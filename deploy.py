#!/usr/bin/env python3
"""
DijkFood — deploy automatizado (Terraform + ECR + RDS + ECS)

Comandos:
    python deploy.py deploy    Aplica a infraestrutura, faz build/push das imagens, força o deploy ECS e faz smoke test.
    python deploy.py update    Recompila e faz push das imagens do docker.
    python deploy.py destroy   Destrói a infraestrutura com o Terraform (exige as mesmas credenciais de DB que o apply).
    python deploy.py all       Faz deploy, executa testes e destrói a infraestrutura (com confirmação ou AUTO_DESTROY).
    python deploy.py plan      Apenas executa o `terraform plan` para análise da infraestrutura
    python deploy.py smoke     Faz só health checks no ALB (exige state/terraform output).
    python deploy.py simulate  Executa (na máquina EC2 criada na AWS) a simulação de requests

Variáveis de ambiente:
    DB_PASSWORD         Senha master RDS: repassada ao Terraform via -var (se definida). Obrigatória no deploy salvo SKIP_DB_INIT=1; no destroy pode ficar vazia se estiver só no TF_VAR_FILE.
    DB_USERNAME         Usuário RDS (default: dijkfood_admin).
    TF_VAR_FILE         .tfvars (ex.: dev.tfvars), buscado na raiz do repo e em infra/terraform.
    AUTO_DESTROY        Se "1"/"true", comando `all` destrói sem prompt (CI).
    SKIP_DESTROY        Se "1"/"true", comando `all` não executa destroy após o deploy.
    SCENARIO            O cenário para rodar a simulação. Ver documentação do arquivo mock/bootstrap/src/simulator.py

Credenciais AWS: ~/.aws/credentials (não commitar segredos no repositório).

Dependências Python: pip install -r requirements.txt (boto3, psycopg2-binary, python_dotenv).
"""
from __future__ import annotations

import boto3
from dotenv import load_dotenv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TERRAFORM_DIR = os.path.join("infra", "terraform")
TF_ABS = os.path.join(PROJECT_ROOT, TERRAFORM_DIR)

def retrieve_lab_role_arn():
    try:
        iam_client = boto3.client("iam")
        response = iam_client.get_role(RoleName = "LabRole")
        arn = response["Role"]["Arn"]
        print(f"Usando LabRole {arn} encontrada automaticamente.")
        return arn
    except Exception as e:
        print(f"Erro ao acessar a LabRole: {e}")
        raise

def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def run_command(cmd, *, cwd = None, capture = False, shell = False, check = True):
    kwargs = dict(cwd = cwd, shell = shell, check = check)
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    display = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(f"\n running command {display}")
    return subprocess.run(cmd, **kwargs)

def terraform_var_file_args() -> list[str]:
    raw = os.environ.get("TF_VAR_FILE", "").strip()
    if not raw:
        return []
    candidates = [
        raw,
        os.path.join(PROJECT_ROOT, raw),
        os.path.join(TF_ABS, raw),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return ["-var-file=" + os.path.normpath(p)]
    raise FileNotFoundError(
        f"TF_VAR_FILE={raw!r} não encontrado (tente caminho relativo à raiz do repo ou a {TERRAFORM_DIR})"
    )

def terraform_db_var_args(db_user: str, db_pass: str | None, arn_role) -> list[str]:
    """Só injeta -var de DB se a senha vier no ambiente (evita sobrescrever tfvars com vazio)."""
    if not db_pass:
        return []
    return [f"-var=db_username={db_user}", f"-var=db_password={db_pass}", f"-var=execution_role_arn={arn_role}", f"-var=task_role_arn={arn_role}"]


def execute_terraform_command(args: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
    return run_command(["terraform", *args], cwd=TF_ABS, **kw)


def tf_output() -> dict[str, Any]:
    result = execute_terraform_command(["output", "-json"], capture=True)
    return json.loads(result.stdout)


def ecr_login(region: str, registry_url: str) -> None:
    """Faz login no ECR usando uma url e a região, para poder subir as imagens do docker"""
    registry_host = registry_url.split("/")[0]
    token = run_command(
        ["aws", "ecr", "get-login-password", "--region", region],
        capture=True,
    ).stdout.strip()
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry_host],
        input=token,
        text=True,
        check=True,
    )


def stage_terraform_init() -> None:
    print("\n═════════ Iniciando terraform ═════════")
    execute_terraform_command(["init", "-input=false"])


def stage_terraform_plan(db_user: str, db_pass: str | None, arn_role) -> None:
    print("\n═══ Terraform plan ═══")
    args = ["plan", "-input=false", *terraform_var_file_args(), *terraform_db_var_args(db_user, db_pass, arn_role)]
    execute_terraform_command(args)


def stage_terraform_apply(db_user: str, db_pass: str | None, arn_role) -> None:
    print("\n═════════ Aplicando infraestrutura definida no Terraform ═════════")
    args = [
        "apply",
        "-auto-approve",
        "-input=false",
        *terraform_var_file_args(),
        *terraform_db_var_args(db_user, db_pass, arn_role),
    ]
    execute_terraform_command(args)


def stage_terraform_destroy(db_user: str, db_pass: str | None, arn_role) -> None:
    print("\n═════════ Destruindo a infraestrutura com Terraform ═════════")
    args = [
        "destroy",
        "-auto-approve",
        "-input=false",
        *terraform_var_file_args(),
        *terraform_db_var_args(db_user, db_pass, arn_role),
    ]
    execute_terraform_command(args)
    print("  Recursos AWS removidos pelo terraform.")


def stage_build_push(outputs: dict[str, Any]) -> None:
    print("\n═════════ Fazendo deploy das imagens docker (ECR) ═════════")
    
    #Pega a região e a url de algum dos repositórios pra poder fazer login com o cli
    region = outputs["aws_region"]["value"]
    ecr_urls = outputs["ecr_repository_urls"]["value"]
    first_url = next(iter(ecr_urls.values())) #pega a url do ecr pra colocar as imagens

    ecr_login(region, first_url)

    #Lista dos caminhos dos containers. Feito na mão pros serviços atuais
    services_dockerfiles = {
        "core-api": os.path.join("services", "core-api", "Dockerfile"),
        "routing-service": os.path.join("services", "routing-service", "Dockerfile"),
        "tracking-service": os.path.join("services", "tracking-service", "Dockerfile"),
        "order-service": os.path.join("services", "order-service", "Dockerfile"),
    }

    for service, dockerfile_path in services_dockerfiles.items():
        print(f"\n  Rodando build e push serviço {service}")
        ecr_url = ecr_urls[service]
        tag = f"{ecr_url}:latest" #coloca como latest para que o ecs atualize sozinho
        run_command(["docker", "build", "-f", dockerfile_path, "-t", tag, "./"], cwd=PROJECT_ROOT)
        run_command(["docker", "push", tag], cwd=PROJECT_ROOT)

def stage_force_ecs_deploy(outputs: dict[str, Any]) -> None:
    print("\n═══ Novo deployment ECS (todas as services) ═══")
    region = outputs["aws_region"]["value"]
    cluster = outputs["ecs_cluster_name"]["value"]
    
    # Todos os 4 serviços incluídos na lista de atualização
    services_to_deploy = [
        "core_api_service_name", 
        "routing_service_name",
        "tracking_service_name",
        "order_service_name"
    ]
    
    for svc_key in services_to_deploy:
        svc = outputs[svc_key]["value"] #pega do output do terraform qual o nome do servico
        run_command(["aws", "ecs", "update-service",
             "--cluster", cluster,
             "--service", svc,
             "--force-new-deployment",
             "--region", region],
            capture=True)
        print(f"  Pedido para redeploy do servico {svc} feito")

    print("\n  Aguardando pela estabilização dos serviços...")
    for svc_key in services_to_deploy:
        svc = outputs[svc_key]["value"]
        run_command(["aws", "ecs", "wait", "services-stable",
             "--cluster", cluster,
             "--services", svc,
             "--region", region])
        print(f"  {svc} está estável")

    alb_dns = outputs["alb_dns_name"]["value"]
    print(f"\n  Link da API com deploy: http://{alb_dns}")
    

def stage_smoke_test(outputs: dict[str, Any]) -> None:
    print("\n═════════ Testando os serviços com deploy (via ALB) ═════════")
    
    alb_dns = outputs["alb_dns_name"]["value"] #pega o link em que o alb colocou os recursos
    base = f"http://{alb_dns}"

    urls = [
        (f"{base}/healthz", "core-api"),
        (f"{base}/docs", "core-api OpenAPI"),
        (f"{base}/routes/healthz", "routing-service"),
        (f"{base}/tracking/nearby?lat=-23.55&lon=-46.63", "tracking-service (nearby)",),
        (f"{base}/order", "order-service")
    ]

    for url, label in urls:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=45) as resp:
                print(f"  [{label}] {url} → status do request HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 405, 422):
                print(f"  ~ [{label}] {url} → status do request HTTP {exc.code} (aceito no teste de saúde)")
            else:
                raise RuntimeError(f"Teste de saúde falhou [{label}] {url}: HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"Teste de saúde falhou [{label}] {url}: {exc}") from exc

    print("  Teste de saúde concluído.")


def stage_smoke_from_state() -> None:
    """Útil após um deploy manual: lê outputs do Terraform no disco."""
    stage_terraform_init()
    out = tf_output()
    stage_smoke_test(out)


#Função principal para executar todo o workflow
def run_full_deploy(db_user: str, db_password: str | None, arn_role) -> dict[str, Any]:
    #Executa terraform init
    stage_terraform_init()

    #Executa o comando terraform apply, espera-se que a variável de ambiente de usuário e a de senham estejam setadas aqui
    stage_terraform_apply(db_user, db_password, arn_role)

    #Pega os outputs do comando do terraform, pra usar eles
    outputs = tf_output()

    #Roda os comandos docker (docker login, docker build e docker push pra cada imagem)
    stage_build_push(outputs)

    #atualiza o ECS pra poder rodar 
    stage_force_ecs_deploy(outputs)

    #Faz um check básico da saúde dos serviços
    stage_smoke_test(outputs)
    
    return outputs

def stage_run_load_test(outputs: dict[str, Any]) -> None:
    print("\n═════════ Rodando simulacao de carga com o EC2 ═════════")
    
    instance_id = outputs.get("load_tester_instance_id", {}).get("value")
    if not instance_id:
        print("[Erro] ID da instância EC2 para testes não encontrada nos outputs.")
        return

    main_path = os.path.join(PROJECT_ROOT, "mock", "bootstrap", "src", "main.py")
    simulator_path = os.path.join(PROJECT_ROOT, "mock", "bootstrap", "src", "simulator.py")
    utils_path = os.path.join(PROJECT_ROOT, "mock", "bootstrap", "src", "utils.py")
    req_path = os.path.join(PROJECT_ROOT, "mock", "bootstrap", "src", "requirements.txt")

    with open(simulator_path, "r", encoding="utf-8") as f:
        simulator_content = f.read()
    with open(main_path, "r", encoding="utf-8") as f:
        main_content = f.read()
    with open(utils_path, "r", encoding="utf-8") as f:
        utils_content = f.read()
    with open(req_path, "r", encoding="utf-8") as f:
        simulator_requirements = f.read()
    
    
    scenario: str = os.getenv("SCENARIO", "normal")
    #Essa stack de comandos vai ser executada no EC2, pra poder rodar o arquivo
    commands = [
        "#!/bin/bash",
        "set -e",
        "cd /home/ec2-user",
        "sudo dnf install -y python3-pip",
        "mkdir -p mock_test",
        "cd mock_test",
        "cat << \"EOF_REQ\" > requirements.txt",
        simulator_requirements,
        "EOF_REQ",
        "cat << \"EOF_UTILS\" > utils.py",
        utils_content,
        "EOF_UTILS",
        "cat << \"EOF_MAIN\" > main.py",
        main_content,
        "EOF_MAIN",
        "cat << \"EOF_SIM\" > simulator.py",
        simulator_content,
        "EOF_SIM",
        "pip3 install -r requirements.txt",
        "set -a; source /etc/environment; set +a",
        "echo \"═════════ Iniciando Populate ═════════\"",
        f"SCENARIO={scenario} python3 -u main.py",
        "echo \"═════════ Iniciando Simulacao ═════════\"",
        f"SCENARIO={scenario} python3 -u simulator.py"
    ]

    log_group_name = "/aws/ssm/dijkfood-full-simulation"

    aws_region = outputs.get("aws_region", {}).get("value") or "us-east-1"
    ssm_client = boto3.client("ssm", region_name = aws_region)
    
    print("Enviando scripts de simulação para o EC2 via SSM...")
    try:
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
            CloudWatchOutputConfig={
                "CloudWatchLogGroupName": log_group_name,
                "CloudWatchOutputEnabled": True
            }
        )
        cmd_id = response["Command"]["CommandId"]
        
        cw_group_encoded = log_group_name.replace("/", "$252F")
        cw_url = f"https://{aws_region}.console.aws.amazon.com/cloudwatch/home?region={aws_region}#logsV2:log-groups/log-group/{cw_group_encoded}"
        
        print(f"Simulação Iniciada na EC2 (id {cmd_id})")
        print("É possível acompanhar os outputs da simulação pelo link:")
        print(f"{cw_url}\n")

        while True:
            time.sleep(10)
            print(".", end = "")
            try:
                inv = ssm_client.get_command_invocation(
                    CommandId = cmd_id,
                    InstanceId = instance_id
                )
                status = inv["Status"]
                if status not in ("Pending", "InProgress", "Delayed"):
                    print("\nProcesso da simulação finalizado com status: " + status)
                    break
            except ssm_client.exceptions.InvocationDoesNotExist:
                continue

    except Exception as exc:
        print(f"  Falha ao iniciar/monitorar a simulação: {exc}")

def print_usage() -> None:
    print(__doc__)


def main() -> None:
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    action = sys.argv[1].strip().lower()
    valid = ("deploy", "destroy", "all", "plan", "smoke", "help", "simulate", "-h", "--help")
    if action in ("help", "-h", "--help"):
        print_usage()
        return

    if action not in valid:
        print(f"Comando desconhecido: {sys.argv[1]!r}\n")
        print_usage()
        sys.exit(1)

    load_dotenv()
    db_user = os.environ.get("DB_USERNAME", "dijkfood_admin")
    db_pass_env = os.environ.get("DB_PASSWORD", "12345678").strip() or None
    arn_role = retrieve_lab_role_arn()

    if action == "plan":
        stage_terraform_init()
        stage_terraform_plan(db_user, db_pass_env, arn_role)
        return

    if action == "smoke":
        stage_smoke_from_state()
        return

    if action == "destroy":
        stage_terraform_init()
        stage_terraform_destroy(db_user, db_pass_env, arn_role)
        return

    if action == "update":
        out = tf_output()
        stage_build_push(out)

    if action == "deploy":
        run_full_deploy(db_user, db_pass_env, arn_role)
        return

    if action == "simulate":
        out = tf_output()
        stage_run_load_test(out)
        return

    if action == "all":
        outputs = run_full_deploy(db_user, db_pass_env, arn_role)
        stage_run_load_test(outputs)
        if _truthy("SKIP_DESTROY"):
            print("\nSKIP_DESTROY=1 — não executando destroy.")
            return
        if not _truthy("AUTO_DESTROY"):
            input("\nPressione Enter para executar terraform destroy (ou Ctrl+C para cancelar)... ")
        print("Destruindo infraestrutura")
        stage_terraform_destroy(db_user, db_pass_env, arn_role)
        return

    print_usage()
    sys.exit(1)


if __name__ == "__main__":
    main()
