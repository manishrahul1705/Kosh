"""Alembic environment wired to the application's models and settings."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.database.models import Base
import app.database.auth_models  # Register authentication ORM tables
import app.database.platform_auth_models  # Register platform operator ORM tables
import app.database.matching_models  # Register seller-tender matching tables

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().resolved_database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(url),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if _is_sqlite(url):
        from pathlib import Path

        db_path = url.split("sqlite:///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(url),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


def _refuse_in_verify_mode() -> None:
    """Migrations write schema. They must never run in APP_STARTUP_MODE=verify.

    Checks an explicit override on the Alembic config as well as the cached
    global settings, so a different Settings instance cannot bypass the rule.
    """
    explicit = config.attributes.get("app_startup_mode")
    if explicit == "verify" or get_settings().app_startup_mode == "verify":
        raise RuntimeError("Alembic migrations are disabled while APP_STARTUP_MODE=verify")


_refuse_in_verify_mode()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
