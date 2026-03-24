from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    secret_key: str
    database_url: str
    default_admin_email: str
    default_admin_password: str
    default_admin_username: str
    host: str
    port: int


def get_settings() -> Settings:
    server_root = Path(__file__).resolve().parents[1]
    default_sqlite_url = f"sqlite:///{server_root / 'data' / 'openeelo.db'}"
    return Settings(
        app_name=os.getenv("OPENELO_APP_NAME", "OpenELO"),
        secret_key=os.getenv("OPENELO_SECRET_KEY", "change-me"),
        database_url=os.getenv("OPENELO_DATABASE_URL", default_sqlite_url),
        default_admin_email=os.getenv("OPENELO_DEFAULT_ADMIN_EMAIL", "admin@example.com"),
        default_admin_password=os.getenv("OPENELO_DEFAULT_ADMIN_PASSWORD", "admin123"),
        default_admin_username=os.getenv("OPENELO_DEFAULT_ADMIN_USERNAME", "admin"),
        host=os.getenv("OPENELO_HOST", "0.0.0.0"),
        port=int(os.getenv("OPENELO_PORT", "8000")),
    )
