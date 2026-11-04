"""Explicit phase-2 operator; scopes every action to the owned Legal Checker cluster."""

import argparse
import base64
import json
import secrets

import yaml

from .common import (
    CONTRACT,
    PRIVATE,
    ROOT,
    apply,
    checkout,
    imported_image,
    kube,
    kube_command,
    load,
    owner,
    run,
    save,
    settings,
    sha,
    source_identity,
)

NAMESPACES = ("legal-localstack", "legal-secrets", "legal-edge", "legal-observability")


def helm(release):
    owner()
    pin = load(ROOT / "versions/phase2.lock.json")["charts"][release]
    folder = PRIVATE / "charts"
    folder.mkdir(exist_ok=True)
    archive = folder / (pin["chart"] + "-" + pin["version"] + ".tgz")
    if not archive.exists():
        run(
            [
                "helm",
                "pull",
                pin["chart"],
                "--repo",
                pin["repo"],
                "--version",
                pin["version"],
                "--destination",
                str(folder),
            ]
        )
    if sha(archive) != pin["sha256"]:
        raise ValueError("Helm chart checksum mismatch: " + release)
    run(
        [
            "helm",
            "upgrade",
            "--install",
            release,
            str(archive),
            "--kubeconfig",
            str(PRIVATE / "kubeconfig"),
            "--kube-context",
            CONTRACT["context"],
            "--namespace",
            pin["namespace"],
            "--values",
            str(ROOT / "local/values" / pin["values"]),
            "--wait",
            "--timeout",
            "10m",
        ]
    )


def seed_secrets():
    """Read existing keys in memory; preserve DB password, don't print secret payloads."""
    credentials = load(PRIVATE / "credentials.json")
    values = {}
    for name in ("legal-database", "legal-redis", "legal-llm-secret"):
        result = kube(
            "get", "secret", name, "--ignore-not-found", "-o", "json", capture=True
        )
        values[name] = (
            {
                key: base64.b64decode(value).decode()
                for key, value in json.loads(result).get("data", {}).items()
            }
            if result.strip()
            else {}
        )
    if not values["legal-database"].get("DATABASE_URL"):
        raise ValueError(
            "Bootstrap the existing DB Secret first; no password reset is attempted"
        )
    redis = values["legal-redis"]
    redis.setdefault("password", credentials["redis_password"])
    from urllib.parse import quote

    redis["REDIS_URL"] = (
        "redis://:" + quote(redis["password"], safe="") + "@redis:6379/0"
    )
    # Merge targets must exist before ESO reconciliation, even for an empty LLM set.
    for name, payload in values.items():
        if name == "legal-llm-secret" and not payload:
            payload["CONFIGURED"] = "false"
        apply(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": name},
                    "type": "Opaque",
                    "stringData": payload,
                }
            ]
        )
    script = """import boto3,json,sys
client=boto3.client('secretsmanager',endpoint_url='http://127.0.0.1:4566',
 region_name='ap-southeast-1',aws_access_key_id='test',aws_secret_access_key='test')
for name,value in json.loads(sys.stdin.read()).items():
 key='legal-checker/local/'+name
 try: client.describe_secret(SecretId=key)
 except client.exceptions.ResourceNotFoundException:
  client.create_secret(Name=key,SecretString=json.dumps(value))
 else: client.put_secret_value(SecretId=key,SecretString=json.dumps(value))
print('Local Secrets Manager values synchronized; payloads omitted')
"""
    kube(
        "exec",
        "-i",
        "deployment/localstack",
        "--",
        "python",
        "-c",
        script,
        namespace="legal-localstack",
        stdin=json.dumps(
            {
                "database": values["legal-database"],
                "redis": redis,
                "llm": values["legal-llm-secret"],
            }
        ),
    )


def install(_):
    owner()
    for namespace in NAMESPACES:
        apply(
            [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}}]
        )
    apply(
        list(
            yaml.safe_load_all((ROOT / "local/manifests/localstack.yaml").read_text())
        ),
        namespace="legal-localstack",
    )
    kube(
        "rollout",
        "status",
        "deployment/localstack",
        "--timeout=300s",
        namespace="legal-localstack",
    )
    seed_secrets()
    apply(
        [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "legal-localstack-auth"},
                "stringData": {"access-key": "test", "secret-key": "test"},
            }
        ],
        namespace="legal-secrets",
    )
    helm("legal-secrets")
    apply(
        list(
            yaml.safe_load_all((ROOT / "local/manifests/secret-store.yaml").read_text())
        )
    )
    kube(
        "wait",
        "--for=condition=Ready",
        "clustersecretstore/legal-local-aws",
        "--timeout=180s",
    )
    helm("legal-edge")
    password = PRIVATE / "grafana.json"
    if not password.exists():
        save(
            password,
            {"admin-user": "admin", "admin-password": secrets.token_urlsafe(32)},
        )
    apply(
        [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "legal-grafana-admin"},
                "stringData": load(password),
            }
        ],
        namespace="legal-observability",
    )
    for release in ("legal-monitoring", "legal-loki", "legal-alloy"):
        helm(release)
    apply(
        list(yaml.safe_load_all((ROOT / "local/manifests/dashboard.yaml").read_text())),
        namespace="legal-observability",
    )
    save(
        PRIVATE / "phase2-platform.json",
        {
            "cluster_id": owner()["cluster_id"],
            "chart_lock_sha256": sha(ROOT / "versions/phase2.lock.json"),
            "installed": True,
        },
    )


def build_frontend(args):
    """Build/import the existing frontend Dockerfile with its correct frontend context."""
    owner()
    source = checkout("app")
    identity = source_identity(source)
    if identity["dirty"] and not args.allow_dirty:
        raise ValueError(
            "Commit app source or explicitly use --allow-dirty for local testing"
        )
    temporary = "legal-local/frontend:build-" + identity["snapshot_sha256"][:16]
    run(
        [
            "docker",
            "build",
            "--file",
            str(source / "frontend/Dockerfile"),
            "--tag",
            temporary,
            str(source / "frontend"),
        ]
    )
    if source_identity(source) != identity:
        raise ValueError("App source changed during frontend build")
    image_id = json.loads(run(["docker", "image", "inspect", temporary], capture=True))[
        0
    ]["Id"]
    alias = "legal-local/frontend:image-" + image_id.removeprefix("sha256:")
    run(["docker", "tag", image_id, alias])
    run(["k3d", "image", "import", "--cluster", CONTRACT["cluster_name"], alias])
    save(
        PRIVATE / "frontend-image.json",
        {
            "schema_version": "1.0.0",
            "image": alias,
            "image_id": image_id,
            "source": identity,
            "cluster_id": owner()["cluster_id"],
        },
    )


def apply_local(args):
    """Apply reviewed local desired state without publishing uncommitted source to GitHub.

    Argo auto-sync is suspended only for these two apps until this branch is published.
    Existing data is never reseeded/deleted; old upload files are preserved separately.
    """
    owner()
    gitops = checkout("gitops")
    receipt = imported_image()
    if args.image != receipt["image"]:
        raise ValueError("Use the exact image imported by this cluster's build receipt")
    frontend_image = getattr(args, "frontend_image", None)
    if frontend_image:
        frontend = load(PRIVATE / "frontend-image.json")
        if (
            frontend["image"] != frontend_image
            or frontend["cluster_id"] != owner()["cluster_id"]
        ):
            raise ValueError(
                "Frontend image must match the current cluster import receipt"
            )
    # Record policies before suspension so the operator can restore the exact settings.
    path = PRIVATE / "phase2-argo-policies.json"
    if not path.exists():
        policies = {}
        for name in ("legal-checker-platform", "legal-checker-backend"):
            app = json.loads(
                kube(
                    "get",
                    "application",
                    name,
                    "-o",
                    "json",
                    namespace="argocd",
                    capture=True,
                )
            )
            policies[name] = app["spec"].get("syncPolicy", {})
        save(path, policies)
    for name in load(path):
        kube(
            "patch",
            "application",
            name,
            "--type=merge",
            "-p",
            json.dumps({"spec": {"syncPolicy": {"automated": None}}}),
            namespace="argocd",
        )
    # Existing emptyDir may contain user uploads: back them up before changing the pod.
    backup = PRIVATE / "phase2-cache-backup"
    if not backup.exists():
        backup.mkdir(mode=0o700)
        pods = json.loads(
            kube("get", "pods", "-l", "app=legal-backend", "-o", "json", capture=True)
        )
        running = [
            pod for pod in pods["items"] if pod["status"].get("phase") == "Running"
        ]
        if running:
            run(
                kube_command(
                    "cp", running[0]["metadata"]["name"] + ":/cache/.", str(backup)
                )
            )
    # Render first: if any root fails, no partial set of workload manifests is applied.
    platform = kube(
        "kustomize", str(gitops / "environments/local/platform"), capture=True
    )
    apps = list(
        yaml.safe_load_all(
            kube("kustomize", str(gitops / "environments/local/apps"), capture=True)
        )
    )
    for item in apps:
        if (
            item
            and item["kind"] == "Deployment"
            and item["metadata"]["name"]
            in {"legal-backend", "legal-worker", "legal-scheduler"}
        ):
            item["spec"]["template"]["spec"]["containers"][0]["image"] = args.image
            item["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] = (
                "Never"
            )
    if frontend_image:
        for item in apps:
            if (
                item
                and item["kind"] == "Deployment"
                and item["metadata"]["name"] == "legal-frontend"
            ):
                container = item["spec"]["template"]["spec"]["containers"][0]
                container["image"] = frontend_image
                container["imagePullPolicy"] = "Never"
    # NetworkPolicy is installed after transfers/migrations, not before owner operations.
    policies = []
    for doc in yaml.safe_load_all(platform):
        if doc and doc["kind"] == "NetworkPolicy":
            policies.append(doc)
        elif doc:
            apply([doc])
    kube("rollout", "status", "statefulset/redis", "--timeout=300s")
    kube("wait", "--for=condition=Ready", "externalsecret", "--all", "--timeout=180s")
    pvcs = [d for d in apps if d and d["kind"] == "PersistentVolumeClaim"]
    apply(pvcs)
    helper = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "legal-files-transfer"},
        "spec": {
            "restartPolicy": "Never",
            "securityContext": {"fsGroup": 10001},
            "containers": [
                {
                    "name": "copy",
                    "image": args.image,
                    "imagePullPolicy": "Never",
                    "command": ["sleep", "600"],
                    "volumeMounts": [{"name": "files", "mountPath": "/cache"}],
                }
            ],
            "volumes": [
                {
                    "name": "files",
                    "persistentVolumeClaim": {"claimName": "legal-shared-files"},
                }
            ],
        },
    }
    apply([helper])
    try:
        kube(
            "wait",
            "--for=condition=Ready",
            "pod/legal-files-transfer",
            "--timeout=180s",
        )
        restored = PRIVATE / "phase2-files-restored.json"
        if any(backup.iterdir()) and not restored.exists():
            run(kube_command("cp", str(backup) + "/.", "legal-files-transfer:/cache"))
        if not restored.exists():
            save(
                restored, {"cluster_id": owner()["cluster_id"], "backup_restored": True}
            )
    finally:
        kube("delete", "pod/legal-files-transfer", "--ignore-not-found", "--wait=false")
    apply(apps)
    for name in ("legal-backend", "legal-worker", "legal-scheduler", "legal-frontend"):
        kube("rollout", "status", "deployment/" + name, "--timeout=600s")
    apply(policies)
    save(
        PRIVATE / "phase2-local-deployment.json",
        {
            "cluster_id": owner()["cluster_id"],
            "image": args.image,
            "frontend_image": frontend_image,
            "gitops_published": False,
            "argo_auto_sync_suspended": True,
        },
    )
    print(
        "Local phase 2 applied. Publish/review GitOps before restoring Argo auto-sync."
    )


def resume_gitops(_):
    gitops = checkout("gitops")
    if run(["git", "-C", str(gitops), "status", "--porcelain"], capture=True).strip():
        raise ValueError("Review/commit/publish GitOps first; checkout is dirty")
    config = settings()
    local = run(["git", "-C", str(gitops), "rev-parse", "HEAD"], capture=True).strip()
    remote = run(
        [
            "git",
            "ls-remote",
            config["gitops_repository"],
            "refs/heads/" + config["gitops_revision"],
        ],
        capture=True,
    ).split()
    if not remote or remote[0] != local:
        raise ValueError("Published GitOps revision is not the reviewed local HEAD")
    release = load(gitops / "environments/local/apps/release.json")
    if not release.get("worker_enabled") or not release.get("phase2_enabled"):
        raise ValueError(
            "Publish the phase-2 release before resuming old Argo desired state"
        )
    for name, policy in load(PRIVATE / "phase2-argo-policies.json").items():
        if name == "legal-checker-backend":
            policy.setdefault("syncOptions", []).append("RespectIgnoreDifferences=true")
        patch = {
            "spec": {
                "syncPolicy": policy,
                "source": {
                    "repoURL": config["gitops_repository"],
                    "targetRevision": config["gitops_revision"],
                },
            },
            "metadata": {"annotations": {"argocd.argoproj.io/refresh": "hard"}},
        }
        if name == "legal-checker-backend":
            patch["spec"]["ignoreDifferences"] = [
                {
                    "group": "apps",
                    "kind": "Deployment",
                    "name": n,
                    "jsonPointers": ["/spec/replicas"],
                }
                for n in ("legal-backend", "legal-frontend")
            ]
        kube(
            "patch",
            "application",
            name,
            "--type=merge",
            "-p",
            json.dumps(patch),
            namespace="argocd",
        )
    print(
        "Published GitOps verified; previous policies restored for the two Legal apps"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    children = parser.add_subparsers(dest="command", required=True)
    children.add_parser("install").set_defaults(function=install)
    children.add_parser("seed-secrets").set_defaults(function=lambda _: seed_secrets())
    children.add_parser("resume-gitops").set_defaults(function=resume_gitops)
    child = children.add_parser("build-frontend")
    child.add_argument("--allow-dirty", action="store_true")
    child.set_defaults(function=build_frontend)
    child = children.add_parser("apply-local")
    child.add_argument("--image", required=True)
    child.add_argument("--frontend-image")
    child.set_defaults(function=apply_local)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
