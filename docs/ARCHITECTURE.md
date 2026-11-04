# Kiến trúc và ownership local

```text
Application: một package backend
  ├── FastAPI: nhận request, enqueue và đọc DB/report
  ├── Celery worker: chạy cùng business modules từ cùng image
  └── Beat: một scheduler riêng cho recovery
            API → Redis có xác thực → Worker → PostgreSQL
            API/worker → shared upload/cache/export PVC

Infrastructure
  ├── k3d, private kubeconfig, namespaces, bootstrap credentials
  ├── Argo CD + project/applications
  ├── LocalStack + ESO/ClusterSecretStore
  └── Traefik + Prometheus/Grafana + Loki/Alloy (Helm pins/checksums)

GitOps
  ├── platform: PostgreSQL, Redis, ExternalSecrets, NetworkPolicies
  └── apps: shared PVC, backend, frontend, worker, Beat, HPA/PDB, ingress/ServiceMonitor
```

Không tạo Deployment cho từng business module. API/worker là hai tiến trình của modular monolith; chia sẻ contracts, modules, Alembic, DB và image. PostgreSQL là nguồn trạng thái/kết quả; Redis là broker, không thay DB.

Infrastructure không sao chép SQL hoặc định nghĩa kết quả pháp lý. Nó gọi operations của app, rồi bàn giao receipts. LocalStack dùng lại credentials có sẵn, ESO Merge giữ lifecycle Secret bootstrap. Không có KMS/IRSA hoặc AWS service thật trong local target.

Mọi kubectl/Helm dùng `.local/kubeconfig`, context `k3d-legal-checker-local`. Không đổi current-context toàn máy hoặc sửa MaintAI. API Kubernetes chỉ bind loopback6561; edge/Grafana mở qua loopback forwards cho cluster hiện có.

Argo Application đang follow branch thật đã publish. Source local chưa commit không thể xuất hiện trên Argo chỉ nhờ chỉnh file: `phase2 apply-local` lưu/tạm dừng auto-sync của đúng hai Legal applications rồi apply overlay local. Sau publish/review dùng `resume-gitops`; không gọi apply-local là Argo Synced revision mới.

One-node k3d + RWO shared PVC cho phép API replicas và worker cùng đọc file trên một node. Nhiều node cần storage khác. HPA/PDB không bảo vệ việc node duy nhất dừng, Redis local không bảo đảm exactly-once. Giữ run idempotency/lease và kiểm recovery; không suy luận SLA hoặc chất lượng pháp lý từ Pod Ready.

Nguồn chính thức:

- [Celery Beat: một scheduler](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).
- [ESO AWS Secrets Manager](https://external-secrets.io/latest/provider/aws-secrets-manager/).
- [Traefik Kubernetes Ingress](https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-ingress/).
- [Alloy Kubernetes log source](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/).
- [Promtail EOL](https://grafana.com/docs/loki/latest/send-data/promtail/).

[Xem runbook](PHASE2_LOCAL.md) và [kết quả kiểm chứng](PHASE2_VALIDATION.md).
