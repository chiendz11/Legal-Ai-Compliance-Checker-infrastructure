"""Explicit local synthetic orchestration check. Run with the app's dev/export venv.

Requires running edge on 127.0.0.1:18880. Creates one labelled test contract/case/run;
never changes seeded cases. Temporarily uses offline worker, drains old consumers,
verifies no provider audit calls, and restores the exact original worker env.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from fpdf import FPDF

infra = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(infra))
from legal_infra.common import owner

owner()
base = [
    "kubectl",
    "--kubeconfig",
    str(infra / ".local/kubeconfig"),
    "--context",
    "k3d-legal-checker-local",
    "-n",
    "legal-checker",
]


def k(*args, capture=False):
    return subprocess.run(
        base + list(args), check=True, text=True, capture_output=capture
    ).stdout


current = json.loads(k("get", "deployment", "legal-worker", "-o", "json", capture=True))
env = current["spec"]["template"]["spec"]["containers"][0]["env"]
old_pods = json.loads(
    k("get", "pods", "-l", "app=legal-worker", "-o", "json", capture=True)
)["items"]
private = infra / ".local/phase2-worker-before-smoke.json"
private.write_text(json.dumps(env))
private.chmod(0o600)
patch = lambda values: k(
    "patch",
    "deployment",
    "legal-worker",
    "--type=json",
    "-p",
    json.dumps(
        [
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/env",
                "value": values,
            }
        ]
    ),
)
summary = {}
try:
    patch(
        [row for row in env if row["name"] != "ASSESSMENT_LLM"]
        + [{"name": "ASSESSMENT_LLM", "value": "offline"}]
    )
    k("rollout", "status", "deployment/legal-worker", "--timeout=300s")
    # Deployment Ready can coexist with terminating old workers. Drain every old
    # consumer before enqueueing, so a worker with live LLM settings cannot take this job.
    for old in old_pods:
        for _ in range(360):
            found = k(
                "get",
                "pod",
                old["metadata"]["name"],
                "--ignore-not-found",
                "-o",
                "name",
                capture=True,
            )
            if not found.strip():
                break
            time.sleep(1)
        else:
            raise TimeoutError("Old worker did not drain; no smoke job was enqueued")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in [
        "LOCAL PHASE 2 - SYNTHETIC INFRASTRUCTURE SMOKE",
        "This is a test document. No actual legal transaction.",
        "Seller: TEST SELLER. Buyer: TEST BUYER.",
        "No signing date is asserted. No legal compliance is asserted.",
    ]:
        pdf.multi_cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
    content = bytes(pdf.output())
    headers = {"Host": "app.legal-checker.localhost"}
    with httpx.Client(
        base_url="http://127.0.0.1:18880", headers=headers, timeout=30
    ) as c:

        def req(method, url, **kwargs):
            response = c.request(method, url, **kwargs)
            if response.status_code not in (200, 201, 202):
                raise RuntimeError(f"{method} {url}: HTTP {response.status_code}")
            return response

        contract = req(
            "POST",
            "/api/v1/contracts",
            files={
                "file": ("LOCAL_PHASE2_OFFLINE_SMOKE.pdf", content, "application/pdf")
            },
        ).json()
        case = req(
            "POST",
            "/api/v1/cases",
            json={
                "hop_dong_id": contract["hop_dong_id"],
                "ngay_danh_gia": "2026-11-04",
            },
        ).json()["case"]
        ca_id = case["ca_id"]
        endpoint = f"/api/v1/cases/{ca_id}/runs"
        accepted = req(
            "POST", endpoint, headers={"Idempotency-Key": "LOCAL_PHASE2_OFFLINE_SMOKE"}
        ).json()
        repeated = req(
            "POST", endpoint, headers={"Idempotency-Key": "LOCAL_PHASE2_OFFLINE_SMOKE"}
        ).json()
        assert accepted["context"]["run_id"] == repeated["context"]["run_id"]
        for _ in range(240):
            status = req("GET", accepted["status_url"]).json()
            if status["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.5)
        summary.update(
            ca_id=ca_id,
            run_id=accepted["context"]["run_id"],
            status=status["status"],
            idempotency=True,
        )
        assert status["status"] == "COMPLETED", "Offline workflow did not complete"
        results = req("GET", accepted["results_url"]).json()
        reports = req("GET", endpoint + "/" + summary["run_id"] + "/reports").json()
        assert reports["total"] >= 1
        report = reports["items"][0]["report"]
        assert report["report_status"] == "DRAFT"
        report_id = report["bao_cao_id"]
        exported = req("GET", f"/api/v1/reports/{report_id}/export?format=json")
        assert len(exported.content) > 100
        summary.update(
            report_id=report_id,
            report_status=report["report_status"],
            report_export_http=exported.status_code,
            module_source=results.get(
                "module_source", accepted.get("module_source", "MODULES")
            ),
            pdf_uploaded_bytes=len(content),
        )
    # Verify this case did not call any provider; never infer it from a passed rollout.
    import re

    assert re.fullmatch(r"[A-Za-z0-9_]+", ca_id)
    count = k(
        "exec",
        "postgres-0",
        "--",
        "psql",
        "-U",
        "legal_checker",
        "-d",
        "legal_checker_dev",
        "-Atc",
        "SELECT count(*) FROM runtime.nhat_ky_goi_llm WHERE ca_id='" + ca_id + "'",
        capture=True,
    )
    assert int(count.strip()) == 0, "Smoke test must not create any provider calls"
    summary["llm_calls_for_smoke_case"] = 0
    # A new client (like re-opening/reloading a browser) still reads the persisted state.
    with httpx.Client(
        base_url="http://127.0.0.1:18880", headers=headers, timeout=30
    ) as reloaded:
        summary["new_client_reads_completed_run"] = (
            reloaded.get(accepted["status_url"]).json()["status"] == "COMPLETED"
        )
    assert summary["new_client_reads_completed_run"]
    target = infra / ".local/phase2-offline-smoke.json"
    target.write_text(json.dumps(summary, indent=2))
    target.chmod(0o600)
    print(json.dumps(summary, indent=2))
finally:
    patch(env)
    k("rollout", "status", "deployment/legal-worker", "--timeout=300s")
