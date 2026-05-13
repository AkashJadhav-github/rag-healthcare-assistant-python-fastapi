import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_stats_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/admin/stats")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_stats(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_documents" in data
    assert "indexed_documents" in data
    assert "total_chunks" in data
    assert "total_queries" in data
    assert "active_users" in data


@pytest.mark.asyncio
async def test_retention_stats_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/admin/retention/stats")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retention_stats(client: AsyncClient, admin_token: str):
    response = await client.get(
        "/api/v1/admin/retention/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "audit_logs" in data
    assert "query_logs" in data
    assert "policy_applied_at" in data


@pytest.mark.asyncio
async def test_retention_purge_requires_auth(client: AsyncClient):
    response = await client.post("/api/v1/admin/retention/purge")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retention_purge(client: AsyncClient, admin_token: str):
    response = await client.post(
        "/api/v1/admin/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "audit_logs_deleted" in data
    assert "query_logs_deleted" in data
    assert "purged_at" in data


@pytest.mark.asyncio
async def test_reindex_requires_auth(client: AsyncClient):
    response = await client.post("/api/v1/admin/reindex")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reindex(client: AsyncClient, admin_token: str):
    response = await client.post(
        "/api/v1/admin/reindex",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_user_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "newuser@test.com",
            "username": "newuser",
            "password": "NewUser@123!",
            "full_name": "New User",
            "role": "viewer",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_user(client: AsyncClient, admin_token: str):
    response = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "newuser@test.com",
            "username": "newuser",
            "password": "NewUser@123!",
            "full_name": "New User",
            "role": "viewer",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code in (200, 201)
