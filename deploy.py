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

def terraform_db_var_args(db_user: str, db_pass: str | None) -> list[str]:
    """Só injeta -var de DB se a senha vier no ambiente (evita sobrescrever tfvars com vazio)."""
    if not db_pass:
        return []
    return [f"-var=db_username={db_user}", f"-var=db_password={db_pass}"]


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


def check_docker_ready() -> None:
    """Falha cedo com uma mensagem clara se o Docker daemon não estiver disponível."""
    try:
        run_command(["docker", "info"], capture=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Docker não está pronto. Abra o Docker Desktop e aguarde o engine Linux iniciar antes de rodar o deploy."
        ) from exc


def stage_terraform_init() -> None:
    print("\n======== Iniciando terraform ========")
    execute_terraform_command(["init", "-input=false"])


def stage_terraform_plan(db_user: str, db_pass: str | None) -> None:
    print("\n=== Terraform plan ===")
    args = ["plan", "-input=false", *terraform_var_file_args(), *terraform_db_var_args(db_user, db_pass)]
    execute_terraform_command(args)


def stage_terraform_apply(db_user: str, db_pass: str | None) -> None:
    print("\n========= Aplicando infraestrutura definida no Terraform =========")
    args = [
        "apply",
        "-auto-approve",
        "-input=false",
        *terraform_var_file_args(),
        *terraform_db_var_args(db_user, db_pass),
    ]
    execute_terraform_command(args)


def stage_terraform_destroy(db_user: str, db_pass: str | None) -> None:
    print("\n========= Destruindo a infraestrutura com Terraform =========")
    args = [
        "destroy",
        "-auto-approve",
        "-input=false",
        *terraform_var_file_args(),
        *terraform_db_var_args(db_user, db_pass),
    ]
    execute_terraform_command(args)
    print("  Recursos AWS removidos pelo terraform.")


def stage_build_push(outputs: dict[str, Any]) -> None:
    print("\n======== Fazendo deploy das imagens docker (ECR) ========")
    
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
        # Camada analítica / Objetivo 3
        "dashboard-service": os.path.join("services", "dashboard-service", "Dockerfile"),
        "prediction-service": os.path.join("services", "prediction-service", "Dockerfile"),
        "assistant-service": os.path.join("services", "assistant-service", "Dockerfile"),
    }

    for service, dockerfile_path in services_dockerfiles.items():
        print(f"\n  Rodando build e push serviço {service}")
        ecr_url = ecr_urls[service]
        tag = f"{ecr_url}:latest" #coloca como latest para que o ecs atualize sozinho
        run_command(["docker", "build", "-f", dockerfile_path, "-t", tag, "./"], cwd=PROJECT_ROOT)
        run_command(["docker", "push", tag], cwd=PROJECT_ROOT)

def stage_upload_ml_assets(outputs: dict[str, Any]) -> None:
    """Empacota o código de treino (SageMaker) e o catálogo semântico no S3.

    O Step Functions/SageMaker lê o sourcedir.tar.gz com o train_eta.py; o
    assistant-service pode ler overrides do catálogo semântico em semantic/.
    """
    import io
    import tarfile

    bucket = outputs.get("datalake_bucket_name", {}).get("value")
    if not bucket:
        print("[ML] datalake_bucket_name ausente nos outputs — pulando upload de assets de ML.")
        return

    region = outputs.get("aws_region", {}).get("value") or "us-east-1"
    s3 = boto3.client("s3", region_name=region)

    # 1) sourcedir.tar.gz com o entrypoint de treino (script mode do SageMaker)
    ml_dir = os.path.join(PROJECT_ROOT, "infra", "ml")
    if os.path.isdir(ml_dir):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for fname in os.listdir(ml_dir):
                fpath = os.path.join(ml_dir, fname)
                if os.path.isfile(fpath):
                    tar.add(fpath, arcname=fname)
        buf.seek(0)
        s3.put_object(Bucket=bucket, Key="ml/sourcedir.tar.gz", Body=buf.getvalue())
        print(f"  [ML] sourcedir.tar.gz enviado para s3://{bucket}/ml/sourcedir.tar.gz")

    # 2) Script do Glue ETL (curated/marts em Parquet)
    glue_script = os.path.join(PROJECT_ROOT, "infra", "glue", "build_marts.py")
    if os.path.isfile(glue_script):
        with open(glue_script, "rb") as f:
            s3.put_object(Bucket=bucket, Key="glue/build_marts.py", Body=f.read())
        print(f"  [ML] Glue ETL enviado para s3://{bucket}/glue/build_marts.py")

    # 3) Catálogo semântico (opcional — overrides do assistant-service)
    sem_dir = os.path.join(PROJECT_ROOT, "infra", "semantic")
    if os.path.isdir(sem_dir):
        for fname in os.listdir(sem_dir):
            fpath = os.path.join(sem_dir, fname)
            if os.path.isfile(fpath) and fname.endswith(".json"):
                with open(fpath, "rb") as f:
                    s3.put_object(Bucket=bucket, Key=f"semantic/{fname}", Body=f.read(),
                                  ContentType="application/json")
        print(f"  [ML] catálogo semântico enviado para s3://{bucket}/semantic/")


def stage_build_osrm_data(outputs: dict[str, Any]) -> None:
    """Converte sao_paulo.pkl → arquivos .osrm e os salva no S3 usando a EC2 via SSM.

    Fluxo:
      1. Sobe o sao_paulo.pkl e o pkl_to_osm.py para o bucket S3 do grafo.
      2. Na EC2 (via SSM): baixa os arquivos, converte pkl→osm, roda
         osrm-extract / osrm-partition / osrm-customize via Docker.
      3. Sincroniza os arquivos .osrm resultantes para s3://<bucket>/osrm/processed/.

    Os containers ECS baixam os arquivos desse prefixo no startup.
    """
    print("\n======== Pré-processando grafo OSRM na EC2 ========")

    graph_bucket = outputs.get("graph_bucket_name", {}).get("value")
    if not graph_bucket:
        raise RuntimeError("graph_bucket_name ausente nos outputs do Terraform.")

    region = outputs.get("aws_region", {}).get("value") or "us-east-1"
    instance_id = outputs.get("load_tester_instance_id", {}).get("value")
    if not instance_id:
        raise RuntimeError("load_tester_instance_id ausente nos outputs — EC2 não encontrada.")

    # 1. Sobe pkl e script de conversão para o S3
    s3 = boto3.client("s3", region_name=region)

    pkl_path  = os.path.join(PROJECT_ROOT, "services", "routing-service", "data", "sao_paulo.pkl")
    conv_path = os.path.join(PROJECT_ROOT, "mock", "bootstrap", "src", "pkl_to_osm.py")

    print(f"  Enviando sao_paulo.pkl ({os.path.getsize(pkl_path) // (1024*1024)} MB) para S3...")
    s3.upload_file(pkl_path, graph_bucket, "osrm/sao_paulo.pkl")

    with open(conv_path, "rb") as f:
        s3.put_object(Bucket=graph_bucket, Key="osrm/pkl_to_osm.py", Body=f.read())

    print(f"  Arquivos enviados para s3://{graph_bucket}/osrm/")

    # 2. Script shell executado na EC2 via SSM
    commands = [
        "#!/bin/bash",
        "set -e",
        "cd /home/ec2-user",
        # Instala dependências
        "sudo dnf install -y python3-pip docker",
        "sudo systemctl start docker",
        "pip3 install networkx boto3 --quiet",
        # Cria diretório de trabalho isolado
        "rm -rf osrm_build && mkdir -p osrm_build && cd osrm_build",
        # Baixa pkl e script do S3
        f"aws s3 cp s3://{graph_bucket}/osrm/sao_paulo.pkl . --region {region}",
        f"aws s3 cp s3://{graph_bucket}/osrm/pkl_to_osm.py . --region {region}",
        # Converte pkl → .osm
        "echo '>>> Convertendo pkl para .osm...'",
        "python3 pkl_to_osm.py sao_paulo.pkl sao_paulo.osm",
        "echo '>>> Conversão concluída'",
        # Pré-processa com OSRM via Docker (sem instalação nativa)
        "sudo docker pull ghcr.io/project-osrm/osrm-backend:v5.27.1",
        "echo '>>> Rodando osrm-extract...'",
        "sudo docker run --rm -v $(pwd):/data ghcr.io/project-osrm/osrm-backend:v5.27.1 "
        "osrm-extract -p /opt/car.lua /data/sao_paulo.osm",
        "echo '>>> Rodando osrm-partition...'",
        "sudo docker run --rm -v $(pwd):/data ghcr.io/project-osrm/osrm-backend:v5.27.1 "
        "osrm-partition /data/sao_paulo.osrm",
        "echo '>>> Rodando osrm-customize...'",
        "sudo docker run --rm -v $(pwd):/data ghcr.io/project-osrm/osrm-backend:v5.27.1 "
        "osrm-customize /data/sao_paulo.osrm",
        "echo '>>> Pré-processamento OSRM concluído'",
        # Sobe os arquivos .osrm para S3 (exclui pkl e osm — só artefatos do OSRM)
        f"aws s3 sync . s3://{graph_bucket}/osrm/processed/ --region {region} "
        "--exclude '*.osm' --exclude '*.pkl' --exclude 'pkl_to_osm.py'",
        "echo '>>> Upload para S3 concluído'",
    ]

    ssm = boto3.client("ssm", region_name=region)

    print(f"  Enviando script de pré-processamento para EC2 ({instance_id}) via SSM...")
    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
    )
    cmd_id = response["Command"]["CommandId"]
    print(f"  SSM Command iniciado (ID: {cmd_id}). Aguardando (~8-12 min)...")

    while True:
        time.sleep(20)
        print(".", end="", flush=True)
        try:
            inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
            status = inv["Status"]
            if status not in ("Pending", "InProgress", "Delayed"):
                print(f"\n  SSM concluído com status: {status}")
                if status != "Success":
                    print(f"Stdout:\n{inv.get('StandardOutputContent')}")
                    print(f"Stderr:\n{inv.get('StandardErrorContent')}")
                    raise RuntimeError(f"Pré-processamento OSRM falhou com status: {status}")
                break
        except ssm.exceptions.InvocationDoesNotExist:
            continue

    print(f"  Arquivos OSRM disponíveis em s3://{graph_bucket}/osrm/processed/")


def stage_force_ecs_deploy(outputs: dict[str, Any]) -> None:
    print("\n=== Novo deployment ECS (todas as services) ===")
    region = outputs["aws_region"]["value"]
    cluster = outputs["ecs_cluster_name"]["value"]
    
    # Serviços ECS (o dashboard NÃO está aqui — roda numa EC2 dedicada)
    services_to_deploy = [
        "core_api_service_name",
        "routing_service_name",
        "tracking_service_name",
        "order_service_name",
        "prediction_service_name",
        "assistant_service_name",
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


def stage_refresh_dashboard_ec2(outputs: dict[str, Any]) -> None:
    """Força a EC2 do dashboard a (re)puxar a imagem recém-publicada via SSM."""
    instance_id = outputs.get("dashboard_instance_id", {}).get("value")
    if not instance_id:
        print("  [dashboard] instance_id ausente — pulando refresh do dashboard.")
        return
    region = outputs.get("aws_region", {}).get("value") or "us-east-1"
    ssm = boto3.client("ssm", region_name=region)
    try:
        ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [
                "for i in $(seq 1 20); do [ -x /usr/local/bin/run-dashboard.sh ] && break; sleep 5; done",
                "/usr/local/bin/run-dashboard.sh || true",
            ]},
        )
        url = outputs.get("dashboard_url", {}).get("value", "")
        print(f"  [dashboard] refresh solicitado na EC2 ({instance_id}). URL: {url}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [dashboard] falha ao solicitar refresh (a EC2 se auto-atualiza via user-data): {exc}")


def stage_smoke_test(outputs: dict[str, Any]) -> None:
    print("\n======== Testando os serviços com deploy (via ALB) ========")
    
    alb_dns = outputs["alb_dns_name"]["value"] #pega o link em que o alb colocou os recursos
    base = f"http://{alb_dns}"

    urls = [
        (f"{base}/healthz", "core-api"),
        (f"{base}/docs", "core-api OpenAPI"),
        (f"{base}/routes/healthz", "routing-service"),
        (f"{base}/tracking/nearby?lat=-23.55&lon=-46.63", "tracking-service (nearby)",),
        (f"{base}/order", "order-service"),
        (f"{base}/chat", "assistant-service"),
        (f"{base}/model/info", "prediction-service"),
    ]

    # Códigos aceitos como "vivo" (a rota existe e respondeu).
    accepted = (200, 201, 400, 401, 403, 404, 405, 422)
    # Códigos de "ainda subindo" no ALB → vale a pena reesperar.
    transient = (502, 503, 504)

    def _probe(url: str, label: str, attempts: int = 8, delay: int = 20) -> bool:
        last = "?"
        for i in range(1, attempts + 1):
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=20) as resp:
                    print(f"  [OK] [{label}] {url} -> HTTP {resp.status}")
                    return True
            except urllib.error.HTTPError as exc:
                if exc.code in accepted:
                    print(f"  [OK] [{label}] {url} -> HTTP {exc.code} (aceito)")
                    return True
                if exc.code not in transient:
                    print(f"  [FALHA] [{label}] {url} -> HTTP {exc.code}")
                    return False
                last = f"HTTP {exc.code}"
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            if i < attempts:
                print(f"  [...] [{label}] subindo ({last}); tentativa {i}/{attempts}, aguardando {delay}s")
                time.sleep(delay)
        print(f"  [FALHA] [{label}] {url} nao respondeu saudavel apos {attempts} tentativas ({last})")
        return False

    failed = [label for url, label in urls if not _probe(url, label)]

    # Dashboard roda numa EC2 dedicada; pode levar ~1-2 min para puxar a imagem.
    dash_url = outputs.get("dashboard_url", {}).get("value")
    if dash_url:
        if not _probe(dash_url + "/healthz", "dashboard-ec2", attempts=6, delay=20):
            print(f"  [~] [dashboard-ec2] {dash_url} ainda subindo a imagem na EC2 (cheque em 1-2 min).")

    if failed:
        print(f"\n  [AVISO] Servicos ainda nao saudaveis: {', '.join(failed)}.")
        print("    A infraestrutura subiu. Rode 'python deploy.py smoke' em ~1 min para revalidar.")
    else:
        print("  Teste de saude concluido (todos os servicos responderam).")


def stage_smoke_from_state() -> None:
    """Útil após um deploy manual: lê outputs do Terraform no disco."""
    stage_terraform_init()
    out = tf_output()
    stage_smoke_test(out)


def stage_rds_init_via_ssm(outputs: dict[str, Any], db_user: str, db_password: str | None) -> None:
    print("\n======== Inicializando banco de dados RDS (via SSM no EC2) ========")
    instance_id = outputs.get("load_tester_instance_id", {}).get("value")
    if not instance_id:
        raise RuntimeError("ID da instância EC2 para inicialização do banco não encontrado nos outputs.")
    
    rds_endpoint = outputs["rds_endpoint"]["value"]
    
    init_db_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "init_db.py")
    schema_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "schema.sql")
    lookup_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "lookup-data.sql")
    
    with open(init_db_path, "r", encoding="utf-8") as f:
        init_db_content = f.read()
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_content = f.read()
    with open(lookup_path, "r", encoding="utf-8") as f:
        lookup_content = f.read()
        
    commands = [
        "#!/bin/bash",
        "set -e",
        "cd /home/ec2-user",
        "sudo dnf install -y python3-pip",
        "mkdir -p db_init",
        "cd db_init",
        "cat << \"EOF_INIT\" > init_db.py",
        init_db_content,
        "EOF_INIT",
        "cat << \"EOF_SCHEMA\" > schema.sql",
        schema_content,
        "EOF_SCHEMA",
        "cat << \"EOF_LOOKUP\" > lookup-data.sql",
        lookup_content,
        "EOF_LOOKUP",
        "pip3 install psycopg2-binary boto3",
        f"python3 init_db.py --host {rds_endpoint} --user {db_user} --dbname dijkfood " + (f"--password {db_password}" if db_password else "")
    ]
    
    aws_region = outputs.get("aws_region", {}).get("value") or "us-east-1"
    ssm_client = boto3.client("ssm", region_name=aws_region)
    
    try:
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands}
        )
        cmd_id = response["Command"]["CommandId"]
        print(f"Comando SSM de inicialização do banco enviado (ID: {cmd_id}). Aguardando conclusão...")
        
        while True:
            time.sleep(5)
            print(".", end="", flush=True)
            try:
                inv = ssm_client.get_command_invocation(
                    CommandId=cmd_id,
                    InstanceId=instance_id
                )
                status = inv["Status"]
                if status not in ("Pending", "InProgress", "Delayed"):
                    print(f"\nSSM concluído com status: {status}")
                    if status != "Success":
                        print(f"Stdout:\n{inv.get('StandardOutputContent')}")
                        print(f"Stderr:\n{inv.get('StandardErrorContent')}")
                        raise RuntimeError(f"Inicialização do banco via SSM falhou com status {status}")
                    break
            except ssm_client.exceptions.InvocationDoesNotExist:
                continue
    except Exception as exc:
        print(f"\n[Erro] Falha ao executar inicialização no EC2 via SSM: {exc}")
        raise


#Função principal para executar todo o workflow
def run_full_deploy(db_user: str, db_password: str | None) -> dict[str, Any]:
    #Executa terraform init
    stage_terraform_init()

    #Executa o comando terraform apply, espera-se que a variável de ambiente de usuário e a de senham estejam setadas aqui
    stage_terraform_apply(db_user, db_password)

    #Pega os outputs do comando do terraform, pra usar eles
    outputs = tf_output()

    # Inicializa o banco de dados RDS (Executa schema e seeds uma única vez de dentro da VPC)
    stage_rds_init_via_ssm(outputs, db_user, db_password)

    #Empacota e envia o código de treino (SageMaker) + catálogo semântico ao S3
    stage_upload_ml_assets(outputs)

    # Pré-processa o grafo de SP com OSRM na EC2 e salva os artefatos no S3.
    # Feito ANTES do build/push para que os containers ECS já encontrem os
    # arquivos .osrm disponíveis no S3 ao subir pela primeira vez.
    stage_build_osrm_data(outputs)

    #Roda os comandos docker (docker login, docker build e docker push pra cada imagem)
    stage_build_push(outputs)

    #atualiza o ECS pra poder rodar
    stage_force_ecs_deploy(outputs)

    #atualiza o container do dashboard na EC2 dedicada (imagem recém-publicada)
    stage_refresh_dashboard_ec2(outputs)

    #Faz um check básico da saúde dos serviços
    stage_smoke_test(outputs)
    
    return outputs

def stage_run_load_test(outputs: dict[str, Any]) -> None:
    print("\n======== Rodando simulacao de carga com o EC2 ========")
    
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
    tracking_lifetime: str = os.getenv("TRACKING_LIFETIME", 5.0)
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
        "echo \"========= Iniciando Populate ========\"",
        f"PYTHONIOENCODING=utf-8 SCENARIO={scenario} TRACKING_LIFETIME={tracking_lifetime} python3 -u main.py",
        "echo \"========= Iniciando Simulacao ========\"",
        f"PYTHONIOENCODING=utf-8 SCENARIO={scenario} TRACKING_LIFETIME={tracking_lifetime} python3 -u simulator.py"
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
    valid = ("deploy", "update", "destroy", "all", "plan", "smoke", "help", "simulate", "-h", "--help")
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

    if action == "plan":
        stage_terraform_init()
        stage_terraform_plan(db_user, db_pass_env)
        return

    if action == "smoke":
        stage_smoke_from_state()
        return

    if action == "destroy":
        stage_terraform_init()
        stage_terraform_destroy(db_user, db_pass_env)
        return

    if action == "update":
        check_docker_ready()
        out = tf_output()
        stage_build_push(out)
        stage_force_ecs_deploy(out)
        stage_refresh_dashboard_ec2(out)
        return

    if action == "deploy":
        check_docker_ready()
        run_full_deploy(db_user, db_pass_env)
        return

    if action == "simulate":
        out = tf_output()
        stage_run_load_test(out)
        return

    if action == "all":
        check_docker_ready()
        outputs = run_full_deploy(db_user, db_pass_env)
        stage_run_load_test(outputs)
        if _truthy("SKIP_DESTROY"):
            print("\nSKIP_DESTROY=1 — não executando destroy.")
            return
        if not _truthy("AUTO_DESTROY"):
            input("\nPressione Enter para executar terraform destroy (ou Ctrl+C para cancelar)... ")
        print("Destruindo infraestrutura")
        stage_terraform_destroy(db_user, db_pass_env)
        return

    print_usage()
    sys.exit(1)


if __name__ == "__main__":
    main()
