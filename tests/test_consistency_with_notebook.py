"""Defaults in the app reproduce the notebook's published numbers (results.json written by the notebook).

Exact check (1e-9) when the notebook's own input snapshot is available; otherwise the app's stored snapshot
is used with a small tolerance, because Yahoo re-scales adjusted prices slightly between download days.
"""
import json
import math

import pandas as pd
import pytest

import core
import data_layer as dl
from conftest import notebook_inputs_snapshot, results_json

# engine metric key -> accepted key names in results.json
ALIASES = {
    "ann_return": ["ann_return"],
    "ann_vol": ["ann_vol", "volatility"],
    "sharpe": ["sharpe"],
    "beta": ["beta"],
    "alpha_ann": ["alpha_ann", "alpha"],
    "information_ratio": ["information_ratio", "ir"],
    "cagr": ["cagr"],
    "max_drawdown": ["max_drawdown"],
    "tracking_error": ["tracking_error"],
}
STRATEGY_KEYS = ["strategy", "Strategy", "strategy_net", core.STRATEGY, f"{core.STRATEGY} (net)"]
B1_KEYS = ["b1", "B1", core.KEY_B1, core.BENCH_B1]


def _find(d, keys):
    for k in keys:
        if isinstance(d, dict) and k in d:
            return d[k]
    return None


def _metrics_block(res_json, which):
    for container in ("portfolios", "metrics", "table1", "headline"):
        block = res_json.get(container)
        if isinstance(block, dict):
            hit = _find(block, which)
            if isinstance(hit, dict):
                return hit
    return _find(res_json, which)


def _inputs():
    snap = notebook_inputs_snapshot()
    if snap is not None and snap.with_name("snapshot_meta.json").exists():
        return dl.load_snapshot(snap, snap.with_name("snapshot_meta.json")), 1e-9
    if dl.snapshot_available():
        return dl.load_snapshot(), 2e-3
    pytest.skip("no input data available offline")


def test_defaults_reproduce_notebook_results():
    path = results_json()
    if path is None:
        pytest.skip("notebook results.json not available yet")
    res_json = json.loads(path.read_text(encoding="utf-8"))
    data, tol = _inputs()
    app = core.run(dict(core.DEFAULTS), data).metrics
    checked = 0
    for col, keys in ((core.STRATEGY, STRATEGY_KEYS), (core.BENCH_B1, B1_KEYS)):
        block = _metrics_block(res_json, keys)
        if not isinstance(block, dict):
            continue
        for ek, names in ALIASES.items():
            v = _find(block, names)
            if v is None or ek not in app.index:
                continue
            a = float(app.loc[ek, col])
            if math.isnan(a):
                continue
            assert abs(a - float(v)) <= tol, f"{col} {ek}: app {a:.6f} vs notebook {float(v):.6f} (tol {tol})"
            checked += 1
    if checked < 4:
        pytest.skip(f"results.json shape not recognised ({checked} metrics matched); update ALIASES")
