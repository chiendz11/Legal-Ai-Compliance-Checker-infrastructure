# Legal AI Compliance Checker — Infrastructure as Code (IaC)

Hạ tầng được quản lý bằng **Terraform (IaC)** tương tự môi trường Production của MaintAI, hỗ trợ 2 môi trường:
* **`terraform/local/`**: Cụm Kubernetes k3d local, Argo CD GitOps, tự động kéo image từ GHCR và đồng bộ với GitOps repo.
* **`terraform/production/`**: Kiến trúc Production Cloud trên AWS (VPC, EKS Cluster, RDS PostgreSQL 17, S3 Documents, IAM/KMS).

👉 **[Xem Hướng dẫn Bật Demo Nhanh bằng Terraform & GitOps tại đây](docs/DEMO_GUIDE.md)**

---

## Hai folder phối hợp ra sao?

| Nơi sở hữu | Công việc |
|---|---|
| Folder này | Cluster `legal-checker-local`, kubeconfig riêng, namespaces, secrets, bootstrap Argo CD, build/import image và gọi các owner operations |
| `../Legal-Ai-Compliance-Checker-gitops/` | Desired state PostgreSQL, Redis tùy chọn và backend; chuẩn bị release để review/commit/push |
| `../Legal-Ai-Compliance-Checker/` | FastAPI, Alembic/SQL, đọc và seed workbook, knowledge reader và nghiệp vụ |

Không chuyển từng business module thành một Deployment. Hiện chỉ có backend đọc knowledge/run chạy được; worker/frontend chưa có build/entrypoint trong checkout được đối chiếu. PDF tiếp tục dùng HTTP(S) sources đã có. Không mang Kafka/MLflow/Keycloak/AWS của MaintAI sang ứng dụng này.

```text
config/             k3d template và settings mẫu không có secrets
contracts/          local platform contract, giống byte-for-byte ở GitOps
versions/           tool/image/Argo pins và reference commits
legal_infra/        CLI operator, không tự chạy lúc import
.local/             settings, secrets, kubeconfig, storage và receipts; ngoài Git
```

## 1. Chuẩn bị

Cần Linux/macOS, Docker Engine, Python >=3.11, k3d **5.9.0**, kubectl tương thích Kubernetes **1.35**. Pins lấy từ reference local; PostgreSQL giữ bản **17.10** tương ứng app. Dự trù khoảng 4 CPU/8 GB RAM và đủ đĩa cho k3s/Argo/DB; đây là gợi ý, chưa có benchmark.

Từ root folder infrastructure:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m legal_infra init
```

`init` chỉ tạo `.local/`, passwords ngẫu nhiên và config riêng. Chạy lại giữ credentials. Không ghi vào `~/.kube/config`, không đổi current-context, không tạo cluster.

Sửa `.local/settings.json` khi cần đổi đường dẫn checkout. `gitops_repository` ban đầu là `null`: chỉ điền URL HTTPS `.git` **thật, đã publish** khi bạn tạo repo GitOps. Bootstrap Argo và cluster có thể chuẩn bị trước; Argo không đọc một folder local qua đường dẫn trên laptop.

## 2. Tạo cluster riêng và Argo CD

Những lệnh sau là **runbook cho lần thực thi sau**, chưa được chạy:

```bash
.venv/bin/python -m legal_infra up
.venv/bin/python -m legal_infra install-argocd
```

`up` chỉ tạo cluster/kubeconfig; không apply PostgreSQL hay backend. Một server k3s, không agent; Traefik/ServiceLB mặc định bị tắt. Kubernetes API chỉ bind `127.0.0.1:6561`. Nếu tên cluster đã tồn tại mà không có marker hợp lệ của bootstrap này, lệnh từ chối nhận quản lý.

`install-argocd` tạo namespaces/secrets rồi cài Argo từ installer có checksum, thay upstream images bằng các digest đã khóa. Chưa attach/sync Application. Password local nằm trong `.local/credentials.json`; tránh đưa nội dung file vào log/Git. Secret đưa qua stdin của kubectl, không đặt trong argv.

Mở Argo qua một terminal riêng:

```bash
.venv/bin/python -m legal_infra forward argocd
```

Truy cập `https://127.0.0.1:19443`. Argo sử dụng chứng chỉ nội bộ mặc định; cấu hình trust phù hợp nếu cần. Admin password là Secret `argocd-initial-admin-secret` trong namespace `argocd`; dùng kubeconfig riêng khi đọc Secret. CLI không tắt TLS hoặc auth để giả lập đăng nhập.

## 3. Publish GitOps và attach Applications

Folder GitOps chưa phải repo GitHub. Sau khi bạn khởi tạo/publish folder đó, điền `gitops_repository` và tên branch `gitops_revision` trong private settings, rồi:

```bash
.venv/bin/python -m legal_infra attach-gitops
```

Lệnh kiểm tra GitOps sạch và branch remote trùng HEAD đã review. AppProject chỉ cho repo đã chọn, namespace `legal-checker`; không cho child Applications quản lý Secrets/cluster resources. Hai Applications:

- `legal-checker-platform` → `environments/local/platform`: mặc định chỉ PostgreSQL.
- `legal-checker-backend` → `environments/local/apps`: ban đầu không có backend workload.

Cả hai dùng **manual sync**, không auto-prune. Sync platform trong Argo UI trước và chờ PostgreSQL sẵn sàng. Không apply lại PostgreSQL từ infrastructure, để tránh hai nơi cùng quản lý workload.

## 4. Build/import image đúng source app

```bash
.venv/bin/python -m legal_infra build-image
.venv/bin/python -m legal_infra import-image
```

Mặc định build từ chối checkout app đang dirty. Muốn thử source local chưa commit, dùng rõ `build-image --allow-dirty`; receipt lưu `dirty=true`, source SHA và hash toàn bộ source không bị Git ignore. Đây là provenance local, không phải production attestation.

Image tạo từ `backend/Dockerfile` do app sở hữu. CLI lấy Docker image ID thật, gắn alias `legal-local/backend:image-<ID>`, rồi import đúng cluster. Không bịa OCI registry digest hoặc dùng tag `latest`. Base image của Dockerfile app vẫn do app quản lý; receipt khóa image build thực tế, không tự sửa Dockerfile.

## 5. Migration và seed DEV/VALIDATION

Sau khi PostgreSQL đã sync/Ready:

```bash
.venv/bin/python -m legal_infra migrate
```

Đây là Job một lần, ngoài roots Argo. Nó dùng image đã import và gọi đúng `python -m alembic -c backend/alembic.ini upgrade head`. Không tự copy SQL sang infrastructure; không tự downgrade/drop bảng. Job giữ logs tạm, có TTL một ngày.

Tạo app `.venv` và cài `backend[dev]` theo docs app trước khi seed. Tải dataset bằng script app, rồi chỉ rõ workbook:

```bash
.venv/bin/python -m legal_infra seed --workbook ../Legal-Ai-Compliance-Checker/data/private/v750_source_pdf360_r2_supabase/bang_du_lieu_runtime_v7_5_0_360_STRUCTURED_R2_SUPABASE_DEV_VALIDATION.xlsx
```

Seed chạy bằng `.venv` của app qua một port-forward loopback tạm tới **DB trong cluster mới**; không ghi DB native/Compose hiện có. Nó kiểm tra filename/SHA từ manifest DEV_VALIDATION, gọi importer app, capture/kiểm knowledge hash rồi lưu `.local/seed.json`. Giữ 240 DEV + 60 VALIDATION và QA tham chiếu; không nhận MASTER/TEST answers. Không tải/copy workbook vào GitOps/image. Nếu bạn sửa knowledge thì cần quy trình dataset/pin mới; không tự bỏ kiểm tra hash.

Không giữ port-forward PostgreSQL thủ công cùng cổng khi chạy seed. Lệnh tự mở/đóng forward riêng. Seed không tự bật backend.

## 6. Chuẩn bị desired state backend

```bash
.venv/bin/python -m legal_infra prepare backend
```

CLI chuyển receipts sang generator trong GitOps. Image và seed phải cùng image ID/cluster instance; knowledge hash và workbook hash phải có. Chỉ sửa files GitOps, không tự commit/push hoặc sync.

Review GitOps diff, publish branch rồi sync `legal-checker-backend`. Backend được pin snapshot đã seed, chạy một replica, imagePullPolicy Never và không public Ingress. Mở:

```bash
.venv/bin/python -m legal_infra forward backend
```

Swagger: `http://127.0.0.1:18100/docs`. App hiện chỉ có health, GET knowledge và GET stored run; chưa có pipeline 1–9/worker/auth/report API đầy đủ. Probe knowledge kiểm snapshot đã nạp; chưa phải bằng chứng DB tiếp tục khỏe hoặc nghiệp vụ E2E pass.

## 7. Redis tùy chọn và quan sát

Redis chưa cần cho GET backend hiện có. Khi triển khai queue/worker thật:

```bash
.venv/bin/python -m legal_infra prepare platform --redis
```

Review/publish GitOps và sync platform. Redis có password Secret riêng, AOF/PVC; bật nó không tự tạo Celery queue/worker. Không tự thêm `REDIS_URL` vào Settings app chưa hỗ trợ. Omission `--redis` không tự xóa Redis đã bật.

```bash
.venv/bin/python -m legal_infra status
.venv/bin/python -m legal_infra forward postgres
```

| Mục đích | Host port |
|---|---|
| Kubernetes API | `127.0.0.1:6561` |
| Backend | `127.0.0.1:18100` |
| PostgreSQL forward | `127.0.0.1:15440` |
| Redis forward | `127.0.0.1:16380` |
| Argo CD forward | `127.0.0.1:19443` |

Các cổng được chọn khác mặc định MaintAI và DB app local. Nếu cổng đang bị dùng, giải quyết xung đột thay vì đổi current-context hoặc trỏ sang cluster khác.

## Giới hạn hiện tại

- Source mới được viết, chưa chạy dependency install, tests, Kustomize render, image build, cluster hoặc deploy cho Legal Checker.
- Các folder không có `.git` hoặc remote được tự tạo. Có GitOps thật sau khi bạn publish desired state và attach/sync Argo.
- Một node, local-path storage và local DB user dùng cho development; chưa có HA, production grants/TLS/backup automation hoặc auth app.
- PVC nằm trên node/host storage trong `.local/storage`; không tự backup/khôi phục khi tạo lại cluster. Backup DB trước khi thay cluster/PVC; không xóa `.local/` để reset khi còn dữ liệu cần giữ.
- `.local/credentials.json` là nguồn credentials ổn định. Thay file này không tự đổi password trong DB đã khởi tạo; rotation cần thao tác có chủ đích.

Xem [ownership/kiến trúc](docs/ARCHITECTURE.md), [khôi phục và chuyển tiếp](docs/OPERATIONS.md) và [GitOps](../Legal-Ai-Compliance-Checker-gitops/README.md).
