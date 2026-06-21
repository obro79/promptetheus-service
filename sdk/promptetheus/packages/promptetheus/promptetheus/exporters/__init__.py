"""Outbound exporters for Promptetheus.

Exporters take a Promptetheus event stream and push it onto another system. This
is the outbound direction (Promptetheus events out to somewhere else), distinct
from adapters, which translate a framework's events inbound onto the Session API.

Optional dependencies (for instance the OpenTelemetry SDK) are imported lazily
inside each exporter module, so importing this package or any single exporter
never requires an extra to be installed. The exporter classes are resolved on
attribute access via __getattr__ so a partially-installed environment can still
import the ones it needs.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Public exporter name -> submodule that defines it.
_EXPORTER_MODULES = {
    "OTLPExporter": "otlp",
    "export_session": "otlp",
}

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .otlp import OTLPExporter as OTLPExporter
    from .otlp import export_session as export_session


def __getattr__(name: str) -> Any:
    module = _EXPORTER_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f".{module}", __name__), name)


def __dir__() -> list[str]:
    return sorted(_EXPORTER_MODULES)


__all__ = sorted(set(_EXPORTER_MODULES))
