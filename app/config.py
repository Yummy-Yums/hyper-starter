from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "hyper-starter"
    database_url: str = "sqlite+aiosqlite:///./hyper.db"
    rate_limit_per_minute: int = 60
    sandbox_idle_timeout_seconds: int = 1800
    admin_api_key: str = ""
    engine_backend: str = "fake"
    grpc_target: str = "localhost:50051"
    grpc_timeout_seconds: float = 30.0
    grpc_image_timeout_seconds: float = 600.0
    grpc_exec_timeout_ms: int = 60000
    grpc_arch: str = "x86_64"
    grpc_use_tls: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
