"""SUPABASE_URL is read from the environment or from .env (Settings); the placeholder is ignored."""

from __future__ import annotations

from app.api import auth
from app.core import config


class _S:
    def __init__(self, url):
        self.supabase_url = url


def test_environment_wins(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://env-proj.supabase.co")
    monkeypatch.setattr(config, "get_settings", lambda: _S("https://dotenv-proj.supabase.co"))
    assert auth.configured_supabase_url() == "https://env-proj.supabase.co"


def test_dotenv_value_used_when_environment_empty(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(config, "get_settings", lambda: _S("https://dotenv-proj.supabase.co"))
    assert auth.configured_supabase_url() == "https://dotenv-proj.supabase.co"


def test_placeholder_counts_as_not_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://your-project.supabase.co")
    assert auth.configured_supabase_url() == ""


def test_settings_field_reads_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("SUPABASE_URL=https://abc.supabase.co\n", encoding="utf-8")
    assert config.Settings(_env_file=str(env)).supabase_url == "https://abc.supabase.co"
