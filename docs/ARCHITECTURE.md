# Ownership và kiến trúc local

```text
Infrastructure CLI
  ├── k3d cluster + private kubeconfig + namespaces/secrets
  ├── pinned Argo CD installer
  └── AppProject + hai Applications (manual sync)
          └── GitOps repo đã publish
                ├── platform: PostgreSQL (+ Redis tùy chọn)
                └── apps: backend, mặc định tắt

Application repo
  ├── Dockerfile backend → build receipt → k3d import receipt
  ├── Alembic → owner migration Job một lần
  └── workbook DEV_VALIDATION → app importer → seed/knowledge receipt
                                              └── GitOps backend activation
```

Đây là thiết kế có code, chưa có bằng chứng thực thi. Source refs trong `versions/reference-lock.json` dùng để ghi nguồn tham khảo, không chứng minh working trees tương ứng sạch hoặc code đã chạy.

Không sao chép AWS stack, Kafka, MLflow, auth compatibility sidecars hoặc dữ liệu của MaintAI. Backend của Legal Checker là modular monolith; folder business module không tự trở thành service K8s. Redis là hạ tầng dự kiến, không thay implementation worker.

`contracts/local-platform.json` giống nhau ở hai folder: cluster/context, namespace, tên Secret/DB, ports và source paths. Infrastructure kiểm bản GitOps trước khi gọi generator/owner operation. Thay contract cần cập nhật cả hai nơi và review khả năng tương thích.

Infrastructure tạo namespaces và Secrets. Argo child apps bị chặn quản lý Secrets hoặc cluster resources, chỉ sync desired state trong `legal-checker`. Platform/application manifests chỉ thuộc GitOps. Migration/seed là lệnh explicit do app sở hữu; không chạy bằng Argo auto-sync.

Images platform/Argo dùng pins từ reference và PostgreSQL official registry. Image app local dùng alias theo Docker config ID, kèm source/cluster receipts. Đó không phải registry manifest digest hoặc signed production provenance. Không tự khai báo image đã được build/import khi chưa thực hiện thao tác tương ứng.

Argo theo branch thật đã publish và sync thủ công; thay desired state qua review Git diff/commit. Repo URL không có sẵn vì người dùng mới yêu cầu hai folder, chưa yêu cầu tạo remote. Private repository cần cấp repository credentials cho Argo ngoài Git.

Nguồn hướng dẫn chính thức đã đối chiếu khi viết source:

- [k3d kubeconfig](https://k3d.io/stable/usage/kubeconfig/): dùng file riêng và tắt cập nhật default/current context.
- [k3d config](https://k3d.io/stable/usage/configfile/): `v1alpha5`, API binding và volumes.
- [Argo sync policy](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/): việc attach Application và việc sync là hai bước riêng.
- [Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/): ConfigMap hash và image/replica overrides.
