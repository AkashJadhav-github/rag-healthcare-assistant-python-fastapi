import hashlib
import json
from typing import Any, Optional

import redis.asyncio as aioredis
import structlog

from ..config import settings

logger = structlog.get_logger()


class CacheService:
    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    async def client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_keepalive=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
        return self._client

    async def get(self, key: str) -> Optional[Any]:
        try:
            c = await self.client()
            value = await c.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.warning("cache_get_failed", key=key, error=str(e))
        return None

    async def set(
        self, key: str, value: Any, ttl: int = settings.CACHE_TTL_SECONDS
    ) -> bool:
        try:
            c = await self.client()
            await c.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception as e:
            logger.warning("cache_set_failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        try:
            c = await self.client()
            await c.delete(key)
            return True
        except Exception as e:
            logger.warning("cache_delete_failed", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        try:
            c = await self.client()
            return bool(await c.exists(key))
        except Exception:
            return False

    async def health_check(self) -> bool:
        try:
            c = await self.client()
            await c.ping()
            return True
        except Exception as e:
            logger.error("redis_health_check_failed", error=str(e))
            return False

    async def increment(self, key: str, expire: int = 60) -> int:
        try:
            c = await self.client()
            pipe = c.pipeline()
            await pipe.incr(key)
            await pipe.expire(key, expire)
            results = await pipe.execute()
            return results[0]
        except Exception:
            return 0

    @staticmethod
    def make_query_key(query: str, user_id: str = "") -> str:
        content = f"query:{user_id}:{query}"
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def make_embedding_key(text: str) -> str:
        return f"emb:{hashlib.sha256(text.encode()).hexdigest()}"


cache_service = CacheService()
