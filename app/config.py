from __future__ import annotations

import os
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field, validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Uses pydantic.BaseSettings to provide type-safe configuration loaded from the environment.
    """

    # External API keys
    GOOGLE_API_KEY: str = Field(..., env="GOOGLE_API_KEY")

    # AI configuration
    EMBEDDING_MODEL: str = Field("gemini-embedding-001", env="EMBEDDING_MODEL")
    EMBEDDING_DIMENSIONS: int = Field(1536, env="EMBEDDING_DIMENSIONS")
    LLM_MODEL: str = Field("gemini-2.5-flash", env="LLM_MODEL")

    # Database and infra
    POSTGRES_USER: str = Field(..., env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(..., env="POSTGRES_PASSWORD")
    POSTGRES_DB: str = Field(..., env="POSTGRES_DB")
    POSTGRES_HOST: str = Field("postgres", env="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(5432, env="POSTGRES_PORT")
    DATABASE_URL: Optional[str] = Field(None, env="DATABASE_URL")

    REDIS_HOST: str = Field("redis", env="REDIS_HOST")
    REDIS_PORT: int = Field(6379, env="REDIS_PORT")
    CELERY_BROKER_URL: str = Field(..., env="CELERY_BROKER_URL")
    CELERY_RESULT_BACKEND: str = Field(..., env="CELERY_RESULT_BACKEND")

    QDRANT_HOST: str = Field("qdrant", env="QDRANT_HOST")
    QDRANT_PORT: int = Field(6333, env="QDRANT_PORT")
    QDRANT_COLLECTION: str = Field("web_documents", env="QDRANT_COLLECTION")

    API_PORT: int = Field(8000, env="API_PORT")
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")

    # Chunking and retrieval
    CHUNK_SIZE: int = Field(800, env="CHUNK_SIZE")
    CHUNK_OVERLAP: int = Field(100, env="CHUNK_OVERLAP")
    TOP_K_RESULTS: int = Field(5, env="TOP_K_RESULTS")

    class Config:
        """Pydantic configuration for environment variable support."""
        env_file = ".env"
        env_file_encoding = "utf-8"

    @validator("DATABASE_URL", pre=True, always=True)
    def build_database_url(cls, v, values):  # type: ignore[override]
        """Ensure DATABASE_URL exists. If provided in short form or not provided, build from components.

        Also convert to SQLAlchemy async URL using asyncpg driver if necessary.
        """
        if v:
            # Allow postgres:// or postgresql:// and convert to asyncpg format for SQLAlchemy async engine
            if v.startswith("postgresql+asyncpg://"):
                return v
            if v.startswith("postgresql://"):
                return v.replace("postgresql://", "postgresql+asyncpg://", 1)
            if v.startswith("postgres://"):
                return v.replace("postgres://", "postgresql+asyncpg://", 1)
            return v

        # Build from components
        user = values.get("POSTGRES_USER")
        password = values.get("POSTGRES_PASSWORD")
        host = values.get("POSTGRES_HOST", "postgres")
        port = values.get("POSTGRES_PORT", 5432)
        db = values.get("POSTGRES_DB")
        if not all([user, password, db]):
            raise ValueError("Insufficient PostgreSQL configuration to build DATABASE_URL")
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


# Singleton settings instance to be imported by modules
settings = Settings()
