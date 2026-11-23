"""Glue between the page and fm_lean.py, the notebook's own module (imported unchanged).

Every number comes from fm_lean: backtest, table, at_cost, breakeven, wealth, drawdown, rolling,
calendar_years, monte_carlo. This file only turns the sidebar choices into those calls.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

import fm_lean as fl

STRATEGY = "BP Trend-Guarded Multi-Asset"
NAMES = {"SPY": "US equity", "EFA": "Developed ex-US equity", "IEF": "US Treasuries 7-10y",
         "VNQ": "US real estate", "DBC": "Commodities"}
BENCH = {"B1": "B1 Equal weight 1/n", "B2": "B2 Classic 60/40"}
CLIENT_DD_TARGET, CLIENT_DD_CEILING = 0.10, 0.20  # client's worst-fall target and hard ceiling (prospectus, D2)
# Prospectus Table 1 = notebook defaults: 10-month average, lag 1 at the month-end close, 10 bps, 2007-2025, vs B1.
DEFAULTS = dict(sma=10, lag=1, next_day=False, cost_bps=10, start="2007-01", end="2025-12",
                tickers=tuple(fl.TICKERS), bench="B1")
SHA = hashlib.sha256(Path(fl.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def month_end(ym: str) -> pd.Timestamp:
    return pd.Timestamp(ym + "-01") + pd.offsets.MonthEnd(0)


def earliest_start(d: dict, tickers, sma: int, lag: int) -> pd.Timestamp:
    """First month the rule can trade: the youngest fund needs a full average before the first decision."""
    youngest = max(d["px"][t].first_valid_index() for t in tickers)
    return youngest + pd.offsets.MonthEnd(sma - 1 + lag)


def run(ui: dict, d: dict) -> dict:
    """The backtest for the sidebar choices and its Table 1 (all portfolios against the chosen benchmark)."""
    bt = fl.backtest(d, month_end(ui["start"]), month_end(ui["end"]), list(ui["tickers"]), int(ui["sma"]),
                     int(ui["lag"]), float(ui["cost_bps"]), bool(ui["next_day"]))
    bt["table"] = fl.table(bt, against=ui["bench"])
    return bt


def costs(bt: dict, bench: str) -> dict:
    """Turnover, cost drag and breakeven costs, as in the notebook's cost section."""
    n, years = bt["net"], len(bt["net"]) / 12
    cagr = lambda r: (1 + r).prod() ** (12 / len(r)) - 1
    grid = pd.DataFrame({c: {"strategy": (1 + fl.at_cost(bt, "Strategy", c)).prod(),
                             "benchmark": (1 + fl.at_cost(bt, bench, c)).prod()} for c in range(0, 101, 5)}).T
    return dict(turnover_pa=bt["parts"]["Strategy"]["turnover"].sum() / years,
                cost_drag_pa=cagr(n["Strategy gross"]) - cagr(n["Strategy"]),
                breakeven_cagr=fl.breakeven(bt, bench, "cagr"), breakeven_sharpe=fl.breakeven(bt, bench, "sharpe"),
                grid=grid)


def monte_carlo(bt: dict, haircut: bool = False) -> dict:
    """Notebook section 9: strategy and B2 on the same random months; the haircut variant halves the
    strategy's average return above cash (McLean and Pontiff 2016)."""
    mc_in = pd.DataFrame({"Strategy": bt["net"]["Strategy"], BENCH["B2"]: bt["net"]["B2"]})
    if haircut:
        mc_in["Strategy"] -= 0.5 * (bt["net"]["Strategy"] - bt["rf"]).mean()
    return fl.monte_carlo(mc_in)
