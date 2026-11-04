# Publication và triển khai qua Argo — 04/11/2026

Đã commit/push source lên nhánh `feat/local-phase2-worker-verification` ở cả ba repositories. Main chưa được merge hoặc bypass ruleset. Argo local hiện theo nhánh này; khi merge main phải cập nhật target revision có chủ đích.

- App PR: https://github.com/chiendz11/Legal-Ai-Compliance-Checker/pull/26
- GitOps PR: https://github.com/chiendz11/Legal-Ai-Compliance-Checker-gitops/pull/1
- Infrastructure PR: https://github.com/chiendz11/Legal-Ai-Compliance-Checker-infrastructure/pull/1
- App commit/image tag: `210e1973fb9de341b5f78096fab31a6dee060367` / `sha-210e1973fb9de341b5f78096fab31a6dee060367`.
- CI required pass: https://github.com/chiendz11/Legal-Ai-Compliance-Checker/actions/runs/41854252479
- Build/publish/promote pass: https://github.com/chiendz11/Legal-Ai-Compliance-Checker/actions/runs/41854758570

GitHub Actions đã publish backend/frontend lên GHCR và cập nhật image overrides của nhánh GitOps. API, Celery worker và Beat cùng chạy backend registry image mới; frontend chạy tag tương ứng. Các pod Ready, hai Argo Applications Synced/Healthy và auto-sync được khôi phục. PostgreSQL/PVC/seed được giữ nguyên, không chạy seed lại.

## Các điểm được sửa khi bàn giao

`resume-gitops` phải gắn đúng `spec.source.targetRevision` từ private settings, ngoài việc khôi phục sync policy. Nếu chỉ push feature branch nhưng Application vẫn theo main, Argo sẽ tiếp tục đọc manifest cũ.

Traefik NodePort ở k3d không có node ExternalIP. Cấu hình `publishedService` mặc định khiến Ingress không có status address và Argo chờ health ở wave 0, chưa triển khai worker/backend ở wave sau. Cấu hình local nay quảng bá hostname `app.legal-checker.localhost`; endpoint vẫn được truy cập qua edge port-forward18880, không tuyên bố đã tạo cloud LoadBalancer.

Ba ConfigMap generated cũ được giữ để phục vụ lịch sử/rollback, sau khi xác nhận không có pod hiện tại tham chiếu. `IgnoreExtraneous` chỉ dùng cho generated ConfigMap history, không bỏ so sánh image/Deployment hoặc bỏ health checks. Policy được ghi tại generatorOptions trong GitOps.

## Vì sao frontend vẫn có thể hiện 306?

Report UI đọc một report ID và snapshot đã lưu trong DB. Đổi image hoặc F5 không tính lại report cũ. Không ghi đè các kết quả/human reviews đã lưu để thay đổi con số.

Kiểm tra chỉ đọc trên C05/C07 của một run cũ cho thấy: 306 kết quả C08 cũ gồm 162 requirement NOT_APPLICABLE. C08 mới (bao gồm trường hợp scope UNKNOWN nhưng requirement chưa được ban hành tại ngày áp dụng) loại riêng 162, còn 144. Đã chạy phép tính này ngay trong pod registry image mới, không gọi LLM và không ghi lại report cũ.

144 còn lại vẫn INSUFFICIENT trên dữ liệu C07 cũ; có nguồn pháp lý chưa được duyệt, thiếu facts/evidence, quote không hợp lệ hoặc call limit. Không đặt các flags VERIFIED để đổi kết quả. Đây là kiểm tra hậu xử lý C08, không phải một lần chạy mới toàn bộ PDF/LLM.

Muốn thấy kết quả của code mới trong UI: có PDF gốc trên storage, chạy assessment mới rồi mở report ID của run mới. Với ca upload cũ được kiểm tra, bytes gốc hiện không nằm trong shared upload PVC hoặc thư mục upload/cache local hiện tại; cần tải lại đúng PDF nếu muốn chạy lại ca đó. Không dùng report snapshot để giả làm PDF gốc.

Receipt triển khai gồm image IDs, pod readiness và GitOps revisions nằm ngoài Git tại `.local/phase2-publication.json`. Không có API key, DSN hay nội dung hợp đồng trong tài liệu này.
