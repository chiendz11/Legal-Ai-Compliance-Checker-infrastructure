variable "cluster_name" {
  type        = string
  default     = "legal-checker-local"
  description = "Name of the local k3d Kubernetes cluster"
}

variable "gitops_repository" {
  type        = string
  default     = "https://github.com/chiendz11/Legal-Ai-Compliance-Checker-gitops.git"
  description = "GitOps repository URL for Argo CD applications"
}

variable "gitops_revision" {
  type        = string
  default     = "main"
  description = "Git revision for Argo CD applications in Legal-Ai-Compliance-Checker-gitops"
}
