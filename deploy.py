#!/usr/bin/env python3
"""
DijkFood — Automated Deployment Script

Creates all AWS resources, deploys services, optionally runs the load
test, and tears everything down.

Usage:
    python deploy.py deploy              # provision infra + push images
    python deploy.py destroy             # tear down all AWS resources
    python deploy.py all                 # deploy ➜ test ➜ destroy

Environment variables (required for deploy):
    DB_PASSWORD         RDS master password
    GRAPH_FILE_PATH     Local path to sao_paulo.pkl (for S3 upload)

Optional:
    DB_USERNAME         RDS master username (default: dijkfood_admin)
    AWS_REGION          AWS region          (default: us-east-1)
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time

TERRAFORM_DIR = os.path.join("infra", "terraform")
DOCKER_DIR = os.path.join("infra", "docker")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

import urllib.request
import urllib.error

def stage_smoke_test(outputs: dict):
    print("\n═══ Smoke test ═══")
    alb_dns = outputs["alb_dns_name"]["value"]

    urls = [
        f"http://{alb_dns}/healthz",
        f"http://{alb_dns}/docs",
        f"http://{alb_dns}/routes/healthz",
    ]

    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                print(f"  ✓ {url} -> {resp.status}")
        except Exception as exc:
            raise RuntimeError(f"Smoke test failed for {url}: {exc}")


# ─── helpers ────────────────────────────────────────────────────────

def run(cmd: list[str] | str, *, cwd: str | None = None,
        capture: bool = False, shell: bool = False, check: bool = True):
    """Run a subprocess with live output unless capture=True."""
    kwargs: dict = dict(cwd=cwd, shell=shell, check=check)
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    print(f"\n>>> {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def tf(args: list[str], **kw):
    """Run a terraform sub-command inside the terraform directory."""
    return run(["terraform"] + args, cwd=os.path.join(PROJECT_ROOT, TERRAFORM_DIR), **kw)


def tf_output() -> dict:
    result = tf(["output", "-json"], capture=True)
    return json.loads(result.stdout)


# def ecr_login(region: str, registry_url: str):
#     """Authenticate Docker with ECR."""
#     registry_host = registry_url.split("/")[0]
#     if platform.system() == "Windows":
#         cmd = (
#             f'aws ecr get-login-password --region {region} '
#             f'| docker login --username AWS --password-stdin {registry_host}'
#         )
#         run(cmd, shell=True)
#     else:
#         token = run(
#             ["aws", "ecr", "get-login-password", "--region", region],
#             capture=True,
#         ).stdout.strip()
#         run(["docker", "login", "--username", "AWS",
#              "--password-stdin", registry_host],
#             shell=False,
#             check=True,
#             capture=False)

def ecr_login(region: str, registry_url: str):
    registry_host = registry_url.split("/")[0]

    token = run(
        ["aws", "ecr", "get-login-password", "--region", region],
        capture=True,
    ).stdout.strip()

    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry_host],
        input=token,
        text=True,
        check=True
    )


# ─── stages ─────────────────────────────────────────────────────────

def stage_terraform_init():
    print("\n═══ Stage 1/6: Terraform init ═══")
    tf(["init", "-input=false"])


def stage_terraform_apply(db_user: str, db_pass: str):
    print("\n═══ Stage 2/6: Terraform apply ═══")
    tf([
        "apply", "-auto-approve", "-input=false",
        f"-var=db_username={db_user}",
        f"-var=db_password={db_pass}",
    ])


def stage_build_push(outputs: dict):
    print("\n═══ Stage 3/6: Build & push Docker images ═══")
    region = outputs["aws_region"]["value"]
    ecr_urls: dict = outputs["ecr_repository_urls"]["value"]

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
        print(f"\n  Building {svc} …")
        run(["docker", "build", "-f", dockerfile, "-t", tag, "."],
            cwd=PROJECT_ROOT)
        print(f"  Pushing {svc} …")
        run(["docker", "push", tag], cwd=PROJECT_ROOT)


def stage_upload_graph(outputs: dict):
    print("\n═══ Stage 4/6: Upload graph to S3 ═══")
    # graph_path = os.environ.get("GRAPH_FILE_PATH", "data/sao_paulo.pkl")
    graph_path = os.environ.get(
    "GRAPH_FILE_PATH",
    os.path.join(PROJECT_ROOT, "services", "routing-service", "data", "sao_paulo.pkl")
    )
    if not os.path.exists(graph_path):
        print(f"  [SKIP] Graph file not found at {graph_path}")
        return
    bucket = outputs["graph_bucket_name"]["value"]
    run(["aws", "s3", "cp", graph_path,
         f"s3://{bucket}/graph/sao_paulo.pkl"])


def stage_init_database(outputs: dict, db_user: str, db_pass: str):
    print("\n═══ Stage 5/6: Initialize database schema ═══")
    import psycopg2

    endpoint = outputs["rds_endpoint"]["value"]
    retries, delay = 10, 15
    conn = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=endpoint, port=5432, dbname="dijkfood",
                user=db_user, password=db_pass, connect_timeout=10,
            )
            print(f"  Connected to RDS ({endpoint})")
            break
        except psycopg2.OperationalError as exc:
            if attempt == retries:
                raise
            print(f"  Attempt {attempt}/{retries}: {exc}  — retrying in {delay}s")
            time.sleep(delay)

    # schema_path = os.path.join("infra", "database", "rds", "schema.sql")
    # seed_path = os.path.join("infra", "database", "rds", "lookup-data.sql")
    schema_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "schema.sql")
    seed_path = os.path.join(PROJECT_ROOT, "infra", "database", "rds", "lookup-data.sql")

    with conn.cursor() as cur:
        for path in [schema_path, seed_path]:
            with open(path) as f:
                sql = f.read()
            cur.execute(sql)
            print(f"  Executed {path}")
    conn.commit()
    conn.close()


def stage_force_deploy(outputs: dict):
    print("\n═══ Stage 6/6: Force new ECS deployment ═══")
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
    

def stage_destroy():
    print("\n═══ Terraform destroy ═══")
    tf([
        "destroy", "-auto-approve", "-input=false",
        f"-var=db_username={db_user}",
        f"-var=db_password={db_pass}",
    ])
    print("  All resources destroyed.")

# ─── main ───────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("deploy", "destroy", "all"):
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]

    if action in ("deploy", "all"):
        db_user = os.environ.get("DB_USERNAME", "dijkfood_admin")
        db_pass = os.environ.get("DB_PASSWORD")
        if not db_pass:
            print("ERROR: set the DB_PASSWORD environment variable.")
            sys.exit(1)

        stage_terraform_init()
        stage_terraform_apply(db_user, db_pass)
        outputs = tf_output()
        stage_build_push(outputs)
        stage_upload_graph(outputs)
        stage_init_database(outputs, db_user, db_pass)
        stage_force_deploy(outputs)

    if action in ("destroy", "all"):
        if action == "all":
            keep_alive = os.environ.get("KEEP_ALIVE_AFTER_TEST", "false").lower() == "true"
        if not keep_alive:
            stage_destroy()


if __name__ == "__main__":
    main()
