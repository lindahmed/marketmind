import pytest

from tests.conftest import register

ECOMMERCE = "date,revenue,orders,ad_spend,cost_of_goods\n2026-01-01,100,5,80,40\n"


def upload(client, content, **kwargs):
    return client.post("/api/data/import", files={"file": ("daily.csv", content, "text/csv")}, **kwargs)


def test_auth_and_session(clients):
    client, _ = clients
    assert client.get("/api/business").status_code == 401
    register(client)
    assert client.get("/api/auth/me").json()["email"] == "owner@example.com"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": "bad-password"}).status_code == 401
    response = client.post("/api/auth/login", json={"email": "OWNER@example.com", "password": "a-good-test-password"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    client.cookies.set("marketmind_session", "forged-token")
    assert client.get("/api/business").status_code == 401


def test_cross_tenant_access_is_rejected(clients):
    first, second = clients
    tenant_a = register(first)
    tenant_b = register(second, "second@example.com")
    assert tenant_a != tenant_b
    assert upload(first, ECOMMERCE).status_code == 200
    assert second.get("/api/dashboard").json()["row_count"] == 0
    assert first.get("/api/dashboard").json()["row_count"] == 1
    foreign_headers = {"X-Workspace-ID": tenant_a}
    for path in ("/api/business", "/api/dashboard"):
        assert second.get(path, headers=foreign_headers).status_code == 403
    assert upload(second, ECOMMERCE, headers=foreign_headers).status_code == 403
    payload = first.get("/api/business").json()
    payload.pop("id")
    payload.pop("industry")
    payload["name"] = "Attempted change"
    assert second.put("/api/business", headers=foreign_headers, json=payload).status_code == 403
    assert first.get("/api/business").json()["name"] == "Test Business"


def test_profile_persistence_and_currency_lock(clients):
    client, _ = clients
    register(client)
    payload = {"name": "Changed Business", "currency": "EGP", "monthly_budget": "2500.00",
               "goals": ["Improve margin"], "constraints": ["No discounts"], "description": "A local store"}
    assert client.put("/api/business", json=payload).status_code == 200
    assert client.get("/api/business").json()["goals"] == ["Improve margin"]
    assert upload(client, ECOMMERCE).status_code == 200
    payload["currency"] = "USD"
    assert client.put("/api/business", json=payload).status_code == 409
    assert client.get("/api/business").json()["currency"] == "EGP"


def test_profit_findings_and_idempotent_import(clients):
    client, _ = clients
    register(client)
    assert upload(client, ECOMMERCE).status_code == 200
    overview = client.get("/api/dashboard").json()
    assert overview["kpis"]["estimated_profit"] == -20
    assert overview["kpis"]["unattributed_revenue_ad_spend_ratio"] == 1.25
    assert overview["kpis"]["average_order_value"] == 20
    assert overview["findings"][0]["code"] == "negative_profit"
    assert upload(client, ECOMMERCE.replace(",100,", ",200,")).status_code == 200
    overview = client.get("/api/dashboard").json()
    assert overview["row_count"] == 1
    assert overview["kpis"]["revenue"] == 200
    assert overview["kpis"]["estimated_profit"] == 80


@pytest.mark.parametrize("content", [
    "date,revenue\n2026-01-01,100\n",
    ECOMMERCE.replace(",100,", ",NaN,"),
    ECOMMERCE.replace(",100,", ",inf,"),
    ECOMMERCE.replace(",100,", ",-1,"),
    ECOMMERCE.replace(",5,", ",5.5,"),
    ECOMMERCE.replace("2026-01-01", "invalid"),
    ECOMMERCE + "2026-01-01,10,1,1,1\n",
    ECOMMERCE + "2026-01-02,broken,1,1,1\n",
])
def test_invalid_import_is_atomic(clients, content):
    client, _ = clients
    register(client)
    assert upload(client, content).status_code == 422
    assert client.get("/api/dashboard").json()["row_count"] == 0


def test_appointment_pack_and_origin_protection(clients):
    client, _ = clients
    register(client, industry="appointments")
    content = "date,revenue,bookings,completed,ad_spend,variable_cost\n2026-01-01,100,10,6,20,30\n"
    assert upload(client, content).status_code == 200
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["kpis"]["estimated_profit"] == 50
    assert dashboard["kpis"]["completion_rate"] == 60
    assert dashboard["findings"][0]["code"] == "low_completion_rate"
    assert upload(client, content.replace(",6,", ",11,")).status_code == 422
    assert client.post("/api/auth/logout", headers={"Origin": "https://hostile.example"}).status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_duplicate_email_rollback_and_upload_limit(clients):
    first, second = clients
    register(first)
    response = second.post("/api/auth/register", json={"email": "OWNER@example.com", "password": "a-good-test-password",
                           "business_name": "Duplicate", "industry": "ecommerce"})
    assert response.status_code == 409
    assert second.get("/api/auth/me").status_code == 401
    assert upload(first, b"x" * (2 * 1024 * 1024 + 1)).status_code == 413


def test_private_evidence_search_and_investigation_history(clients):
    first, second = clients
    workspace_a = register(first)
    register(second, "second@example.com")
    source_a = b"# Returns policy\n\nRefunds are available within thirty days when an item is unused."
    source_b = b"# Returns policy\n\nStore credit is issued only after a completed salon appointment."
    doc_a = first.post("/api/knowledge/documents", files={"file": ("returns.md", source_a, "text/markdown")})
    doc_b = second.post("/api/knowledge/documents", files={"file": ("returns.md", source_b, "text/markdown")})
    assert doc_a.status_code == doc_b.status_code == 201
    assert len(first.get("/api/knowledge/documents").json()) == 1
    assert len(second.get("/api/knowledge/documents").json()) == 1
    assert first.post("/api/knowledge/documents", files={"file": ("copy.md", source_a, "text/markdown")}).status_code == 409
    results_a = first.post("/api/knowledge/search", json={"query": "refunds unused"}).json()["results"]
    results_b = second.post("/api/knowledge/search", json={"query": "refunds unused"}).json()["results"]
    assert results_a
    assert {match["source"] for match in results_a} == {"returns.md"}
    assert "thirty days" in results_a[0]["excerpt"]
    assert results_b == []
    report = first.post("/api/investigations", json={"question": "Why are refunds increasing?"})
    assert report.status_code == 201
    report = report.json()
    assert report["status"] == "evidence_ready"
    assert report["model"] is None and report["confidence"] is None
    assert report["result"]["evidence_sources"][0]["document"] == "returns.md"
    run_id = report["id"]
    assert len(first.get("/api/investigations").json()) == 1
    assert first.get(f"/api/investigations/{run_id}").json()["question"] == "Why are refunds increasing?"
    assert second.get(f"/api/investigations/{run_id}").status_code == 404
    assert second.get(f"/api/investigations/{run_id}", headers={"X-Workspace-ID": workspace_a}).status_code == 403
    assert second.post("/api/knowledge/search", headers={"X-Workspace-ID": workspace_a},
                       json={"query": "refunds"}).status_code == 403
    assert first.delete(f"/api/knowledge/documents/{doc_a.json()['id']}").status_code == 204
    assert first.post("/api/knowledge/search", json={"query": "refunds"}).json()["results"] == []
    assert len(second.get("/api/knowledge/documents").json()) == 1


def test_knowledge_upload_limits_and_search_validation(clients):
    client, _ = clients
    register(client)
    assert client.post("/api/knowledge/documents", files={"file": ("secret.pdf", b"not a pdf", "application/pdf")}).status_code == 415
    assert client.post("/api/knowledge/documents", files={"file": ("blank.md", b" \n", "text/markdown")}).status_code == 422
    assert client.post("/api/knowledge/documents", files={"file": ("large.txt", b"x" * (200 * 1024 + 1), "text/plain")}).status_code == 413
    assert client.post("/api/knowledge/documents", files={"file": ("bad.txt", b"\xff", "text/plain")}).status_code == 422
    assert client.post("/api/knowledge/search", json={"query": "  "}).status_code == 422
    assert client.post("/api/investigations", json={"question": " ? "}).status_code == 422
