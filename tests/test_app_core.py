"""App adapter checks that need no network (synthetic data + the stored snapshot)."""
import math

import numpy as np
import pandas as pd
import pytest

import core
import data_layer as dl
import fm_backtest as fb


def test_app_defaults_are_exactly_the_notebook_config():
    assert core.build_config(core.DEFAULTS) == fb.get_config()


def test_runs_on_synthetic_data_and_series_start_at_one():
    data = fb.synthetic_data()
    res = core.run(dict(core.DEFAULTS), data)
    for r in [res.strat_net, *res.bench_net.values()]:
        w = core.wealth(r)
        assert w.iloc[0] == 1.0 and w.index[0] == res.index[0] - pd.offsets.MonthEnd(1)
    assert np.allclose(res.held.sum(axis=1), 1.0)
    assert (res.held >= -1e-12).all().all()


def test_benchmark_against_itself():
    res = core.run(dict(core.DEFAULTS), fb.synthetic_data())
    b1 = res.metrics[core.BENCH_B1]
    assert math.isclose(b1["beta"], 1.0, abs_tol=1e-12)
    assert abs(b1["alpha_ann"]) < 1e-12 and abs(b1["tracking_error"]) < 1e-12


def test_every_user_setting_changes_or_runs():
    data = fb.synthetic_data()
    base = core.run(dict(core.DEFAULTS), data).metrics.loc["sharpe", core.STRATEGY]
    variants = [dict(cost_bps=50), dict(sma_window=6), dict(signal_lag=2), dict(rebalance="Q"),
                dict(base_ccy="USD"), dict(start="2012-01"), dict(tickers=("SPY", "IEF")),
                dict(primary_benchmark=core.BENCH_B2), dict(hedge=False)]
    for v in variants:
        r = core.run({**core.DEFAULTS, **v}, data)
        assert np.isfinite(r.metrics.loc["sharpe", core.STRATEGY]), v
    assert core.run({**core.DEFAULTS, "cost_bps": 50}, data).metrics.loc["sharpe", core.STRATEGY] < base


def test_b1_follows_selected_assets():
    cfg = core.build_config({**core.DEFAULTS, "tickers": ("SPY", "EFA", "IEF")})
    assert fb.benchmark_weights(cfg, core.KEY_B1) == {"SPY": 1 / 3, "EFA": 1 / 3, "IEF": 1 / 3}


def test_engine_features_detected():
    assert core.HEDGE_KEY and core.HAS_SRI
    cfg = core.build_config({**core.DEFAULTS, "hedge": False})
    assert not cfg[core.HEDGE_KEY]
    res = core.run(dict(core.DEFAULTS), fb.synthetic_data())
    assert 1 <= res.sri["sri"] <= 7
    mc = core.monte_carlo(res)
    assert set(mc["bands"]) == {"Strategy", core.BENCH_B2}


@pytest.mark.skipif(not dl.snapshot_available(), reason="no stored snapshot")
def test_snapshot_round_trip_runs():
    res = core.run(dict(core.DEFAULTS), dl.load_snapshot())
    assert len(res.index) == 228 and res.index[0] == pd.Timestamp("2007-01-31")
    assert res.annual.index.min() == 2007 and res.annual.index.max() == 2025


def test_haircut_bands_match_engine_haircut_summary():
    res = core.run(dict(core.DEFAULTS), fb.synthetic_data())
    eng = core.monte_carlo(res)["haircut_summary"]
    mine = core.monte_carlo_haircut(res)["summary"]
    for k in ("Strategy", core.BENCH_B2):
        for q in ("p10", "p50", "p90"):
            assert abs(eng[k][q] - mine[k][q]) < 1e-9


def test_crisis_view_and_sma_stability():
    data = fb.synthetic_data()
    res = core.run(dict(core.DEFAULTS), data)
    cv = core.crisis_view(res, "2020-02-01", "2020-03-31")
    assert cv["in_sample"] and set(cv["returns"]) == {"Strategy", core.BENCH_B1, core.BENCH_B2}
    assert all(abs(p.iloc[0] - 1.0) < 1e-12 for p in cv["paths"].values())
    st = core.sma_stability(dict(core.DEFAULTS), data)
    assert set(st["results"]) == {6, 8, 10, 12}
    assert len({tuple(r.index) for r in st["results"].values()}) == 1  # one common sample


def test_sma_stability_matches_engine_robustness():
    data = fb.synthetic_data()
    res = core.run(dict(core.DEFAULTS), data)
    eng = fb.robustness(res.cfg, data, res.bt)["sma_stability"]
    mine = core.sma_stability(dict(core.DEFAULTS), data)["results"]
    for n, r in mine.items():
        assert abs(eng.loc[f"{n} months", "sharpe"] - r.metrics.loc["sharpe", core.STRATEGY]) < 1e-9
