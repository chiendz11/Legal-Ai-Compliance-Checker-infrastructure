output "eks_cluster_name" {
  value       = aws_eks_cluster.this.name
  description = "Name of the EKS cluster"
}

output "eks_cluster_endpoint" {
  value       = aws_eks_cluster.this.endpoint
  description = "Endpoint for EKS control plane"
}

output "rds_postgres_endpoint" {
  value       = aws_db_instance.postgres.endpoint
  description = "RDS PostgreSQL connection endpoint"
}

output "s3_documents_bucket" {
  value       = aws_s3_bucket.documents.id
  description = "Name of the S3 bucket for legal documents and audit data"
}
