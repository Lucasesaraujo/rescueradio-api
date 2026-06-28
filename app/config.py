from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str | None = None
    redis_url: str | None = None
    jwt_secret: str = "rescueradio-dev-secret"
    jwt_expire_minutes: int = 480
    bootstrap_admin_key: str = "rescueradio-bootstrap"
    kafka_bootstrap_servers: str = ""
    kafka_audit_topic: str = "rescueradio.audit"
    cors_allow_origins: str = "*"
    enable_udp: bool = False
    udp_host: str = "0.0.0.0"
    udp_port: int = 9000
    disconnect_grace_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
