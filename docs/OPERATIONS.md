# Thao tác có chủ đích và khôi phục

Tài liệu là runbook chưa thực thi. Chỉ thao tác Legal Checker với `.local/kubeconfig` và context `k3d-legal-checker-local`; không dùng current-context toàn máy.

## Backend cần dừng

Trong folder GitOps:

```bash
.venv/bin/python -m legal_gitops.release disable-backend
```

Review/commit/push và sync Application. Generator đặt replicas=0, giữ các resources thay vì trông chờ prune. Chỉ thay source chưa làm pod đang chạy dừng ngay. Không ảnh hưởng PostgreSQL/PVC.

## Nâng image / rules / knowledge

- Đổi app code: build/import image mới, gọi migration nếu schema đổi, seed/kiểm snapshot và chuẩn bị backend release lại.
- Không seed workbook khác checksum lên DB đã seed. Muốn dataset mới, thiết kế cutover DB/pin rõ ràng; công cụ này không tự reset/truncate baseline.
- Không chỉnh ba migration SQL/Alembic baseline đã chia sẻ. Thêm revision tại repo app.
- Lưu release receipts và Git revision tương ứng. Quay về image cũ chỉ khi schema còn tương thích; baseline hiện không hỗ trợ downgrade phá dữ liệu.

## DB, PVC và credentials

PostgreSQL là DB local độc lập với native/Compose của app. Password init chỉ áp dụng khi data directory trống. Secret mới không tự rotate DB password. Sao lưu bằng công cụ PostgreSQL của operator trước khi đổi PVC/cluster; kiểm restore trên môi trường tách riêng.

Không có lệnh destroy/reset tự động trong CLI. Khi cần xóa cluster, kiểm tra tên `legal-checker-local`, backup DB, dừng workloads và giữ private credentials/storage/receipts cần khôi phục. Local-path không phải storage HA hoặc kho backup.

## Kiểm chứng về sau

1. Kiểm source/config và dependencies.
2. Tạo cluster, xác nhận kubeconfig/context và namespaces riêng.
3. Bootstrap Argo, publish/attach rồi sync platform; kiểm DB/PVC.
4. Build/import image; migrate; seed và đối chiếu hashes.
5. Chuẩn bị/publish/sync backend; kiểm pod, `/health`, `/api/v1/knowledge` và GET run nếu có run đã lưu.
6. Kiểm nghiệp vụ/OCR/retrieval/LLM/E2E sau khi module owners hoàn thiện. Seeded outputs không chứng minh implementation đã chạy.

Không coi Argo Synced, Pod Ready hoặc API health là bằng chứng pipeline pháp lý đầy đủ đã pass.
