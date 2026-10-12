"""End-to-end: auth -> upload -> plan -> execute -> approval -> report, with the LLM provider replaced by a
deterministic test double (everything else - Postgres, pgvector retrieval, pandas, sklearn, PDF - is real)."""
import time

import pytest

from app.services.llm import LLMClient, LLMError


def wait_for(client, auth, path, predicate, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(path, headers=auth)
        if r.status_code == 200 and predicate(r.json()):
            return r.json()
        time.sleep(0.4)
    raise AssertionError(f"timeout waiting on {path}: {r.text[:500]}")


PLAN = {"title": "Regional sales review", "rationale": "Analyze, compare to policy, chart.",
        "steps": [
            {"name": "Analyze sales", "tool": "analyze_data", "objective": "Find regional drops in revenue", "requires_approval": False},
            {"name": "Detect anomalies", "tool": "ml_analysis", "objective": "Run anomaly detection", "requires_approval": False},
            {"name": "Check policy", "tool": "rag_search", "objective": "What does policy say about regional revenue decline review", "requires_approval": False},
            {"name": "Chart revenue", "tool": "create_chart", "objective": "Line chart of revenue by region", "requires_approval": False},
            {"name": "Bogus", "tool": "does_not_exist", "objective": "should be dropped", "requires_approval": False}]}


@pytest.fixture()
def fake_llm(monkeypatch):
    def fake_json(self, messages, **kw):
        system = messages[0]["content"]
        if "planning agent" in system:
            return PLAN
        if "fact-checker" in system:
            return {"grounded": True, "score": 92, "unsupported_claims": []}
        raise AssertionError("unexpected json call")

    def fake_chat(self, messages, **kw):
        return {"content": "# Report\n\n## Executive Summary\nWest dropped sharply (Step 2). | a | b |\n\n- **Finding** one\n"}

    def fake_call_tool(self, messages, name, description, parameters):
        if name == "rag_search":
            return {"query": "regional revenue decline review requirement", "top_k": 3}
        if name == "create_chart":
            return {"chart_type": "line", "title": "Revenue by region"}
        raise LLMError("no tool call", retryable=False)  # exercises default-argument fallback

    monkeypatch.setattr(LLMClient, "json", fake_json)
    monkeypatch.setattr(LLMClient, "chat", fake_chat)
    monkeypatch.setattr(LLMClient, "call_tool", fake_call_tool)


def upload_samples(client, auth, sample_dir):
    for name in ("sales_data.csv", "company_sales_policy.pdf"):
        with open(sample_dir / name, "rb") as fh:
            r = client.post("/api/documents", headers=auth, files={"file": (name, fh)})
            assert r.status_code == 201, r.text
    docs = wait_for(client, auth, "/api/documents", lambda d: len(d) == 2 and all(x["status"] != "processing" for x in d))
    assert all(d["status"] == "ready" for d in docs), docs


def test_auth_required_and_user_isolation(client, auth):
    assert client.get("/api/workflows").status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrongpass1"}).status_code == 401
    assert client.get("/api/workflows", headers=auth).json() == []


def test_upload_validation(client, auth):
    r = client.post("/api/documents", headers=auth, files={"file": ("evil.exe", b"MZ...")})
    assert r.status_code == 415
    r = client.post("/api/documents", headers=auth, files={"file": ("empty.txt", b"")})
    assert r.status_code == 400


def test_full_workflow_with_approval(client, auth, sample_dir, fake_llm):
    upload_samples(client, auth, sample_dir)
    r = client.post("/api/workflows", headers=auth, json={
        "description": "Analyze sales, find unusual regional drops, compare with the sales policy and create an executive report.",
        "require_approval": True})
    assert r.status_code == 201
    wid = r.json()["id"]

    wf = wait_for(client, auth, f"/api/workflows/{wid}", lambda w: w["status"] in ("awaiting_approval", "failed", "completed"))
    assert wf["status"] == "awaiting_approval", wf.get("error")
    tools = [s["tool_name"] for s in wf["steps"]]
    assert tools == ["planner", "analyze_data", "ml_analysis", "rag_search", "create_chart", "validator", "report_generator"]
    assert [s["status"] for s in wf["steps"]][:6] == ["completed"] * 6 and wf["steps"][6]["status"] == "awaiting_approval"
    analysis = wf["steps"][1]
    assert analysis["input_data"]["arguments_source"] == "defaults"          # LLM tool-call failed -> defaults used
    assert "West" in analysis["output_data"]["summary"] and analysis["duration"] is not None
    rag = wf["steps"][3]["output_data"]["data"]["passages"]
    assert rag and "company_sales_policy.pdf" in rag[0]["filename"]            # real pgvector retrieval over the PDF
    assert wf["steps"][3]["input_data"]["arguments_source"] == "llm_tool_call"

    pending = client.get("/api/approvals", headers=auth).json()
    assert len(pending) == 1 and pending[0]["workflow_id"] == wid
    res = client.post(f"/api/approvals/{pending[0]['id']}/resolve", headers=auth, json={"approve": True, "note": "ok"})
    assert res.status_code == 200
    assert client.post(f"/api/approvals/{pending[0]['id']}/resolve", headers=auth, json={"approve": True}).status_code == 409

    wf = wait_for(client, auth, f"/api/workflows/{wid}", lambda w: w["status"] in ("completed", "failed"))
    assert wf["status"] == "completed", wf.get("error")
    assert wf["result"]["grounding"]["score"] == 92 and wf["result"]["charts"]
    pdf = client.get(f"/api/workflows/{wid}/report.pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"/api/workflows/{wid}/report.md", headers=auth).status_code == 200
    events = [a["event_type"] for a in client.get(f"/api/workflows/{wid}/audit", headers=auth).json()]
    assert "approval_requested" in events and "approval_approved" in events and "workflow_completed" in events


def test_rejection_stops_workflow(client, auth, sample_dir, fake_llm):
    upload_samples(client, auth, sample_dir)
    wid = client.post("/api/workflows", headers=auth, json={"description": "Analyze sales data and write a report please."}).json()["id"]
    wait_for(client, auth, f"/api/workflows/{wid}", lambda w: w["status"] == "awaiting_approval")
    appr = client.get("/api/approvals", headers=auth).json()[0]
    client.post(f"/api/approvals/{appr['id']}/resolve", headers=auth, json={"approve": False, "note": "not yet"})
    wf = client.get(f"/api/workflows/{wid}", headers=auth).json()
    assert wf["status"] == "rejected" and wf["steps"][-1]["status"] == "rejected" and "not yet" in wf["error"]


def test_other_users_cannot_see_workflow(client, auth, sample_dir, fake_llm):
    wid = client.post("/api/workflows", headers=auth, json={"description": "Analyze sales data and write a report please."}).json()["id"]
    import uuid
    r = client.post("/api/auth/register", json={"email": f"o{uuid.uuid4().hex[:8]}@example.com", "password": "supersecret1", "name": "Other"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"/api/workflows/{wid}", headers=other).status_code == 404


def test_llm_outage_fails_gracefully(client, auth, monkeypatch):
    def boom(self, *a, **k):
        raise LLMError("provider down", retryable=True)

    monkeypatch.setattr(LLMClient, "json", boom)
    wid = client.post("/api/workflows", headers=auth, json={"description": "Analyze sales data and write a report please."}).json()["id"]
    wf = wait_for(client, auth, f"/api/workflows/{wid}", lambda w: w["status"] in ("failed", "completed"))
    assert wf["status"] == "failed" and "Planning failed" in wf["error"]
