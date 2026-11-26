"""Glue between the page and fm_lean.py, the notebook's own module (imported unchanged).

Every number comes from fm_lean: backtest, table, at_cost, breakeven, cost_table, wealth, drawdown, rolling,
calendar_years, monte_carlo. This file only turns the sidebar choices into those calls, and slices the net returns
the way the notebook does for its crisis and bull-market tables (same formulas, same windows).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

import fm_lean as fl

STRATEGY = "Trend-Guarded Multi-Asset"
NAMES = {"SPY": "US equity", "EFA": "Developed ex-US equity", "IEF": "US Treasuries 7-10y", "XLU": "US utilities",
         "DBC": "Commodities", "GLD": "Gold"}
BENCH = {"B1": "B1 Same mix, always invested", "B2": "B2 Classic 60/40", "B3": "B3 MSCI World"}
SHORT = {"Strategy": "Strategy", "B1": "B1 Same mix", "B2": "B2 60/40", "B3": "B3 MSCI World"}
PORTS = ("Strategy", "B1", "B2", "B3")
CLIENT_DD_TARGET, CLIENT_DD_CEILING = 0.10, 0.20  # client's worst-fall target and hard ceiling (prospectus, D2)
# Prospectus Table 1 = notebook defaults: 10-month average, lag 1 at the month-end close, 10 bps, 2005-2025, vs B1.
DEFAULTS = dict(sma=10, lag=1, next_day=False, cost_bps=10, start="2005-01", end="2025-12",
                tickers=tuple(fl.TICKERS), bench="B1")
FIRST_MONTH = "2005-01"   # the notebook's sample start; the stand-ins (DBC <- S&P GSCI, GLD <- gold futures) as disclosed
# The notebook's windows (section 7 crises, section 8 bull markets): first and last month, both included.
CRISES = [("Financial crisis", "2007-11", "2009-02"), ("Euro crisis", "2011-05", "2011-09"),
          ("Covid crash", "2020-02", "2020-03"), ("2022 inflation shock", "2022-01", "2022-12")]
BULLS = [("From the financial-crisis low to Covid", "2009-03", "2020-01"), ("2023-2025 rally", "2023-01", "2025-12")]
SHA = hashlib.sha256(Path(fl.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def month_end(ym: str) -> pd.Timestamp:
    return pd.Timestamp(ym + "-01") + pd.offsets.MonthEnd(0)


def weights(tickers) -> dict:
    """Target weights of the selected sleeves: the notebook's WEIGHTS unchanged when all six are selected, otherwise
    the selected sleeves keep their proportions and are scaled up to 100%."""
    tickers = [t for t in fl.TICKERS if t in tickers]
    if tickers == fl.TICKERS:
        return dict(fl.WEIGHTS)
    total = sum(fl.WEIGHTS[t] for t in tickers)
    return {t: fl.WEIGHTS[t] / total for t in tickers}


def earliest_start(d: dict, tickers, sma: int, lag: int) -> pd.Timestamp:
    """First month the rule can trade: the youngest series needs a full average before the first decision."""
    youngest = max(d["px"][t].first_valid_index() for t in tickers)
    return max(youngest + pd.offsets.MonthEnd(sma - 1 + lag), month_end(FIRST_MONTH))


def run(ui: dict, d: dict) -> dict:
    """The backtest for the sidebar choices and its Table 1 (all portfolios against the chosen benchmark)."""
    bt = fl.backtest(d, month_end(ui["start"]), month_end(ui["end"]), weights(ui["tickers"]), int(ui["sma"]),
                     int(ui["lag"]), float(ui["cost_bps"]), bool(ui["next_day"]))
    bt["table"] = fl.table(bt, against=ui["bench"])
    return bt


def windows(net: pd.DataFrame, spans, annualise: bool) -> pd.DataFrame:
    """Return of each portfolio over each window inside the sample: total (crises, notebook section 7) or compound
    a year (bull markets, section 8). Windows not fully inside the backtest period are left out."""
    first, last = f"{net.index[0]:%Y-%m}", f"{net.index[-1]:%Y-%m}"
    rows = {}
    for name, a, b in spans:
        if a < first or b > last:
            continue
        x = net.loc[a:b]
        tot = (1 + x[list(PORTS)]).prod()
        rows[name] = dict(start=a, end=b, months=len(x),
                          **(tot ** (12 / len(x)) - 1 if annualise else tot - 1).to_dict())
    return pd.DataFrame(rows).T


def crises(bt: dict) -> pd.DataFrame:
    return windows(bt["net"], CRISES, annualise=False)


def bull_markets(bt: dict) -> pd.DataFrame:
    return windows(bt["net"], BULLS, annualise=True)


def rolling_view(bt: dict, bench: str) -> dict:
    """Notebook F4: rolling 36-month Sharpe of the strategy and of the benchmark, the strategy's beta vs it."""
    net, rf = bt["net"], bt["rf"]
    ro, rb = fl.rolling(net["Strategy"], net[bench], rf), fl.rolling(net[bench], net[bench], rf)
    return dict(strategy=ro, bench=rb, share_above=float((ro["sharpe"] > rb["sharpe"].reindex(ro.index)).mean()),
                beta_min=float(ro["beta"].min()), beta_max=float(ro["beta"].max()))


def costs(bt: dict, bench: str) -> dict:
    """Turnover, cost drag and breakeven costs, as in the notebook's cost section (F5, cost table)."""
    n, years = bt["net"], len(bt["net"]) / 12
    cagr = lambda r: (1 + r).prod() ** (12 / len(r)) - 1
    grid = pd.DataFrame({k: [(1 + fl.at_cost(bt, k, c)).prod() for c in range(0, 101, 2)] for k in PORTS},
                        index=range(0, 101, 2))
    table = pd.DataFrame({c: fl.summary_row(fl.at_cost(bt, "Strategy", c), fl.at_cost(bt, bench, c), bt["rf"])
                          for c in (0, 10, 25, 50)}).T
    be = {b: {on: fl.breakeven(bt, b, on) for on in ("cagr", "sharpe")} for b in ("B1", "B2", "B3")}
    return dict(turnover_pa=bt["parts"]["Strategy"]["turnover"].sum() / years,
                bench_turnover_pa=bt["parts"][bench]["turnover"].sum() / years,
                cost_drag_pa=cagr(n["Strategy gross"]) - cagr(n["Strategy"]),
                breakeven_cagr=be[bench]["cagr"], breakeven_sharpe=be[bench]["sharpe"], breakeven=be,
                grid=grid, table=table)


MC_COLS = {"Strategy": "Strategy", "B2": BENCH["B2"], "B3": BENCH["B3"]}


def monte_carlo(bt: dict, haircut: bool = False) -> dict:
    """Notebook section 9: strategy, 60/40 and MSCI World on the same random months; the haircut variant halves the
    strategy's average return above cash (McLean and Pontiff 2016)."""
    mc_in = pd.DataFrame({lbl: bt["net"][k] for k, lbl in MC_COLS.items()})
    if haircut:
        mc_in["Strategy"] -= 0.5 * (bt["net"]["Strategy"] - bt["rf"]).mean()
    return fl.monte_carlo(mc_in)
