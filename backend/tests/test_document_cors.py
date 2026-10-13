"""Exercise the credentialed browser preflight and actual private document deletion."""
from tests.conftest import register


def test_document_delete_browser_cors_and_tenant_boundary(clients):
    first, second = clients
    workspace_a = register(first)
    register(second, "second@example.com")
    document = first.post("/api/knowledge/documents", files={"file": ("policy.md", b"Private refund policy", "text/markdown")})
    assert document.status_code == 201
    path = f"/api/knowledge/documents/{document.json()['id']}"
    origin = "http://localhost:3000"
    preflight = first.options(path, headers={"Origin": origin, "Access-Control-Request-Method": "DELETE",
                                            "Access-Control-Request-Headers": "X-Workspace-ID"})
    assert preflight.status_code == 200
    assert "DELETE" in preflight.headers["access-control-allow-methods"]
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["access-control-allow-credentials"] == "true"
    assert "x-workspace-id" in preflight.headers["access-control-allow-headers"].lower()
    assert second.delete(path, headers={"Origin": origin}).status_code == 404
    assert second.delete(path, headers={"Origin": origin, "X-Workspace-ID": workspace_a}).status_code == 403
    hostile = "https://hostile.example"
    rejected = first.options(path, headers={"Origin": hostile, "Access-Control-Request-Method": "DELETE"})
    assert rejected.status_code == 400 and "access-control-allow-origin" not in rejected.headers
    assert first.delete(path, headers={"Origin": hostile}).status_code == 403
    assert len(first.get("/api/knowledge/documents").json()) == 1
    deleted = first.delete(path, headers={"Origin": origin, "X-Workspace-ID": workspace_a})
    assert deleted.status_code == 204
    assert deleted.headers["access-control-allow-origin"] == origin
    assert deleted.headers["access-control-allow-credentials"] == "true"
    assert first.get("/api/knowledge/documents").json() == []
    assert first.post("/api/knowledge/search", json={"query": "refund"}).json()["results"] == []
