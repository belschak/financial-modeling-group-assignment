"""Offline checks of the app's calculations on the stored snapshot (= the notebook run's own inputs)."""
import json
import math

import numpy as np
import pandas as pd
import pytest

import core
import data_layer as dl
import fm_lean as fl
from conftest import repo_results_json

RJ = json.loads(repo_results_json().read_text(encoding="utf-8"))
TOL = 1e-6   # the snapshot stores inputs with 10 significant digits
KEYS = {"Strategy": "strategy", "Strategy gross": "strategy_gross", "B1": "B1_equal_weight", "B2": "B2_60_40"}
TABLE1 = ["ann_return", "cagr", "ann_vol", "sharpe", "alpha_ann", "alpha_t", "information_ratio_regression",
          "information_ratio", "beta", "tracking_error", "max_drawdown", "worst_12m", "final_wealth"]


@pytest.fixture(scope="module")
def data():
    return dl.load_snapshot()


@pytest.fixture(scope="module")
def bt(data):
    return core.run(core.DEFAULTS, data)


def test_defaults_reproduce_prospectus_table1(bt):
    assert len(bt["net"]) == RJ["meta"]["n_months"] == 228 and bt["net"].index[0] == pd.Timestamp("2007-01-31")
    for col, key in KEYS.items():
        for k in TABLE1:
            want = RJ["portfolios"][key][k]
            if want is not None:
                assert abs(bt["table"].loc[col, k] - want) < TOL, (col, k, bt["table"].loc[col, k], want)


def test_next_day_costs_and_monte_carlo_match_notebook(data, bt):
    nd = core.run({**core.DEFAULTS, "next_day": True}, data)["table"].loc["Strategy"]
    for k in ("sharpe", "max_drawdown", "cagr"):
        assert abs(nd[k] - RJ["prospectus_numbers"]["headline_next_day"][k]) < TOL, k
    cs = core.costs(bt, "B1")
    assert abs(cs["turnover_pa"] - RJ["costs"]["strategy"]["turnover_pa"]) < TOL
    assert abs(cs["cost_drag_pa"] - RJ["costs"]["strategy"]["cost_drag_pa"]) < TOL
    assert abs(cs["breakeven_cagr"] - RJ["breakeven_cost_bps"]["B1_equal_weight_cagr"]) < 1e-3
    assert abs(cs["breakeven_sharpe"] - RJ["breakeven_cost_bps"]["B1_equal_weight_sharpe"]) < 1e-3
    mc = core.monte_carlo(bt)["summary"]["Strategy"]
    assert abs(mc["p50"] / RJ["headline"]["mc_strategy_p50"] - 1) < 1e-6
    mh = core.monte_carlo(bt, haircut=True)["summary"]["Strategy"]
    assert abs(mh["p50"] / RJ["headline"]["mc_strategy_p50_haircut"] - 1) < 1e-6


def test_series_start_at_one_and_benchmark_against_itself(bt):
    for c in bt["net"].columns:
        w = fl.wealth(bt["net"][c])
        assert w.iloc[0] == 1.0 and w.index[0] == bt["net"].index[0] - pd.offsets.MonthEnd(1)
    b1 = bt["table"].loc["B1"]
    assert math.isclose(b1["beta"], 1.0, abs_tol=1e-12) and abs(b1["alpha_ann"]) < 1e-12
    assert np.isnan(b1["information_ratio"])   # no active return against itself


def test_every_user_setting_runs_and_costs_lower_sharpe(data, bt):
    base = bt["table"].loc["Strategy", "sharpe"]
    for v in (dict(cost_bps=50), dict(sma=6), dict(sma=12, start="2007-02"), dict(lag=2), dict(next_day=True), dict(start="2012-01"),
              dict(tickers=("SPY", "IEF")), dict(bench="B2")):
        t = core.run({**core.DEFAULTS, **v}, data)["table"]
        assert np.isfinite(t.loc["Strategy", "sharpe"]), v
    assert core.run({**core.DEFAULTS, "cost_bps": 50}, data)["table"].loc["Strategy", "sharpe"] < base
    t2 = core.run({**core.DEFAULTS, "bench": "B2"}, data)["table"].loc["Strategy"]
    for k in ("beta", "alpha_ann", "information_ratio_regression", "information_ratio"):
        assert abs(t2[k] - RJ["relative_to_second_benchmark"]["strategy"][k]) < TOL, k


def test_defaults_have_enough_history_and_end_dec_2025(data):
    assert core.earliest_start(data, fl.TICKERS, 10, 1) <= core.month_end(core.DEFAULTS["start"])
    assert dl.last_complete_month(data) == pd.Timestamp("2025-12-31")
