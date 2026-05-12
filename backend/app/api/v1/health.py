from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Dict
import time
import structlog

from ...db.database import check_db_health
from ...services.cache import cache_service
from ...services.metrics import registry, generate_latest, CONTENT_TYPE_LATEST

logger = structlog.get_logger()
router = APIRouter()


class ComponentHealth(BaseModel):
    status: str
    latency_ms: float


class HealthResponse(BaseModel):
    status: str
    version: str
    components: Dict[str, ComponentHealth]
    uptime_seconds: float


_start_time = time.time()


@router.get("", response_model=HealthResponse)
async def health_check():
    """System health and component status — used by K8s liveness probe."""
    components = {}
    overall_healthy = True

    t0 = time.time()
    db_ok = await check_db_health()
    components["database"] = ComponentHealth(
        status="healthy" if db_ok else "unhealthy",
        latency_ms=round((time.time() - t0) * 1000, 2),
    )
    if not db_ok:
        overall_healthy = False

    t0 = time.time()
    redis_ok = await cache_service.health_check()
    components["cache"] = ComponentHealth(
        status="healthy" if redis_ok else "degraded",
        latency_ms=round((time.time() - t0) * 1000, 2),
    )

    components["api"] = ComponentHealth(status="healthy", latency_ms=0.0)

    return HealthResponse(
        status="healthy" if overall_healthy else "degraded",
        version="1.0.0",
        components=components,
        uptime_seconds=round(time.time() - _start_time, 2),
    )


@router.get("/ready")
async def readiness_check():
    """Kubernetes readiness probe — returns 200 only when ready to serve traffic."""
    db_ok = await check_db_health()
    if not db_ok:
        return Response(content="Database not ready", status_code=503)
    return {"status": "ready"}


@router.get("/live")
async def liveness_check():
    """Kubernetes liveness probe."""
    return {"status": "alive"}


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
