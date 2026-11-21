"""Adapter between the app UI and the shared engine (fm_backtest.py, identical to the notebook's).

Only this file knows the engine's API. It maps the sidebar choices to engine CONFIG keys and
collects what the page shows. No calculation is re-implemented here: every number comes from
fm_backtest (run_backtest, metrics_table, turnover_stats, breakeven_cost, cost_sensitivity).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import fm_backtest as fb

_D = fb.get_config()
STRATEGY = _D["strategy_name"]
ASSET_NAMES = dict(_D["asset_names"])
BENCH_B1, BENCH_B2 = list(_D["benchmarks"])
CASH = fb.CASH

# Prospectus / notebook defaults, as UI values.
DEFAULTS = dict(
    sma_months=int(_D["sma_months"]),
    signal_lag=int(_D["signal_lag"]),
    rebalance=_D["rebalance"],
    cost_bps=int(round(_D["cost_bps"])),
    start=pd.Timestamp(_D["start"]).strftime("%Y-%m"),
    end=pd.Timestamp(_D["end"]).strftime("%Y-%m"),
    base_ccy=_D["base_ccy"],
    tickers=tuple(_D["tickers"]),
    primary_benchmark=_D["primary_benchmark"],
)


def build_config(ui: dict) -> dict:
    """UI choices -> engine CONFIG via fm_backtest.get_config (unknown keys would raise)."""
    tickers = [t for t in _D["tickers"] if t in ui["tickers"]]
    benchmarks = fb.get_config()["benchmarks"]
    # B1 = the same assets as the strategy, static equal weights (isolates what the trend filter adds).
    benchmarks[BENCH_B1]["weights"] = {t: 1.0 / len(tickers) for t in tickers}
    return fb.get_config(
        tickers=tickers,
        sma_months=int(ui["sma_months"]),
        signal_lag=int(ui["signal_lag"]),
        rebalance=ui["rebalance"],
        cost_bps=float(ui["cost_bps"]),
        start=pd.Timestamp(ui["start"] + "-01").strftime("%Y-%m-%d"),
        end=(pd.Timestamp(ui["end"] + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"),
        base_ccy=ui["base_ccy"],
        benchmarks=benchmarks,
        primary_benchmark=ui["primary_benchmark"],
    )


@dataclass
class Result:
    cfg: dict
    index: pd.DatetimeIndex
    strat_net: pd.Series
    strat_gross: pd.Series
    bench_net: dict
    held: pd.DataFrame
    metrics: pd.DataFrame        # rows = metric keys, columns = STRATEGY, STRATEGY gross, B1, B2
    primary: str
    turnover: dict
    breakeven_bps: float | None
    cost_grid: pd.DataFrame      # CAGR by one-way cost (bps): Strategy, B1, B2


def run(ui: dict, data: dict) -> Result:
    cfg = build_config(ui)
    bt = fb.run_backtest(cfg, data)
    prim = bt["primary"]
    tab = fb.metrics_table(bt, prim).T
    tab.columns = [STRATEGY, f"{STRATEGY} (before costs)", *list(bt["benchmarks"])]
    return Result(
        cfg=cfg,
        index=bt["index"],
        strat_net=bt["strategy"].net,
        strat_gross=bt["strategy"].gross,
        bench_net={k: v.net for k, v in bt["benchmarks"].items()},
        held=bt["strategy"].held,
        metrics=tab,
        primary=prim,
        turnover=fb.turnover_stats(bt["strategy"]),
        breakeven_bps=fb.breakeven_cost(bt["strategy"], bt["benchmarks"][prim],
                                        bench_pays=cfg.get("benchmark_costs", True)),
        cost_grid=fb.cost_sensitivity(bt, max_bps=100, step=5),
    )


def wealth(r: pd.Series) -> pd.Series:
    return fb.wealth_index(r)


def drawdown(r: pd.Series) -> pd.Series:
    return fb.drawdown(r)
