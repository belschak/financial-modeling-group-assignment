"""Adapter between the app UI and the shared engine (fm_backtest.py, identical to the notebook's).

Only this file knows the engine's API. It maps the sidebar choices to engine CONFIG keys and
collects what the page shows. No calculation is re-implemented here: every number comes from
fm_backtest (run_backtest, metrics_table, turnover_stats, breakeven_cost, cost_sensitivity,
annual_returns, sri_priips, monte_carlo).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import fm_backtest as fb

_D = fb.get_config()
STRATEGY = _D["strategy_name"]
ASSET_NAMES = dict(_D["asset_names"])
CASH = fb.CASH

# Benchmarks: the app works with the engine's display labels, the CONFIG with keys.
_KEYS = list(_D["benchmarks"])
LABEL = {k: fb.bench_label(_D, k) for k in _KEYS}
KEY = {v: k for k, v in LABEL.items()}
BENCH_B1, BENCH_B2 = (LABEL[k] for k in _KEYS[:2])     # "B1 Equal weight 1/n", "B2 Classic 60/40"
KEY_B1, KEY_B2 = _KEYS[:2]

# Engine features, switched on only when the shared engine provides them.
HEDGE_KEY = next((k for k in ("hedge_tickers", "hedged_tickers", "hedge_bonds") if k in _D), None)
HAS_SRI = callable(getattr(fb, "sri_priips", None))
SMA_RANGE = (6, 12)
SMA_KEY = "sma_window" if "sma_window" in _D else "sma_months"

# Prospectus / notebook defaults, as UI values.
DEFAULTS = dict(
    sma_window=int(_D[SMA_KEY]),
    signal_lag=int(_D["signal_lag"]),
    rebalance=_D["rebalance"],
    cost_bps=int(round(_D["cost_bps"])),
    start=pd.Timestamp(_D["start"]).strftime("%Y-%m"),
    end=pd.Timestamp(_D["end"]).strftime("%Y-%m"),
    base_ccy=_D["base_ccy"],
    tickers=tuple(_D["tickers"]),
    primary_benchmark=LABEL[_D["primary_benchmark"]],
)
if HEDGE_KEY:
    DEFAULTS["hedge"] = bool(_D[HEDGE_KEY])


def build_config(ui: dict) -> dict:
    """UI choices -> engine CONFIG via fm_backtest.get_config (unknown keys would raise)."""
    tickers = [t for t in _D["tickers"] if t in ui["tickers"]]
    extra = {}
    if HEDGE_KEY and "hedge" in ui:
        if isinstance(_D[HEDGE_KEY], list):
            extra[HEDGE_KEY] = list(_D[HEDGE_KEY]) if ui["hedge"] else []
        else:
            extra[HEDGE_KEY] = bool(ui["hedge"])
    return fb.get_config(
        **extra,
        tickers=tickers,
        **{SMA_KEY: int(ui["sma_window"])},
        signal_lag=int(ui["signal_lag"]),
        rebalance=ui["rebalance"],
        cost_bps=float(ui["cost_bps"]),
        start=pd.Timestamp(ui["start"] + "-01").strftime("%Y-%m-%d"),
        end=(pd.Timestamp(ui["end"] + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"),
        base_ccy=ui["base_ccy"],
        primary_benchmark=KEY[ui["primary_benchmark"]],
    )


@dataclass
class Result:
    cfg: dict
    bt: dict                     # the engine's full backtest output
    index: pd.DatetimeIndex
    strat_net: pd.Series
    strat_gross: pd.Series
    bench_net: dict              # label -> monthly net returns
    held: pd.DataFrame
    metrics: pd.DataFrame        # rows = metric keys, columns = STRATEGY, "STRATEGY (before costs)", B1, B2 labels
    primary: str                 # label of the benchmark used for alpha, beta, IR
    turnover: dict
    breakeven_bps: float | None          # on CAGR
    breakeven_sharpe_bps: float | None   # on Sharpe
    cost_grid: pd.DataFrame      # growth of 1 by the end of the sample, by one-way cost (bps)
    annual: pd.DataFrame         # calendar-year returns (net), full years only
    sri: dict | None             # indicative PRIIPs SRI: {"sri": int, "strategy": {...}, "b1": {...}}


def run(ui: dict, data: dict) -> Result:
    cfg = build_config(ui)
    bt = fb.run_backtest(cfg, data)
    prim_key = bt["primary"]
    tab = fb.metrics_table(bt, prim_key).T
    tab.columns = [STRATEGY, f"{STRATEGY} (before costs)", *[b.name for b in bt["benchmarks"].values()]]
    bench = bt["benchmarks"][prim_key]
    pays = cfg.get("benchmark_costs", True)
    nets = {b.name: b.net for b in bt["benchmarks"].values()}
    annual = fb.annual_returns({"Strategy": bt["strategy"].net, **nets})
    full_years = [y for y in annual.index if (bt["index"].year == y).sum() == 12]
    return Result(
        cfg=cfg,
        bt=bt,
        index=bt["index"],
        strat_net=bt["strategy"].net,
        strat_gross=bt["strategy"].gross,
        bench_net=nets,
        held=bt["strategy"].held,
        metrics=tab,
        primary=LABEL[prim_key],
        turnover=fb.turnover_stats(bt["strategy"]),
        breakeven_bps=fb.breakeven_cost(bt["strategy"], bench, bt["rf"], on="cagr", bench_pays=pays),
        breakeven_sharpe_bps=fb.breakeven_cost(bt["strategy"], bench, bt["rf"], on="sharpe", bench_pays=pays),
        cost_grid=fb.cost_sensitivity(bt, max_bps=100, step=5),
        annual=annual.loc[full_years],
        sri=_sri(cfg, bt),
    )


def _sri(cfg: dict, bt: dict) -> dict | None:
    """Spec S5: the higher of the strategy's and the unfiltered 1/n mix's class (as the notebook does)."""
    if not HAS_SRI or KEY_B1 not in bt["benchmarks"]:
        return None
    rhp = int(cfg.get("sri_rhp_years", 10))
    s = fb.sri_priips(bt["strategy"].net, rhp)
    b = fb.sri_priips(bt["benchmarks"][KEY_B1].net, rhp)
    return dict(sri=max(s["sri_class"], b["sri_class"]), strategy=s, b1=b)


def monte_carlo(res: Result) -> dict:
    """Engine Monte Carlo: strategy and B2 resampled jointly on the same months (+ haircut variant)."""
    return fb.monte_carlo(res.cfg, res.bt, against=KEY_B2)


def wealth(r: pd.Series) -> pd.Series:
    return fb.wealth_index(r)


def drawdown(r: pd.Series) -> pd.Series:
    return fb.drawdown(r)


# ---------------------------------------------------------------- level-2 views (compose engine outputs only)
# Crisis windows: the engine's own list plus the 2025 tariff shock (an app display window, not used in the notebook).
CRISES = [tuple(w) for w in _D.get("crisis_windows", [])] + [("2025-02-01", "2025-04-30", "Feb-Apr 2025 tariff shock")]


def crisis_view(res: Result, start: str, end: str, pad_months: int = 3) -> dict:
    """Paths rebased to 1 just before the window (with context months either side), the window's cumulative
    returns, which sleeves were invested each month, and the engine's list of exits/re-entries."""
    s0 = pd.Timestamp(start) + pd.offsets.MonthEnd(0)
    s1 = pd.Timestamp(end) + pd.offsets.MonthEnd(0)
    ix = res.index
    lo = ix[max(0, ix.searchsorted(s0) - pad_months)]
    hi = ix[min(len(ix) - 1, ix.searchsorted(s1) + pad_months)]
    series = {"Strategy": res.strat_net, **res.bench_net}
    paths = {k: fb.wealth_index(v.loc[lo:hi]) for k, v in series.items()}
    inside = ix[(ix >= s0) & (ix <= s1)]
    window_ret = {k: float((1 + v.loc[inside]).prod() - 1) for k, v in series.items()} if len(inside) else {}
    sig = res.bt.get("signals")
    signals = sig.loc[lo:hi] if sig is not None else None
    events = fb.signal_events(res.bt, str(lo.date()), str(hi.date())) if sig is not None else []
    return dict(paths=paths, window=(s0, s1), returns=window_ret, signals=signals, events=events,
                in_sample=len(inside) > 0)


def earliest_start(data: dict, tickers, sma: int, lag: int) -> pd.Timestamp:
    """First return month for which every selected fund has a full moving-average window before the decision."""
    youngest = max(data["prices_usd"][t].first_valid_index() for t in tickers)
    return youngest + pd.offsets.MonthEnd(int(sma) - 1 + int(lag))


def sma_stability(ui: dict, data: dict) -> dict:
    """All windows from the engine's stability list on ONE common sample (the longest window needs the most
    history), other settings as chosen. A check that the result does not hinge on 10, not a search for the best."""
    windows = list(_D.get("sma_stability", [6, 8, 10, 12]))
    first = earliest_start(data, ui["tickers"], max(windows), ui["signal_lag"])
    start = max(pd.Timestamp(ui["start"] + "-01") + pd.offsets.MonthEnd(0), first,
                pd.Timestamp(_D.get("sma_stability_start", ui["start"] + "-01")) + pd.offsets.MonthEnd(0))
    out = {}
    for n in windows:
        r = run({**ui, "sma_window": n, "start": start.strftime("%Y-%m")}, data)
        out[n] = r
    return dict(start=start, results=out)


def monte_carlo_haircut(res: Result) -> dict:
    """The engine's haircut variant (excess return over cash halved, McLean-Pontiff 2016) with full bands.
    Same transformation and call as fm_backtest.monte_carlo; a test checks its summary equals the engine's."""
    c = res.cfg
    b = res.bt["benchmarks"][KEY_B2]
    df = pd.DataFrame({"Strategy": res.bt["strategy"].net, b.name: b.net})
    excess_mean = df.sub(res.bt["rf"], axis=0).mean()
    return fb.block_bootstrap(df - 0.5 * excess_mean, n_paths=c["mc_paths"], n_months=c["mc_years"] * fb.PERIODS,
                              block=c["mc_block"], initial=c["mc_initial"], seed=c["mc_seed"])
