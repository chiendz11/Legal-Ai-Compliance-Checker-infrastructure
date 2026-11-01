output "cluster_name" {
  value       = var.cluster_name
  description = "Name of the local k3d Kubernetes cluster"
}

output "kubeconfig" {
  value       = abspath("${path.module}/../../.local/kubeconfig")
  description = "Path to the private kubeconfig for the local cluster"
}

output "backend_api_url" {
  value       = "http://127.0.0.1:18100"
  description = "URL to access the Legal Backend API (forward with: .venv/bin/python -m legal_infra forward backend)"
}

output "argocd_ui_url" {
  value       = "https://127.0.0.1:19443"
  description = "URL to access Argo CD UI (forward with: .venv/bin/python -m legal_infra forward argocd)"
}

output "postgres_port" {
  value       = 15440
  description = "Local port for PostgreSQL (forward with: .venv/bin/python -m legal_infra forward postgres)"
}

