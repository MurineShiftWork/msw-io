"""Barcodes are decoded with the session's settings and found by their length."""

from __future__ import annotations

import logging
import random

import numpy as np
import pandas as pd
import pytest
import yaml

pytest.importorskip("ttl_barcoder")

from ttl_barcoder.core.barcode_ttl import BarcodeTTL  # noqa: E402
from ttl_barcoder.core.config import BarcodeConfig  # noqa: E402

from murineshiftwork.readers.alignment import (  # noqa: E402
    decode_ephys_barcodes,
    decode_rpi_ttl_in,
)
from murineshiftwork.readers.barcodes import (  # noqa: E402
    decode_edge_stream,
    session_barcode_configs,
)

SLOW = BarcodeConfig(bit_duration_ms=100.0, init_duration_ms=100.0)
FAST = BarcodeConfig()


def _edges(config, values, starts):
    """Edges of several barcodes on one idle-low line."""
    ttl = BarcodeTTL(config)
    times, levels, level = [], [], False
    for value, t in zip(values, starts, strict=True):
        for target, ms in ttl.get_sequence(value):
            if target != level:
                times.append(t)
                levels.append(target)
                level = target
            t += ms / 1000.0
    return times, levels


def _values(n, seed=0):
    rng = random.Random(seed)
    # long runs of equal bits first: these are what a silence cutoff splits
    return [0, 2**37 - 1, 0b1111111111 << 13] + [rng.getrandbits(37) for _ in range(n)]


@pytest.mark.parametrize("config", [FAST, SLOW], ids=["35ms", "100ms"])
def test_ephys_line_decodes_every_barcode(config):
    values = _values(60)
    gap = config.total_duration_ms / 1000 + 0.3
    times, levels = _edges(config, values, [5.0 + i * gap for i in range(len(values))])
    events = pd.DataFrame(
        {"line": 2, "timestamps": times, "state": np.array(levels, dtype=int)}
    )
    decoded = decode_ephys_barcodes(events, barcode_bnc_line=2, barcode_config=config)
    assert [v for _, v in decoded] == values


def test_zero_length_pulses_on_the_port_are_ignored():
    values = _values(10)
    times, levels = _edges(SLOW, values, [i * 5.0 for i in range(len(values))])
    # another line on the port changed: off/on pairs at one timestamp
    for t in (0.75, 3.3, 21.05):
        i = int(np.searchsorted(times, t))
        level = levels[i - 1]
        times[i:i] = [t, t]
        levels[i:i] = [not level, level]
    assert [v for _, v in decode_edge_stream(times, levels, SLOW)] == values


def test_two_lengths_in_one_session():
    t_slow, l_slow = _edges(SLOW, [11, 2**37 - 1], [0.0, 5.0])
    t_fast, l_fast = _edges(FAST, [22, 0], [12.0, 14.0])
    decoded = decode_edge_stream(t_slow + t_fast, l_slow + l_fast, [SLOW, FAST])
    assert [v for _, v in decoded] == [11, 2**37 - 1, 22, 0]


def test_rpi_ttl_in_uses_the_given_settings(tmp_path):
    values = _values(5)
    times, levels = _edges(SLOW, values, [i * 5.0 for i in range(len(values))])
    p = tmp_path / "ttl_in.npz"
    np.savez(p, timestamp=np.array(times), data=np.array(levels, dtype=int))
    assert [v for _, v in decode_rpi_ttl_in(p, SLOW)] == values


def test_settings_from_the_session_record():
    recorded = [
        {**SLOW.model_dump(mode="json"), "bit_order": "lsb_first"},
        {**FAST.model_dump(mode="json"), "bit_order": "lsb_first"},
    ]
    configs, source = session_barcode_configs(
        {"settings.barcodes": recorded, "settings.task": {"barcode_bits": 12}}
    )
    assert (configs, source) == ([SLOW, FAST], "session")


def test_settings_from_the_sequence_barcode_block():
    task = {"barcode": {"enabled": True, "bits": 37, "bit_duration_ms": 100.0,
                        "init_duration_ms": 100.0, "tolerance": 0.25}}  # fmt: skip
    assert session_barcode_configs({"settings.task": task}) == ([SLOW], "task_settings")


def test_settings_from_flat_task_keys():
    task = {"barcode_bit_duration_ms": 100.0, "barcode_init_duration_ms": 100.0}
    assert session_barcode_configs({"settings.task": task}) == ([SLOW], "task_settings")


def test_defaults_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        configs, source = session_barcode_configs({"settings.task": {}})
    assert (configs, source) == ([BarcodeConfig.default()], "default")
    assert "No barcode settings" in caplog.text


def test_session_yaml_barcodes_reach_the_reader(tmp_path):
    from murineshiftwork.readers.session import _read_session_yaml

    record = {**SLOW.model_dump(mode="json"), "bit_order": "lsb_first"}
    path = tmp_path / "s1__20260101_000000.msw.session.yaml"
    path.write_text(yaml.safe_dump({"msw_format_version": 2, "barcodes": [record]}))
    data = _read_session_yaml(tmp_path, {})
    assert session_barcode_configs(data) == ([SLOW], "session")
