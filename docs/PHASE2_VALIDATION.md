# Kiểm chứng giai đoạn 2 — 04/11/2026

Source trên nhánh `feat/local-phase2-worker-verification` ở app/infrastructure/GitOps; chưa commit/push. Đã triển khai **local trên k3d-legal-checker-local**, không triển khai AWS, không chạy GitHub CI/CD. Image build/import local, không push image registry.

| Kiểm tra | Kết quả |
|---|---|
| Backend unit tests | 1.200 pass, 2 skip |
| Các integration tests PostgreSQL (run/review/document intelligence) và contract tests | 76 pass; DB test riêng được tạo/xóa, không reset DB seed |
| GitOps release receiver tests | 4 pass |
| Ruff cho code app thay đổi và helpers mới | Pass |
| Kustomize hai roots | Render thành công, sau đó apply thật |
| API + frontend | 2 replicas mỗi loại, Ready |
| Worker + Beat | 1 replica mỗi loại, Ready; cùng image với API |
| PostgreSQL + Redis | Ready; Redis yêu cầu xác thực |
| ESO | 3 ExternalSecrets Ready/SecretSynced |
| HPA/PDB | CPU metrics có số liệu, target 70%, 2–4 replicas; minAvailable1 |
| NetworkPolicy | Worker kết nối DB được; pod probe không thuộc allowlist bị chặn |
| Ingress | API health và frontend HTTP200 qua Traefik |
| Prometheus | Cả hai API targets UP |
| Grafana/Loki/Alloy | Grafana health OK, Loki datasource OK, query được worker logs |
| Workflow PDF→queue→worker→DB→report | COMPLETED; report DRAFT, export JSON200 |
| Reload và idempotency | Client mới đọc lại COMPLETED; cùng key trả cùng run |
| Gọi LLM trong ca smoke | 0 audit calls; không kiểm E2E Gemini/OpenAI có tính phí |

Smoke dùng PDF hạ tầng synthetic có nhãn `LOCAL_PHASE2_OFFLINE_SMOKE.pdf`, được parse bởi Document Intelligence thật (`module_source=MODULES`) và đọc qua shared PVC. Nó kiểm orchestration/storage, không chứng minh chất lượng suy luận trên 360 PDF hoặc xác nhận kết luận pháp lý. Hai ca thử được tạo trong lúc kiểm tra, không sửa các ca seed. Source, DB và providers có thể thay đổi sau thời điểm kiểm chứng.

Receipt chi tiết (image IDs/source hashes/run IDs/check results) nằm ngoài Git ở `.local/phase2-validation.json`; log install/build/import và smoke cũng nằm `.local/`. Không đưa Secret, DSN, API key hoặc nội dung hợp đồng vào báo cáo này.

## Truy cập

- UI: `http://app.legal-checker.localhost:18880`.
- API Swagger: `http://api.legal-checker.localhost:18880/docs`.
- Grafana: `http://127.0.0.1:18300`; admin credentials tại private `.local/grafana.json`.

Các URL phụ thuộc port-forward đang chạy. Khởi động lại bằng `python -m legal_infra forward edge` / `forward grafana`. Không thêm port mappings bằng cách xóa cluster đang có dữ liệu.

## GitOps và những việc chưa chạy

Auto-sync của **đúng hai Legal Applications** đang tạm dừng để GitHub main cũ không ghi đè source local. Cluster đang chạy với image overrides local đã build/import; không gọi đây là Argo Synced commit mới. Sau review/publish app images và GitOps mới dùng `phase2 resume-gitops`.

Không thay workbook/seed schema, không seed lại DB, không đặt hàng loạt knowledge thành VERIFIED. Backend review tự động chỉ áp dụng draft có đủ điều kiện; pending source, facts/ngoại lệ chưa kiểm tra vẫn UNKNOWN. Chưa có kết quả provider E2E, benchmark load, HA hoặc AWS deployment trong đợt này.
