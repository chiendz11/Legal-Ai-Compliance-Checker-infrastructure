# Hướng dẫn Bật Demo Hệ thống (Terraform IaC & GitOps Argo CD)

Tài liệu này hướng dẫn chi tiết cách khởi động, kiểm tra và trình diễn (demo) hệ thống **Legal AI Compliance Checker** bằng công cụ **Terraform (Infrastructure as Code - IaC)** kết hợp với **Argo CD GitOps** trên cụm Kubernetes local **k3d** (theo kiến trúc tiêu chuẩn của MaintAI).

---

## 1. Kiến trúc luồng Demo

```text
[Developer / Laptop]
       │
       ▼ (1. Push code / Merge PR vào main)
[GitHub: Legal-Ai-Compliance-Checker (App Repo)]
       │
       ▼ (2. GitHub Actions CI/CD)
       ├── Tests (Unit & Contract tests)
       ├── Build Docker Image & Push lên GHCR
       │   └── ghcr.io/chiendz11/legal-ai-compliance-checker-backend:sha-<sha>
       └── Tự động commit cập nhật image tag vào GitOps Repo:
           └── environments/local/apps/kustomization.yaml
               │
               ▼
[GitHub: Legal-Ai-Compliance-Checker-gitops (GitOps Repo)]
       │
       ▼ (3. Argo CD tự động phát hiện commit mới)
[Laptop: Local k3d Cluster (Quản lý bằng Terraform)]
       ├── Argo CD tự động SYNC Deployment mới
       └── containerd kéo image mới từ GHCR về chạy
           ==> KHÔNG CẦN CHẠY BẤT KỲ LỆNH BUILD / DEPLOY NÀO Ở LOCAL!
```

---

## 2. Chuẩn bị môi trường (Prerequisites)

Trước khi bật demo, đảm bảo máy tính đã cài đặt:
* **Docker Engine**: Đang chạy (`sudo systemctl start docker`).
* **Terraform**: Phiên bản `>= 1.5.0` (`terraform -version`).
* **k3d**: Phiên bản `v5.9.0` (`k3d version`).
* **kubectl**: Đã cài đặt (`kubectl version --client`).
* **Quyền Image GHCR**: Package [legal-ai-compliance-checker-backend](https://github.com/chiendz11/Legal-Ai-Compliance-Checker/pkgs/container/legal-ai-compliance-checker-backend) liên kết với repo public nên đã tự động ở chế độ **Public**, cụm k3d có thể kéo image về trực tiếp mà không cần cấu hình ImagePullSecrets.

---

## 3. Khởi chạy Demo bằng Terraform (1-Click Startup)

Toàn bộ hạ tầng local (Cụm k3d, Secrets, Argo CD, kết nối GitOps, kích hoạt Auto-sync) được đóng gói trong Terraform module:

```bash
cd /home/chienqt/Dev/newBTL/Legal-Ai-Compliance-Checker-infrastructure/terraform/local

# 1. Khởi tạo Terraform provider plugins
terraform init

# 2. Khởi tạo toàn bộ hệ thống
terraform apply -auto-approve
```

Terraform sẽ tự động thực hiện tuần tự:
1. Tạo môi trường ảo Python và khởi tạo cấu hình bảo mật local (`init`).
2. Khởi tạo cụm Kubernetes `k3d-legal-checker-local` (`up`).
3. Tạo namespace `legal-checker` và Secret `legal-database` (`secrets`).
4. Cài đặt Argo CD vào namespace `argocd` (`install-argocd`).
5. Gắn kết Argo CD với GitOps repo trên GitHub và kích hoạt chế độ **Auto-sync** (`attach-gitops`).
6. Kích hoạt đồng bộ ứng dụng ban đầu (`argocd_sync`).

---

## 4. Kiểm tra trạng thái hệ thống

Sau khi `terraform apply` hoàn tất, bạn có thể kiểm tra:

### 4.1. Kiểm tra Pods trong cụm
```bash
# Đứng tại thư mục terraform/local:
KUBECONFIG=../../.local/kubeconfig kubectl get pods -n legal-checker
```
Bạn sẽ thấy:
* Pod PostgreSQL (`postgres-0`): Lưu trữ dữ liệu chuẩn hóa, snapshot và lineage.
* Pod Backend (`legal-backend-...`): Chạy image vừa kéo từ GHCR.

### 4.2. Truy cập Backend API
Mở một terminal mới để forward port backend:
```bash
cd /home/chienqt/Dev/newBTL/Legal-Ai-Compliance-Checker-infrastructure
.venv/bin/python -m legal_infra forward backend
```
Mở terminal khác để kiểm tra API:
```bash
# Kiểm tra Healthcheck
curl http://127.0.0.1:18100/health
# Kết quả mong đợi: {"status":"ok"}

# Kiểm tra Knowledge base
curl http://127.0.0.1:18100/api/v1/knowledge
```

### 4.3. Truy cập Giao diện Web (Frontend UI)
Giao diện người dùng được phục vụ bởi pod `legal-frontend` trên cổng 80:
```bash
# Forward port frontend ra máy chủ host:
kubectl port-forward svc/legal-frontend -n legal-checker 18080:80
```
Truy cập trình duyệt tại: **`http://localhost:18080`**

### 4.4. Cấu hình AI Provider (Groq / OpenAI) & Đánh giá Tuân thủ
Mặc định hệ thống chạy ở chế độ **`ASSESSMENT_LLM=offline`** (các tiêu chí C07 trả về `UNKNOWN`, yêu cầu pháp lý trả về `INSUFFICIENT`/`Chưa đủ căn cứ`).

Để kích hoạt AI đánh giá tuân thủ tự động (Live AI Assessment):
1. **Tạo Kubernetes Secret `legal-llm-secret`**:
   ```bash
   kubectl create secret generic legal-llm-secret -n legal-checker \
     --from-literal=GROQ_API_KEY="<your-groq-api-key>" \
     --from-literal=OPENAI_API_KEY="<your-openai-api-key>" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
2. **Cập nhật ConfigMap qua GitOps** (`environments/local/apps/kustomization.yaml`):
   - Với **Groq**:
     ```yaml
     - ASSESSMENT_LLM=groq
     - OPENAI_MODEL=openai/gpt-oss-20b
     ```
     > **Lưu ý hạn mức Groq Free Tier**: Groq miễn phí có quota giới hạn 8.000 TPM (tokens per minute) và 30 RPM. Đánh giá hợp đồng pháp lý Việt Nam kèm toàn bộ căn cứ điều khoản tiêu tốn ~7.000 tokens/request. Khi demo luồng AI trực tiếp, khuyến nghị sử dụng OpenAI API key hoặc tài khoản Groq có hạn mức mở rộng.
   - Với **OpenAI**:
     ```yaml
     - ASSESSMENT_LLM=openai
     - OPENAI_MODEL=gpt-4o-mini
     ```

### 4.5. Truy cập Giao diện Argo CD UI
Mở port-forward cho Argo CD:
```bash
cd /home/chienqt/Dev/newBTL/Legal-Ai-Compliance-Checker-infrastructure
.venv/bin/python -m legal_infra forward argocd
```
* Mở trình duyệt tại: `https://127.0.0.1:19443` (bỏ qua cảnh báo SSL tự ký).
* **Tài khoản**: `admin`
* **Mật khẩu**: Xem trong file `.local/credentials.json`:
  ```bash
  cat /home/chienqt/Dev/newBTL/Legal-Ai-Compliance-Checker-infrastructure/.local/credentials.json
  ```
* Trên giao diện Argo CD, bạn sẽ thấy 2 Application:
  * `legal-checker-platform`: Quản lý PostgreSQL.
  * `legal-checker-backend`: Quản lý Deployment backend FastAPI.

---

## 5. Kịch bản Showcase tự động hóa GitOps (Khi Thuyết trình / Demo)

1. Mở sẵn 3 màn hình:
   * **Màn hình 1**: Giao diện Argo CD UI (`https://127.0.0.1:19443`).
   * **Màn hình 2**: Tab GitHub Actions của repo [Legal-Ai-Compliance-Checker](https://github.com/chiendz11/Legal-Ai-Compliance-Checker/actions).
   * **Màn hình 3**: Terminal đang quan sát pods (`kubectl get pods -n legal-checker -w`).
2. Sửa một thay đổi nhỏ trong code backend (hoặc tạo commit test) và push/merge vào `main`.
3. Giải thích luồng cho người xem:
   * GitHub Actions kích hoạt `publish-and-deploy.yml`: Chạy test, build Docker image, tag SHA mới và push lên GHCR.
   * Bot `github-actions[bot]` tự động commit phiên bản image mới vào repo GitOps.
   * Argo CD trên laptop tự động nhận diện thay đổi &rarr; chuyển sang trạng thái `OutOfSync` &rarr; `Syncing`.
   * Cụm k3d kéo image mới từ GHCR về và khởi động lại pod mới với thời gian gián đoạn bằng 0 (Zero Downtime Rolling Update).

---

## 6. Dọn dẹp môi trường sau khi Demo (Teardown)

Khi buổi demo kết thúc, bạn có thể xóa sạch toàn bộ cụm k3d và tài nguyên local chỉ bằng 1 lệnh:

```bash
cd /home/chienqt/Dev/newBTL/Legal-Ai-Compliance-Checker-infrastructure/terraform/local
terraform destroy -auto-approve
```
Lệnh này sẽ tự động xóa sạch cluster k3d `legal-checker-local` mà không để lại tài nguyên rác trên máy.

