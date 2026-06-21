"""Import-isolation for the adapter test suite.

Some adapter tests are lib-verified: they import the real third-party framework
(for example dspy) to prove the adapter is a genuine subclass of the documented
base and that driving the real hook surface stays thin. Importing a real
framework transitively pulls in heavy provider SDKs (dspy imports openai), and
those leak into sys.modules for the remainder of the process.

That leak silently breaks the import-safety contract that other adapter tests
assert, namely that importing a promptetheus adapter never imports its provider
SDK at load time. test_openai, for instance, asserts openai is absent before and
after importing promptetheus.adapters.openai; if an earlier dspy test already
loaded openai, that precondition misfires through no fault of the adapter.

This autouse fixture undoes that leak. It targets only the provider SDK
top-level packages that other adapter tests assert are absent (openai and
anthropic), and only removes them if they were not already imported when the
test began. It deliberately does not touch any other module, so frameworks that
cache partially-initialized submodules during import are left intact, and the
import-safety preconditions read true regardless of test order without
weakening any assertion.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest

# Provider SDKs whose absence other adapter tests assert as their import-safety
# precondition. Lib-verified framework tests transitively import these, so we
# unload any that a test newly introduced to keep that precondition faithful.
_PROVIDER_SDKS = ("openai", "anthropic")


@pytest.fixture(autouse=True)
def _isolate_provider_sdks() -> Iterator[None]:
    present_before = {name for name in _PROVIDER_SDKS if name in sys.modules}
    try:
        yield
    finally:
        for name in _PROVIDER_SDKS:
            if name in present_before:
                continue
            for mod in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
                del sys.modules[mod]
