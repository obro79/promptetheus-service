from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "promptetheus"
sys.path.insert(0, str(PACKAGE_ROOT))

from promptetheus.config import (  # noqa: E402
    Config,
    DEFAULT_API_URL,
    DEFAULT_HTTP_TIMEOUT,
    load_config,
    override_config,
    reset_config,
)


def _write_toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_when_nothing_set(monkeypatch, tmp_path):
    for var in (
        "PROMPTETHEUS_API_URL",
        "PROMPTETHEUS_API_KEY",
        "PROMPTETHEUS_PROJECT",
        "PROMPTETHEUS_ENVIRONMENT",
        "PROMPTETHEUS_SAMPLE_RATE",
        "PROMPTETHEUS_REDACT",
        "PROMPTETHEUS_HTTP_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    config = load_config(config_path=tmp_path / "missing.toml")
    assert config == Config()
    assert config.sample_rate == 1.0
    assert config.api_url == DEFAULT_API_URL
    assert config.http_timeout == DEFAULT_HTTP_TIMEOUT


def test_toml_layer(monkeypatch, tmp_path):
    monkeypatch.delenv("PROMPTETHEUS_API_URL", raising=False)
    monkeypatch.delenv("PROMPTETHEUS_SAMPLE_RATE", raising=False)
    path = _write_toml(
        tmp_path,
        'api_url = "http://toml:4318"\nsample_rate = 0.25\nredact = "default"\n',
    )
    config = load_config(config_path=path)
    assert config.api_url == "http://toml:4318"
    assert config.sample_rate == 0.25
    assert config.redact == "default"


def test_env_overrides_toml(monkeypatch, tmp_path):
    path = _write_toml(tmp_path, 'api_url = "http://toml:4318"\nhttp_timeout = 12\n')
    monkeypatch.setenv("PROMPTETHEUS_API_URL", "http://env:4318")
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "18.5")
    config = load_config(config_path=path)
    assert config.api_url == "http://env:4318"
    assert config.http_timeout == 18.5


def test_explicit_kwargs_override_everything(monkeypatch, tmp_path):
    path = _write_toml(tmp_path, 'api_url = "http://toml:4318"\nhttp_timeout = 12\n')
    monkeypatch.setenv("PROMPTETHEUS_API_URL", "http://env:4318")
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "18.5")
    config = load_config(
        api_url="http://explicit:4318",
        http_timeout=7.25,
        config_path=path,
    )
    assert config.api_url == "http://explicit:4318"
    assert config.http_timeout == 7.25


def test_malformed_toml_is_tolerated(monkeypatch, tmp_path):
    for var in ("PROMPTETHEUS_API_URL", "PROMPTETHEUS_SAMPLE_RATE"):
        monkeypatch.delenv(var, raising=False)
    path = _write_toml(tmp_path, "this is = not valid = toml [[[")
    config = load_config(config_path=path)  # must not raise
    assert config.api_url == DEFAULT_API_URL
    assert config.sample_rate == 1.0


def test_promptetheus_table_form(monkeypatch, tmp_path):
    monkeypatch.delenv("PROMPTETHEUS_PROJECT", raising=False)
    path = _write_toml(tmp_path, '[promptetheus]\nproject_id = "proj_42"\n')
    assert load_config(config_path=path).project_id == "proj_42"


def test_sample_rate_clamped(monkeypatch, tmp_path):
    monkeypatch.delenv("PROMPTETHEUS_SAMPLE_RATE", raising=False)
    assert load_config(sample_rate=5.0, config_path=tmp_path / "x.toml").sample_rate == 1.0
    assert load_config(sample_rate=-2.0, config_path=tmp_path / "x.toml").sample_rate == 0.0


def test_invalid_http_timeout_uses_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPTETHEUS_HTTP_TIMEOUT", "0")
    assert (
        load_config(config_path=tmp_path / "x.toml").http_timeout
        == DEFAULT_HTTP_TIMEOUT
    )


def test_override_config_context_manager():
    reset_config()
    with override_config(Config(api_url="http://overridden")):
        from promptetheus.config import get_config

        assert get_config().api_url == "http://overridden"
    # restored afterwards
    reset_config()
