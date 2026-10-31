# Legal Checker local platform

Giải thích thay đổi bằng tiếng Việt, chi tiết và dễ hiểu.
Đọc README.md, docs/ARCHITECTURE.md và contracts/local-platform.json trước khi sửa.
Infrastructure sở hữu k3d, kubeconfig riêng, namespaces, secrets và Argo bootstrap.
GitOps sở hữu desired state PostgreSQL, Redis tùy chọn và backend. App sở hữu SQL/Alembic, seed và nghiệp vụ.
Mặc định code-first: không tự chạy tests/build/render, Docker/k3d/kubectl/Argo hoặc deploy khi người dùng chỉ yêu cầu viết code. Yêu cầu thực thi về sau của người dùng được ưu tiên.
Không tự tạo remote, commit/push, đổi ~/.kube/config hoặc sửa MaintAI và các repo tham khảo.
Không commit secrets, kubeconfig, dữ liệu PDF/workbook, DB hoặc private .local/. Backend mặc định tắt; worker/frontend chưa có runtime trong checkout app hiện tại.
Không coi slides tiến độ giả định là bằng chứng implementation. Không gọi nguồn này đã deploy/pass trước khi có kiểm chứng thật.
