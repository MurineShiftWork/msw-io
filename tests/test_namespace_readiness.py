"""Namespace package readiness check for msw-io.

msw-io contributes murineshiftwork.io, murineshiftwork.namespace, and
murineshiftwork.readers as a namespace package (PEP 420). This means the
murineshiftwork/ root must never contain an __init__.py, otherwise Python
would treat it as a regular package and block other namespace contributors
(murineshiftwork main, future msw-tasks-*, msw-agent) from installing into
the same top-level namespace.
"""

from pathlib import Path

import murineshiftwork.io


def test_namespace_root_has_no_init():
    """murineshiftwork/ root contributed by msw-io must not have __init__.py."""
    pkg_root = Path(list(murineshiftwork.io.__path__)[0]).parent
    init = pkg_root / "__init__.py"
    assert not init.exists(), (
        f"{init} exists. msw-io must not place an __init__.py at the "
        f"murineshiftwork/ root or it will break the namespace package split."
    )
