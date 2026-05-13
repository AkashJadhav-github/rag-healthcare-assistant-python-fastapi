import tempfile
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "RAG Healthcare Assistant"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # API
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-this-in-production-use-256-bit-key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "healthcare_user"
    POSTGRES_PASSWORD: str = "healthcare_pass"
    POSTGRES_DB: str = "healthcare_rag"
    DATABASE_URL: Optional[str] = None

    @property
    def async_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    CACHE_TTL_SECONDS: int = 3600

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-ada-002"
    OPENAI_LLM_MODEL: str = "gpt-4-turbo-preview"
    OPENAI_MAX_TOKENS: int = 2048

    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

    # LLM Provider (openai | anthropic | local)
    LLM_PROVIDER: str = "openai"
    EMBEDDING_PROVIDER: str = "openai"

    # Vector DB (pgvector)
    VECTOR_DIMENSION: int = 1536
    VECTOR_INDEX_TYPE: str = "ivfflat"
    SIMILARITY_THRESHOLD: float = 0.7
    MAX_RETRIEVAL_DOCS: int = 5

    # RAG Pipeline
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    MAX_DOCUMENT_SIZE_MB: int = 50
    BATCH_SIZE: int = 50

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000

    # File Upload
    UPLOAD_DIR: str = str(tempfile.gettempdir()) + "/healthcare_uploads"
    ALLOWED_EXTENSIONS: List[str] = ["pdf", "docx", "txt", "md"]

    # Monitoring
    ENABLE_METRICS: bool = True
    JAEGER_HOST: str = "localhost"
    JAEGER_PORT: int = 6831

    # AWS (optional)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: Optional[str] = None

    # Encryption
    ENCRYPTION_KEY: Optional[str] = None

    # Data Retention
    AUDIT_LOG_RETENTION_DAYS: int = 2190   # 6 years
    QUERY_LOG_RETENTION_DAYS: int = 90

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
