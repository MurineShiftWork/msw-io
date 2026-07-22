"""Tests for the optional, non-fatal metadata-subtree validation registry."""

from __future__ import annotations

import pytest

from murineshiftwork.namespace import metadata_registry as reg


class _ProbesAddon:
    """A conforming addon: warns when a probe lacks an id."""

    subtree = "probes"
    schema_version = 1

    def validate(self, block: object) -> list[str]:
        warnings: list[str] = []
        for i, p in enumerate((block or {}).get("probes", [])):
            if "id" not in p:
                warnings.append(f"probe[{i}] missing id")
        return warnings


class _RaisingAddon:
    subtree = "opto"
    schema_version = 1

    def validate(self, block: object) -> list[str]:
        raise RuntimeError("boom")


@pytest.fixture
def registered(monkeypatch):
    """Inject addons directly into the discovery cache (no entry points needed)."""
    def _install(*addons):
        reg.reset_cache()
        monkeypatch.setattr(reg, "_discover", lambda: {a.subtree: a for a in addons})
    yield _install
    reg.reset_cache()


def test_none_and_empty_metadata_are_noops(registered):
    registered(_ProbesAddon())
    assert reg.validate_metadata(None) == {}
    assert reg.validate_metadata({}) == {}


def test_valid_subtree_yields_no_warnings(registered):
    registered(_ProbesAddon())
    md = {"probes": {"probes": [{"id": "a"}, {"id": "b"}]}}
    assert reg.validate_metadata(md) == {}


def test_invalid_subtree_yields_warnings(registered):
    registered(_ProbesAddon())
    md = {"probes": {"probes": [{"id": "a"}, {"serial": "x"}]}}
    assert reg.validate_metadata(md) == {"probes": ["probe[1] missing id"]}


def test_unregistered_subtree_is_ignored(registered):
    registered(_ProbesAddon())
    # metadata.reward has no addon -> passes through, no error
    assert reg.validate_metadata({"reward": {"type": "water"}}) == {}


def test_registered_but_absent_subtree_is_skipped(registered):
    registered(_ProbesAddon())
    assert reg.validate_metadata({"other": 1}) == {}


def test_raising_addon_is_caught_not_fatal(registered):
    registered(_RaisingAddon())
    out = reg.validate_metadata({"opto": {"x": 1}})
    assert "opto" in out and "raised" in out["opto"][0]


def test_registered_subtrees_lists_names(registered):
    registered(_ProbesAddon(), _RaisingAddon())
    assert reg.registered_subtrees() == ["opto", "probes"]


def test_conforming_addon_satisfies_protocol():
    # the duck-type / Protocol gate accepts a conforming object
    assert reg._is_addon(_ProbesAddon())
    assert not reg._is_addon(object())
