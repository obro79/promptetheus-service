"""Layered configuration for the Promptetheus SDK.

Resolves SDK defaults from, in descending priority:

1. Explicit keyword arguments passed to load_config.
2. Environment variables (PROMPTETHEUS_API_URL, PROMPTETHEUS_API_KEY,
   PROMPTETHEUS_PROJECT, PROMPTETHEUS_ENVIRONMENT,
   PROMPTETHEUS_SAMPLE_RATE, PROMPTETHEUS_REDACT,
   PROMPTETHEUS_HTTP_TIMEOUT).
3. A TOML file at ~/.promptetheus/config.toml (parsed with the stdlib
   tomllib).
4. Built-in defaults, including the hosted Promptetheus API URL.

This module only *resolves and threads* configuration. It deliberately does not
implement sampling or redaction behavior — those live in session.py. Reading
config is best-effort and never raises: a missing or malformed TOML file is
treated as "no file present" and falls through to env vars and defaults, so a
broken config file can never crash an observed agent at import or startup.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger("promptetheus")

# Hosted Promptetheus API used when users provide only PROMPTETHEUS_API_KEY.
DEFAULT_API_URL = "https://api-production-8a8a.up.railway.app"
DEFAULT_HTTP_TIMEOUT = 30.0

# Default on-disk location of the optional user config file.
DEFAULT_CONFIG_PATH = Path.home() / ".promptetheus" / "config.toml"

# Env var name -> Config field name. Kept explicit so the precedence layer and
# the TOML layer agree on exactly which keys exist.
_ENV_TO_FIELD: dict[str, str] = {
    "PROMPTETHEUS_API_URL": "api_url",
    "PROMPTETHEUS_API_KEY": "api_key",
    "PROMPTETHEUS_PROJECT": "project_id",
    "PROMPTETHEUS_ENVIRONMENT": "environment",
    "PROMPTETHEUS_SAMPLE_RATE": "sample_rate",
    "PROMPTETHEUS_REDACT": "redact",
    "PROMPTETHEUS_HTTP_TIMEOUT": "http_timeout",
}

# TOML key -> Config field name. The TOML file uses the same short names as the
# dataclass fields (under an optional top-level table), so this is identity for
# the fields we recognize.
_TOML_KEYS: tuple[str, ...] = (
    "api_url",
    "api_key",
    "project_id",
    "environment",
    "sample_rate",
    "redact",
    "http_timeout",
)

# Built-in defaults for fields that are not None by default.
_DEFAULT_SAMPLE_RATE = 1.0


@dataclass(frozen=True)
class Config:
    """Resolved SDK configuration.

    api_url defaults to the hosted Promptetheus API. api_key remains None until
    explicitly configured so installs cannot write without a project-scoped key.
    """

    api_url: str | None = DEFAULT_API_URL
    api_key: str | None = None
    project_id: str | None = None
    environment: str | None = None
    sample_rate: float = _DEFAULT_SAMPLE_RATE
    redact: str | None = None
    http_timeout: float = DEFAULT_HTTP_TIMEOUT


def _coerce_sample_rate(value: Any) -> float | None:
    """Coerce a sample-rate value to a clamped float, or None if unusable."""

    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        logger.warning(
            "Promptetheus ignoring invalid sample_rate %r; using default", value
        )
        return None
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return rate


def _coerce_positive_float(value: Any, *, field_name: str) -> float | None:
    """Coerce a numeric config value to a positive float, or None if unusable."""

    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        logger.warning(
            "Promptetheus ignoring invalid %s %r; using default", field_name, value
        )
        return None
    if parsed <= 0.0:
        logger.warning(
            "Promptetheus ignoring non-positive %s %r; using default",
            field_name,
            value,
        )
        return None
    return parsed


def _coerce_str(value: Any) -> str | None:
    """Coerce a value to a non-empty string, or None."""

    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


def _read_toml(path: Path) -> dict[str, Any]:
    """Read recognized keys from the TOML config file.

    Tolerates a missing or malformed file by returning an empty mapping; never
    raises. Recognized keys may live at the top level or under a
    [promptetheus] table.
    """

    try:
        if not path.is_file():
            return {}
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        logger.warning(
            "Promptetheus could not read config file %s; using defaults", path
        )
        return {}
    except Exception:  # pragma: no cover - defensive: config must never crash startup
        logger.exception("Promptetheus unexpected error reading config file %s", path)
        return {}

    if not isinstance(data, dict):
        return {}

    # Allow an optional [promptetheus] table; fall back to top-level keys.
    table = data.get("promptetheus")
    source: dict[str, Any] = table if isinstance(table, dict) else data

    return {key: source[key] for key in _TOML_KEYS if key in source}


def load_config(
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    project_id: str | None = None,
    environment: str | None = None,
    sample_rate: float | None = None,
    redact: str | None = None,
    http_timeout: float | None = None,
    config_path: str | Path | None = None,
) -> Config:
    """Merge explicit kwargs, env vars, the TOML file, and defaults into a Config.

    Precedence (highest first): explicit kwargs > environment variables > TOML
    file (~/.promptetheus/config.toml by default) > built-in defaults. Any
    field left unresolved keeps its dataclass default (hosted API URL for
    api_url, None for credentials, 1.0 for sample_rate). Never raises.
    """

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    toml_values = _read_toml(path)

    env_values: dict[str, Any] = {}
    for env_name, field_name in _ENV_TO_FIELD.items():
        raw = os.environ.get(env_name)
        if raw is not None and raw != "":
            env_values[field_name] = raw

    explicit: dict[str, Any] = {
        "api_url": api_url,
        "api_key": api_key,
        "project_id": project_id,
        "environment": environment,
        "sample_rate": sample_rate,
        "redact": redact,
        "http_timeout": http_timeout,
    }

    defaults = Config()

    def _resolve(field_name: str) -> Any:
        # explicit kwargs > env vars > TOML > dataclass default.
        if explicit.get(field_name) is not None:
            return explicit[field_name]
        if field_name in env_values:
            return env_values[field_name]
        if field_name in toml_values:
            return toml_values[field_name]
        return getattr(defaults, field_name)

    sample_rate_value = _coerce_sample_rate(_resolve("sample_rate"))
    http_timeout_value = _coerce_positive_float(
        _resolve("http_timeout"), field_name="http_timeout"
    )

    return Config(
        api_url=_coerce_str(_resolve("api_url")),
        api_key=_coerce_str(_resolve("api_key")),
        project_id=_coerce_str(_resolve("project_id")),
        environment=_coerce_str(_resolve("environment")),
        sample_rate=sample_rate_value
        if sample_rate_value is not None
        else _DEFAULT_SAMPLE_RATE,
        redact=_coerce_str(_resolve("redact")),
        http_timeout=http_timeout_value
        if http_timeout_value is not None
        else DEFAULT_HTTP_TIMEOUT,
    )


# Process-wide cached config. get_config populates it lazily so the (cheap
# but non-zero) TOML read happens at most once per process unless overridden.
_cached_config: Config | None = None


def get_config() -> Config:
    """Return the cached process-wide Config, loading it on first use.

    The cache resolves environment and TOML state once. Use
    set_config/reset_config (or override_config) to control
    it from tests; production code generally just reads it.
    """

    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def set_config(config: Config) -> None:
    """Override the cached config (primarily for tests)."""

    global _cached_config
    _cached_config = config


def reset_config() -> None:
    """Clear the cached config so the next get_config reloads it."""

    global _cached_config
    _cached_config = None


class override_config:
    """Context manager that swaps in a temporary cached config for tests.

    Restores the previous cached value (including None/unloaded) on exit:

        with override_config(Config(api_url="http://localhost:4318")):
            ...
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._previous: Config | None = None

    def __enter__(self) -> Config:
        global _cached_config
        self._previous = _cached_config
        _cached_config = self._config
        return self._config

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        global _cached_config
        _cached_config = self._previous


__all__ = [
    "Config",
    "DEFAULT_API_URL",
    "DEFAULT_HTTP_TIMEOUT",
    "DEFAULT_CONFIG_PATH",
    "get_config",
    "load_config",
    "override_config",
    "reset_config",
    "set_config",
]


# Reference fields so a future field addition that forgets the resolver maps
# is easy to audit; keeps the import meaningful without changing behavior.
assert {f.name for f in fields(Config)} >= set(_TOML_KEYS)
