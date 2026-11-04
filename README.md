# Legal Checker — Infrastructure

Quản lý cluster **k3d `legal-checker-local`**, kubeconfig riêng, bootstrap Argo và các controller phục vụ phát triển local. App và worker dùng chung backend image. PostgreSQL, Redis, Deployments và policies nằm ở repo GitOps kế bên.

## Bắt đầu

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m legal_infra init
.venv/bin/python -m legal_infra up
.venv/bin/python -m legal_infra install-argocd
```

Nếu cluster đã tồn tại và đang dừng, dùng `k3d cluster start legal-checker-local --wait`; không xóa/recreate DB/PVC. Terraform local là wrapper cho bootstrap; Terraform production là mã cấu hình riêng, không được chạy khi triển khai local.

## Giai đoạn 2

[Xem lệnh triển khai, kiểm tra và khôi phục](docs/PHASE2_LOCAL.md).

```bash
.venv/bin/python -m legal_infra.phase2 install
.venv/bin/python -m legal_infra build-image --allow-dirty
.venv/bin/python -m legal_infra import-image
IMAGE=$(.venv/bin/python -c 'import json; print(json.load(open(".local/backend-image.json"))["image"])')
.venv/bin/python -m legal_infra.phase2 apply-local --image "$IMAGE"
```

- LocalStack + ESO: tiếp quản Secret database/Redis/LLM, giữ password DB hiện có.
- Traefik: class `legal-local`, frontend/API qua một edge endpoint.
- Prometheus/Grafana + Loki/Alloy: metrics và logs; chart version/checksum tại `versions/phase2.lock.json`.
- `apply-local`: triển khai source chưa publish; tạm dừng auto-sync đúng hai Legal apps, backup cache và chuyển API/worker sang shared PVC. Không commit/push, không gọi LLM để kiểm hạ tầng.
- `resume-gitops`: chỉ khôi phục policy Argo khi GitOps đã publish đúng local HEAD và phase-2 release. Không tự push hoặc bypass ruleset.

## Dữ liệu và bí mật

`.local/` ngoài Git chứa kubeconfig, credentials, storage, logs và receipts. Giữ `contracts/local-platform.json` giống byte-for-byte với GitOps. Không commit workbook, PDF, `.env`, Terraform state hoặc Secret payload.

Migration thuộc app (`python -m legal_infra migrate`). Seed thuộc app importer (`python -m legal_infra seed --workbook ...`), chỉ dùng DEV_VALIDATION. **Bật worker không yêu cầu seed lại DB**. Một node/PVC local không chứng minh AWS HA hay backup.

[Kiến trúc](docs/ARCHITECTURE.md) · [Runbook giai đoạn 2](docs/PHASE2_LOCAL.md) · [Báo cáo kiểm chứng](docs/PHASE2_VALIDATION.md)
