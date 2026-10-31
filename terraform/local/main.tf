# Local Demo Infrastructure for Legal AI Compliance Checker (k3d + Argo CD GitOps)

resource "null_resource" "init" {
  triggers = {
    revision = var.gitops_revision
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = <<-EOT
      test -d .venv || python3 -m venv .venv
      .venv/bin/python -m pip install -q -r requirements.txt
      .venv/bin/python -m legal_infra init
    EOT
  }
}

resource "null_resource" "k3d_cluster" {
  depends_on = [null_resource.init]

  triggers = {
    cluster_name = var.cluster_name
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = ".venv/bin/python -m legal_infra up"
  }

  provisioner "local-exec" {
    when        = destroy
    working_dir = "${path.module}/../.."
    command     = "k3d cluster delete legal-checker-local || true"
  }
}

resource "null_resource" "secrets" {
  depends_on = [null_resource.k3d_cluster]

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = ".venv/bin/python -m legal_infra secrets"
  }
}

resource "null_resource" "argocd" {
  depends_on = [null_resource.secrets]

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = ".venv/bin/python -m legal_infra install-argocd"
  }
}

resource "null_resource" "attach_gitops" {
  depends_on = [null_resource.argocd]

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = ".venv/bin/python -m legal_infra attach-gitops"
  }
}

resource "null_resource" "argocd_sync" {
  depends_on = [null_resource.attach_gitops]

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = <<-EOT
      export KUBECONFIG="$PWD/.local/kubeconfig"
      kubectl --context k3d-legal-checker-local -n argocd patch application legal-checker-platform \
        --type merge -p '{"operation":{"sync":{"prune":false}}}' || true
      kubectl --context k3d-legal-checker-local -n argocd patch application legal-checker-backend \
        --type merge -p '{"operation":{"sync":{"prune":false}}}' || true
    EOT
  }
}
