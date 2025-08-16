# backend/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
from typing import List

ROOT_DIR = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    app_env: str = Field("dev", env="APP_ENV")
    debug: bool = Field(True, env="DEBUG")

    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")

    # JWT/сесії
    access_ttl_minutes: int = Field(15, env="ACCESS_TTL_MINUTES")
    refresh_ttl_days:   int = Field(7, env="REFRESH_TTL_DAYS")
    sliding_window_enabled:   bool = Field(True,  env="SLIDING_WINDOW_ENABLED")
    sliding_extend_seconds:   int  = Field(120,   env="SLIDING_EXTEND_SECONDS")
    access_grace_seconds:     int  = Field(60,    env="ACCESS_GRACE_SECONDS")
    reuse_grace_on_disconnect:bool = Field(True,  env="REUSE_GRACE_ON_DISCONNECT")
    auto_release_idle_minutes:int  = Field(10,    env="AUTO_RELEASE_IDLE_MINUTES")
    session_retention_days: int = Field(30, env="SESSION_RETENTION_DAYS")
    session_events_retention_days: int = Field(30, env="SESSION_EVENTS_RETENTION_DAYS")
    refresh_tokens_retention_days: int = Field(30, env="REFRESH_TOKENS_RETENTION_DAYS")
    gc_interval_minutes: int = Field(60, env="GC_INTERVAL_MINUTES")
    gc_batch_size: int = Field(1000, env="GC_BATCH_SIZE")

    # безпека / CORS
    allowed_hosts: str = Field("127.0.0.1,localhost", env="ALLOWED_HOSTS")
    allowed_origins: str = Field("", env="ALLOWED_ORIGINS")  # ← залишаємо лише одне

    # генерація кодів
    code_length:  int    = Field(10,  env="CODE_LENGTH")
    code_alphabet:str    = Field("ABCDEFGHJKMNPQRSTUVWXYZ23456789", env="CODE_ALPHABET")

    # інше
    jwt_secret:        str = Field(..., env='JWT_SECRET')
    admin_jwt_secret:  str = Field(..., env='ADMIN_JWT_SECRET')
    db_url:            str = Field(..., env='DB_URL')
    admin_token_ttl_h: int = Field(2,  env='ADMIN_TOKEN_TTL_H')
    admin_root_email:  str | None = Field(default=None, env="ADMIN_ROOT_EMAIL")
    admin_root_pass:   str | None = Field(default=None, env="ADMIN_ROOT_PASS")
    rate_attempts:     int = Field(5,  env="RATE_ATTEMPTS")
    rate_base:         int = Field(1,  env="RATE_BASE")

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding='utf-8',
        extra="ignore",
    )

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

settings = Settings()
