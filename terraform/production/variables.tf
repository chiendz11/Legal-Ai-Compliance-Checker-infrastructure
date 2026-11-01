variable "aws_region" {
  type        = string
  default     = "ap-southeast-1"
  description = "AWS region for deployment"
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Deployment environment name"
}

variable "project_name" {
  type        = string
  default     = "legal-checker"
  description = "Base project name for resources"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.10.0.0/16"
  description = "VPC CIDR block"
}

variable "kubernetes_version" {
  type        = string
  default     = "1.31"
  description = "Kubernetes version for Amazon EKS"
}

variable "eks_node_instance_types" {
  type        = list(string)
  default     = ["t3.xlarge"]
  description = "EC2 instance types for EKS managed node group"
}

variable "postgres_engine_version" {
  type        = string
  default     = "17.2"
  description = "PostgreSQL engine version for Amazon RDS"
}

variable "db_instance_class" {
  type        = string
  default     = "db.t4g.medium"
  description = "RDS DB instance class"
}

variable "gitops_repo_url" {
  type        = string
  default     = "https://github.com/chiendz11/Legal-Ai-Compliance-Checker-gitops.git"
  description = "URL of the GitOps repository for Argo CD sync"
}

