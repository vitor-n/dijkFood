#!/usr/bin/env python3
"""
DijkFood — deploy automatizado (Terraform + ECR + RDS + ECS)

Comandos:
    python deploy.py deploy    Aplica infra, build/push das imagens, schema RDS,
                               upload do grafo (S3), force deploy ECS, smoke test opcional.
    python deploy.py destroy   terraform destroy (exige as mesmas credenciais de DB que o apply).
    python deploy.py all       deploy e, em seguida, destroy (com confirmação ou AUTO_DESTROY).
    python deploy.py plan      terraform plan
    python deploy.py smoke     só health checks no ALB (exige state/terraform output).

Variáveis de ambiente:
    DB_PASSWORD         Senha master RDS: repassada ao Terraform via -var (se definida) e ao psycopg2
                        para schema/seed. Obrigatória no deploy salvo SKIP_DB_INIT=1; no destroy pode
                        ficar vazia se estiver só no TF_VAR_FILE.
    DB_USERNAME         Usuário RDS (default: dijkfood_admin).
    TF_VAR_FILE         .tfvars (ex.: dev.tfvars), buscado na raiz do repo e em infra/terraform.
    GRAPH_FILE_PATH     sao_paulo.pkl (default: services/routing-service/data/sao_paulo.pkl).
    SKIP_DB_INIT        Se "1"/"true", não aplica schema.sql no RDS (resto do deploy segue).
    SKIP_SMOKE_TEST     Se "1"/"true", não roda smoke HTTP no ALB após o deploy.
    AUTO_DESTROY        Se "1"/"true", comando `all` destrói sem prompt (CI).
    SKIP_DESTROY        Se "1"/"true", comando `all` não executa destroy após o deploy.

Credenciais AWS: ~/.aws/credentials (não commitar segredos no repositório).

Dependências Python: pip install -r requirements.txt (boto3, psycopg2-binary).
"""
from __future__ import annotations

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

# Ordem estável: deve coincidir com as chaves em module.ecr / outputs ECS
SERVICE_IMAGES: list[tuple[str, str]] = [
    ("core-api", os.path.join("services", "core-api", "Dockerfile")),
    ("routing-service", os.path.join("services", "routing-service", "Dockerfile")),
    ("tracking-service", os.path.join("services", "tracking-service", "Dockerfile")),
    ("order-service", os.path.join("services", "order-service", "Dockerfile")),
]

ECS_SERVICE_OUTPUT_KEYS = [
    "core_api_service_name",
    "routing_service_name",
    "tracking_service_name",
    "order_service_name",
]

DEFAULT_GRAPH = os.path.join(
    PROJECT_ROOT, "services", "routing-service", "data", "sao_paulo.pkl"
)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def run(
    cmd: list[str] | str,
    *,
    cwd: str | None = None,
    capture: bool = False,
    shell: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[Any]:
    kwargs: dict[str, Any] = dict(cwd=cwd, shell=shell, check=check)
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    display = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(f"\n>>> {display}")
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


def tf(args: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
    return run(["terraform", *args], cwd=TF_ABS, **kw)


def tf_output() -> dict[str, Any]:
    result = tf(["output", "-json"], capture=True)
    return json.loads(result.stdout)


def ecr_login(region: str, registry_url: str) -> None:
    registry_host = registry_url.split("/")[0]
    token = run(
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
    print("\n═══ Terraform init ═══")
    tf(["init", "-input=false"])


def stage_terraform_plan(db_user: str, db_pass: str | None) -> None:
    print("\n═══ Terraform plan ═══")
    args = ["plan", "-input=false", *terraform_var_file_args(), *terraform_db_var_args(db_user, db_pass)]
    tf(args)


def stage_terraform_apply(db_user: str, db_pass: str | None) -> None:
    print("\n═══ Terraform apply ═══")
    args = [
        "apply",
        "-auto-approve",
        "-input=false",
        *terraform_var_file_args(),
        *terraform_db_var_args(db_user, db_pass),
    ]
    tf(args)


def stage_terraform_destroy(db_user: str, db_pass: str | None) -> None:
    print("\n═══ Terraform destroy ═══")
    args = [
        "destroy",
        "-auto-approve",
        "-input=false",
        *terraform_var_file_args(),
        *terraform_db_var_args(db_user, db_pass),
    ]
    tf(args)
    print("  Recursos AWS removidos (conforme o state do Terraform).")


def stage_build_push(outputs: dict[str, Any]) -> None:
    print("\n═══ Build e push das imagens (ECR) ═══")
    region = outputs["aws_region"]["value"]
    ecr_urls: dict[str, str] = outputs["ecr_repository_urls"]["value"]

    first_url = next(iter(ecr_urls.values()))
    ecr_login(region, first_url)

    # Todos os 4 serviços adicionados aqui
    services_dockerfiles = {
        "core-api": os.path.join("services", "core-api", "Dockerfile"),
        "routing-service": os.path.join("services", "routing-service", "Dockerfile"),
        "tracking-service": os.path.join("services", "tracking-service", "Dockerfile"),
        "order-service": os.path.join("services", "order-service", "Dockerfile"),
    }

    for svc, dockerfile in services_dockerfiles.items():
        ecr_url = ecr_urls[svc]
        tag = f"{ecr_url}:latest"
        print(f"\n  [{svc}] build → {tag}")
        run(["docker", "build", "-f", dockerfile_rel, "-t", tag, "."], cwd=PROJECT_ROOT)
        print(f"  [{svc}] push")
        run(["docker", "push", tag], cwd=PROJECT_ROOT)


def stage_upload_graph(outputs: dict[str, Any]) -> None:
    print("\n═══ Upload do grafo (S3) ═══")
    graph_path = os.environ.get("GRAPH_FILE_PATH", DEFAULT_GRAPH)
    if not os.path.isfile(graph_path):
        print(f"  [SKIP] Arquivo de grafo não encontrado: {graph_path}")
        return
    bucket = outputs["graph_bucket_name"]["value"]
    run(
        [
            "aws",
            "s3",
            "cp",
            graph_path,
            f"s3://{bucket}/graph/sao_paulo.pkl",
        ]
    )


def stage_init_database(outputs: dict[str, Any], db_user: str, db_pass: str) -> None:
    print("\n═══ Inicialização do schema RDS ═══")
    import psycopg2

    endpoint = outputs["rds_endpoint"]["value"]
    retries, delay = 12, 15
    conn = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=endpoint,
                port=5432,
                dbname="dijkfood",
                user=db_user,
                password=db_pass,
                connect_timeout=10,
            )
            print(f"  Conectado ao RDS: {endpoint}")
            break
        except psycopg2.OperationalError as exc:
            if attempt == retries:
                raise
            print(f"  Tentativa {attempt}/{retries}: {exc} — aguardando {delay}s…")
            time.sleep(delay)

    schema_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "schema.sql")
    seed_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "lookup-data.sql")

    assert conn is not None
    with conn.cursor() as cur:
        for path in (schema_path, seed_path):
            with open(path, encoding="utf-8") as f:
                sql = f.read()
            cur.execute(sql)
            print(f"  Executado: {path}")
    conn.commit()
    conn.close()


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
        svc = outputs[svc_key]["value"]
        run(["aws", "ecs", "update-service",
             "--cluster", cluster,
             "--service", svc,
             "--force-new-deployment",
             "--region", outputs["aws_region"]["value"]],
            capture=True)
        print(f"  Triggered redeployment for {svc}")

    print("\n  Waiting for services to stabilise …")
    for svc_key in services_to_deploy:
        svc = outputs[svc_key]["value"]
        run(["aws", "ecs", "wait", "services-stable",
             "--cluster", cluster,
             "--services", svc,
             "--region", outputs["aws_region"]["value"]])
        print(f"  ✓ {svc} is stable")

    alb_dns = outputs["alb_dns_name"]["value"]
    print(f"\n  API available at: http://{alb_dns}")
    

def stage_smoke_test(outputs: dict[str, Any]) -> None:
    print("\n═══ Smoke test (via ALB) ═══")
    alb_dns = outputs["alb_dns_name"]["value"]
    base = f"http://{alb_dns}"

    urls = [
        (f"{base}/healthz", "core-api"),
        (f"{base}/docs", "core-api OpenAPI"),
        (f"{base}/routes/healthz", "routing-service"),
        (
            f"{base}/tracking/nearby?lat=-23.55&lon=-46.63",
            "tracking-service (nearby)",
        ),
    ]

    for url, label in urls:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=45) as resp:
                print(f"  ✓ [{label}] {url} → HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            # nearby pode retornar 4xx em alguns cenários; aceitamos 2xx/422 de validação
            if exc.code in (400, 422):
                print(f"  ~ [{label}] {url} → HTTP {exc.code} (aceito para smoke)")
            else:
                raise RuntimeError(f"Smoke falhou [{label}] {url}: HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"Smoke falhou [{label}] {url}: {exc}") from exc

    print("  Smoke test concluído.")


def stage_smoke_from_state() -> None:
    """Útil após um deploy manual: lê outputs do Terraform no disco."""
    stage_terraform_init()
    out = tf_output()
    stage_smoke_test(out)


def run_full_deploy(db_user: str, db_password: str | None) -> dict[str, Any]:
    """db_password: repassa ao Terraform (-var) se definida; exigida para psycopg2 exceto com SKIP_DB_INIT."""
    stage_terraform_init()
    stage_terraform_apply(db_user, db_password)
    outputs = tf_output()
    stage_build_push(outputs)
    stage_upload_graph(outputs)
    if _truthy("SKIP_DB_INIT"):
        print("\n  (SKIP_DB_INIT=1 — inicialização do schema RDS ignorada)")
    else:
        if not db_password:
            print(
                "ERRO: DB_PASSWORD é obrigatório para aplicar schema.sql no RDS "
                "(ou use SKIP_DB_INIT=1 se o banco já estiver inicializado)."
            )
            sys.exit(1)
        stage_init_database(outputs, db_user, db_password)
    stage_force_ecs_deploy(outputs)
    if not _truthy("SKIP_SMOKE_TEST"):
        stage_smoke_test(outputs)
    else:
        print("\n  (SKIP_SMOKE_TEST definido — smoke test ignorado)")
    return outputs


def print_usage() -> None:
    print(__doc__)


def main() -> None:
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    action = sys.argv[1].strip().lower()
    valid = ("deploy", "destroy", "all", "plan", "smoke", "help", "-h", "--help")
    if action in ("help", "-h", "--help"):
        print_usage()
        return

    if action not in valid:
        print(f"Comando desconhecido: {sys.argv[1]!r}\n")
        print_usage()
        sys.exit(1)

    db_user = os.environ.get("DB_USERNAME", "dijkfood_admin")
    db_pass_env = os.environ.get("DB_PASSWORD", "").strip() or None

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

    if action == "deploy":
        run_full_deploy(db_user, db_pass_env)
        return

    if action == "all":
        run_full_deploy(db_user, db_pass_env)
        if _truthy("SKIP_DESTROY"):
            print("\nSKIP_DESTROY=1 — não executando destroy.")
            return
        if not _truthy("AUTO_DESTROY"):
            input("\nPressione Enter para executar terraform destroy (ou Ctrl+C para cancelar)… ")
        stage_terraform_destroy(db_user, db_pass_env)
        return

    print_usage()
    sys.exit(1)


if __name__ == "__main__":
    main()
