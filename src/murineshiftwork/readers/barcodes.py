"""Barcode settings of a session, and decoding an edge stream with them.

A barcode's length is set per setup and task (a setup recorded on video may send 100 ms
bits, the default is 35 ms), so a decoder needs the settings the session sent with. They are
looked up in this order:

1. ``barcodes:`` in session.yaml, written by the rig when a barcode is first sent;
2. the task settings: the sequence task's ``barcode:`` block, or the flat
   ``barcode_*`` keys other tasks use;
3. the ttl-barcoder defaults, with a warning.

Decoding finds each barcode by its configured length (``BarcodeTTL.find_barcodes``),
never by a silence between barcodes: a run of equal 100 ms bits is a longer silence
than any fixed gap that also separates short barcodes.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Sequence
from typing import TypeAlias

from ttl_barcoder.core.barcode_ttl import BarcodeTTL
from ttl_barcoder.core.config import BarcodeConfig

log = logging.getLogger(__name__)

_FIELDS = ("barcode_bits", "bit_duration_ms", "init_duration_ms", "tolerance")
# sequence task: barcode: {bits, bit_duration_ms, init_duration_ms, tolerance}
_NESTED = {
    "bits": "barcode_bits",
    "bit_duration_ms": "bit_duration_ms",
    "init_duration_ms": "init_duration_ms",
    "tolerance": "tolerance",
}
# other tasks: flat keys in the task settings
_FLAT = {
    "barcode_bits": "barcode_bits",
    "barcode_bit_duration_ms": "bit_duration_ms",
    "barcode_init_duration_ms": "init_duration_ms",
    "barcode_tolerance": "tolerance",
}

BarcodeConfigs: TypeAlias = BarcodeConfig | Sequence[BarcodeConfig]


def _from_keys(values: dict, keys: dict[str, str]) -> BarcodeConfig | None:
    fields = {keys[k]: v for k, v in values.items() if k in keys and v is not None}
    return BarcodeConfig(**fields) if fields else None


def session_barcode_configs(
    session_data: dict | str | os.PathLike,
) -> tuple[list[BarcodeConfig], str]:
    """The barcode settings a session sent with, and where they came from.

    ``session_data`` is the dict from ``read_session_data``, or the session
    directory, which is then read with it. The source is ``"session"``,
    ``"task_settings"`` or ``"default"``.
    """
    if isinstance(session_data, (str, os.PathLike)):
        # imported here: the session reader is heavy and analysis code that
        # already holds the dict should not need it
        from murineshiftwork.readers.session import read_session_data

        session_data = read_session_data(session_data)
    if not isinstance(session_data, dict):
        raise TypeError(
            "session_data must be the dict from read_session_data or a session "
            f"directory, not {type(session_data).__name__}"
        )
    recorded = session_data.get("settings.barcodes") or []
    configs = [
        BarcodeConfig(**{k: r[k] for k in _FIELDS if k in r})
        for r in recorded
        if isinstance(r, dict)
    ]
    if configs:
        return _unique(configs), "session"

    task = session_data.get("settings.task") or {}
    nested = task.get("barcode")
    config = (
        _from_keys(nested, _NESTED) if isinstance(nested, dict) else None
    ) or _from_keys(task, _FLAT)
    if config is not None:
        return [config], "task_settings"

    log.warning(
        "No barcode settings in the session or its task settings: decoding with the "
        "ttl-barcoder defaults (%s)",
        BarcodeConfig.default(),
    )
    return [BarcodeConfig.default()], "default"


def _unique(configs: Iterable[BarcodeConfig]) -> list[BarcodeConfig]:
    out: list[BarcodeConfig] = []
    for c in configs:
        if c not in out:
            out.append(c)
    return out


def as_config_list(configs: BarcodeConfigs | None) -> list[BarcodeConfig]:
    """One config or several as a list; None is the defaults."""
    if configs is None:
        return [BarcodeConfig.default()]
    if isinstance(configs, BarcodeConfig):
        return [configs]
    return _unique(configs)


def decode_edge_stream(
    edge_times: Sequence[float],
    edge_levels: Sequence[bool],
    configs: BarcodeConfigs | None = None,
    *,
    sample_interval_s: float = 0.0,
) -> list[tuple[float, int]]:
    """``(start_s, value)`` of every barcode on one line, sorted by time.

    Each config is searched on its own (a session can send barcodes of more than one
    length); a hit that overlaps one found with an earlier config is dropped.
    Zero-length pulses are dropped first (see ``ttl_barcoder.drop_short_pulses``).
    """
    times = [float(t) for t in edge_times]
    levels = [bool(v) for v in edge_levels]
    found: list[tuple[float, float, int]] = []
    for config in as_config_list(configs):
        for hit in BarcodeTTL(config).find_barcodes(
            times, levels, sample_interval_s=sample_interval_s
        ):
            if not any(
                hit.start_s < end and start < hit.end_s for start, end, _ in found
            ):
                found.append((hit.start_s, hit.end_s, hit.value))
    return [(start, value) for start, _, value in sorted(found)]
