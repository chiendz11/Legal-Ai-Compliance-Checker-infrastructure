# Giai đoạn 2 trên cluster Legal Checker local

Scope: namespace của Legal Checker trên `k3d-legal-checker-local`; không tác động MaintAI hoặc DB native/Compose. API và worker dùng chung image, không tạo Dockerfile mới. Đây là modular monolith với hai loại tiến trình.

## Lệnh triển khai

```bash
cd /home/chienqt/Dev/newBTL/Legal-Ai-Compliance-Checker-infrastructure
.venv/bin/python -m legal_infra.phase2 install
.venv/bin/python -m legal_infra build-image --allow-dirty
.venv/bin/python -m legal_infra import-image
IMAGE=$(.venv/bin/python -c 'import json; print(json.load(open(".local/backend-image.json"))["image"])')
.venv/bin/python -m legal_infra.phase2 apply-local --image "$IMAGE"
```

`install` cài LocalStack, ESO, Traefik, Prometheus/Grafana, Loki và Alloy. Helm archives được kiểm SHA-256 theo `versions/phase2.lock.json`. Không chạy Terraform production. Secret payload chỉ truyền trong bộ nhớ/stdin; không in/copy vào repo. LLM key hiện có được giữ lại, không tạo key mới hoặc thực hiện cuộc gọi tính phí.

`apply-local` kiểm ownership/import receipt, backup cache ngoài Git, tạo shared PVC, bật Redis+worker+Beat, apply manifests và kiểm rollout trước khi khóa NetworkPolicy. Argo auto-sync của hai Legal apps được tạm dừng để commit cũ trên GitHub không ghi đè source đang thử. Policy cũ được lưu `.local/phase2-argo-policies.json`. Không dừng Argo, không sửa ứng dụng MaintAI.

## Truy cập và quan sát

```bash
export KUBECONFIG="$PWD/.local/kubeconfig"
kubectl --context k3d-legal-checker-local -n legal-edge port-forward --address=127.0.0.1 svc/legal-edge-traefik 18880:80
# Terminal khác:
curl -H 'Host: api.legal-checker.localhost' http://127.0.0.1:18880/health
curl -H 'Host: app.legal-checker.localhost' http://127.0.0.1:18880/

kubectl --context k3d-legal-checker-local -n legal-observability port-forward --address=127.0.0.1 svc/legal-monitoring-grafana 18300:80
kubectl --context k3d-legal-checker-local -n legal-checker get pods,hpa,pdb,externalsecrets,networkpolicies,pvc
kubectl --context k3d-legal-checker-local -n legal-checker logs deployment/legal-worker --tail=50
```

Grafana admin password nằm ngoài Git tại `.local/grafana.json`. Không paste password vào chat/log. Dashboard HTTP dùng `sum(rate(legal_http_requests_total[5m]))`. LLM counters là tổng audit DB được scrape từ mỗi API pod: dùng `max by (provider,status) (legal_llm_calls_total)`, không sum trùng các replicas. Loki query `{namespace="legal-checker"}` rồi lọc theo run ID trong log; run ID không phải label chỉ mục.

Worker: `celery worker --concurrency=1`, Beat đúng một replica/Recreate. PVC RWO được chia sẻ giữa các pods cùng node k3d; cloud nhiều node cần object storage/RWX hoặc adapter tương ứng. PDB/HPA không tạo HA cho cluster một node.

## Bàn giao lại cho Argo

Review thay đổi trong cả ba repo; publish app image và cập nhật **cùng image backend cho API, worker, Beat** trong GitOps. Kiểm diff không có `.local`, credentials hoặc dataset. Sau khi branch GitOps đã publish đúng HEAD:

```bash
.venv/bin/python -m legal_infra.phase2 resume-gitops
```

Lệnh từ chối nếu checkout chưa sạch hoặc remote revision chưa bằng local HEAD. Nó khôi phục các sync policies đã lưu và yêu cầu reconcile; không tự push hoặc bypass ruleset. Không xóa cluster để bật ingress; cluster hiện có dùng edge port-forward hoặc NodePort qua Docker node IP.

## Khôi phục

Giữ PostgreSQL/PVC và shared files. Không `terraform destroy` hoặc xóa `.local` để xử lý lỗi. Dừng intake trước khi đổi queue; đợi run đang chạy hoàn tất, đổi ASSESSMENT_QUEUE rồi rollout API/worker có chủ đích. Không tắt Redis khi còn QUEUED/RUNNING jobs. Khi revert source chưa publish, dùng backup/policies private và đảm bảo không ghi đè upload mới trong shared PVC bằng bản cache cũ.

Knowledge/source chưa xác minh vẫn UNKNOWN; quote/offset đúng không chứng minh kết luận pháp lý. Argo Synced/Pod Ready/metrics hoạt động không thay thế E2E pháp lý.

## Nếu đã sửa frontend

Dùng Dockerfile frontend đang có, đúng build context `frontend/`:

```bash
.venv/bin/python -m legal_infra.phase2 build-frontend --allow-dirty
FRONTEND_IMAGE=$(.venv/bin/python -c 'import json; print(json.load(open(".local/frontend-image.json"))["image"])')
.venv/bin/python -m legal_infra.phase2 apply-local --image "$IMAGE" --frontend-image "$FRONTEND_IMAGE"
```

Các lệnh forward tiện dụng: `python -m legal_infra forward edge`, `forward grafana`, `forward prometheus`. Để chạy kiểm thử upload → queue → worker → report không gọi LLM, dùng Python của app dev: `../Legal-Ai-Compliance-Checker/.venv/bin/python checks/phase2_smoke.py`. Checker chờ các worker cũ dừng trước khi enqueue, kiểm số audit của riêng ca smoke bằng 0 và khôi phục env worker. Nó tạo một ca PDF hạ tầng có nhãn rõ, không sửa các ca seed.
