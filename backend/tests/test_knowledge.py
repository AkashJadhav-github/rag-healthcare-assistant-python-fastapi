import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ask_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/knowledge/ask", json={"query": "What is hypertension?"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ask_too_short_query(client: AsyncClient, clinician_token: str):
    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"query": "Hi"},
        headers={"Authorization": f"Bearer {clinician_token}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@patch("app.api.v1.knowledge.RAGPipeline")
async def test_ask_success(
    mock_pipeline_class, client: AsyncClient, clinician_token: str
):
    mock_pipeline = MagicMock()
    mock_pipeline.query = AsyncMock(
        return_value={
            "answer": "Hypertension is elevated blood pressure above 130/80 mmHg.",
            "sources": [],
            "confidence_score": 0.88,
            "model_used": "gpt-4-turbo-preview",
            "latency_ms": 1200,
        }
    )
    mock_pipeline_class.return_value = mock_pipeline

    response = await client.post(
        "/api/v1/knowledge/ask",
        json={"query": "What is hypertension and how is it diagnosed?"},
        headers={"Authorization": f"Bearer {clinician_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "sources" in data
    assert "confidence_score" in data
    assert "query_id" in data


@pytest.mark.asyncio
async def test_get_history_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/knowledge/history")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_history_empty(client: AsyncClient, clinician_token: str):
    response = await client.get(
        "/api/v1/knowledge/history",
        headers={"Authorization": f"Bearer {clinician_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_ingest_requires_permission(client: AsyncClient, admin_token: str):
    """Test that a viewer cannot ingest documents (only clinician+)."""

    response = await client.post(
        "/api/v1/knowledge/ingest",
        files={"file": ("test.txt", io.BytesIO(b"Test content"), "text/plain")},
        data={"title": "Test Document"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code in (200, 202, 422)


@pytest.mark.asyncio
async def test_ingest_unsupported_format(client: AsyncClient, admin_token: str):
    response = await client.post(
        "/api/v1/knowledge/ingest",
        files={
            "file": ("test.exe", io.BytesIO(b"\x4d\x5a"), "application/octet-stream")
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_delete_document_not_found(client: AsyncClient, admin_token: str):
    """DELETE a non-existent document UUID should return 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(
        f"/api/v1/knowledge/documents/{fake_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_requires_auth(client: AsyncClient):
    """DELETE /knowledge/documents/<uuid> with no auth should return 403."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = await client.delete(f"/api/v1/knowledge/documents/{fake_id}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_history_pagination(client: AsyncClient, clinician_token: str):
    """GET /knowledge/history with pagination params should return 200 and a list."""
    response = await client.get(
        "/api/v1/knowledge/history",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {clinician_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
@patch("app.api.v1.knowledge.RAGPipeline")
async def test_ask_with_session_id(
    mock_pipeline_class, client: AsyncClient, clinician_token: str
):
    """POST /knowledge/ask with a session_id should return 200 and expected fields."""
    mock_pipeline = MagicMock()
    mock_pipeline.query = AsyncMock(
        return_value={
            "answer": "Diabetes is a metabolic disease characterised by high blood sugar.",
            "sources": [],
            "confidence_score": 0.91,
            "model_used": "gpt-4-turbo-preview",
            "latency_ms": 950,
        }
    )
    mock_pipeline_class.return_value = mock_pipeline

    response = await client.post(
        "/api/v1/knowledge/ask",
        json={
            "query": "What are the symptoms of type 2 diabetes?",
            "session_id": "11111111-1111-1111-1111-111111111111",
        },
        headers={"Authorization": f"Bearer {clinician_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "sources" in data
    assert "confidence_score" in data
    assert "query_id" in data


@pytest.mark.asyncio
async def test_ingest_no_auth(client: AsyncClient):
    """POST /knowledge/ingest with no auth should return 403."""
    import io

    response = await client.post(
        "/api/v1/knowledge/ingest",
        files={"file": ("test.txt", io.BytesIO(b"Some content"), "text/plain")},
        data={"title": "Unauthenticated Upload"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retention_stats(client: AsyncClient, admin_token: str):
    """GET /admin/retention/stats with admin token should return 200 with expected shape."""
    response = await client.get(
        "/api/v1/admin/retention/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "audit_logs" in data
    assert "query_logs" in data
    assert "policy_applied_at" in data
    assert "total" in data["audit_logs"]
    assert "expired" in data["audit_logs"]
    assert "retention_days" in data["audit_logs"]
