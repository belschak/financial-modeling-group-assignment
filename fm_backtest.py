# %% [engine 1/8] header, configuration
"""fm_backtest: backtest engine for the 2270 Financial Modeling group assignment (Group BP).

One self-contained module shared by the Colab notebook (written to disk with %%writefile)
and the Streamlit app (imported unchanged), so both produce identical numbers.

Conventions (stated once, used everywhere):
- Monthly data, month-end labels. Return of month t = price at end of t / price at end of t-1 - 1.
- Portfolio returns aggregate SIMPLE returns (simple returns add up across assets, log returns do not).
- A position decided with information up to the end of month t is held during month t + signal_lag.
- Weights drift with asset returns between rebalancing dates; costs are charged on the real trades.
- Annualisation: mean x12, volatility x sqrt(12), Sharpe and IR x sqrt(12), alpha x12, beta not annualised.
- Sample standard deviation (ddof=1), the pandas default used in class.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ENGINE_VERSION = "1.0.0"
CASH = "CASH"
PERIODS = 12  # monthly data: 12 periods per year

# The proposed strategy (masterplan section 3b). The group edits only this dictionary.
DEFAULT_CONFIG = dict(
    strategy_name="BP Trend-Guarded Multi-Asset",
    # Backtest proxies with long Yahoo histories (UCITS equivalents are named in the prospectus).
    tickers=["SPY", "EFA", "IEF", "VNQ", "DBC"],
    asset_names={
        "SPY": "US equity (S&P 500)",
        "EFA": "Developed ex-US equity (MSCI EAFE)",
        "IEF": "US Treasuries 7-10y",
        "VNQ": "US real estate (REITs)",
        "DBC": "Broad commodities",
    },
    rule="trend_sma",        # "trend_sma" | "fixed" | "equal" | "inverse_vol"
    weights=None,            # base weights {ticker: w}, sum 1; None = equal weights
    sma_months=10,           # Faber (2007) 10-month simple moving average, taken from the paper
    vol_window=36,           # only used by rule "inverse_vol"
    rebalance="M",           # "M" | "Q" | "A" | "none" | float threshold, e.g. 0.05
    trade_on_signal=True,    # trend rule: always trade when an asset switches between in and out
    benchmarks={
        "B1 Static 1/n": dict(weights={"SPY": 0.2, "EFA": 0.2, "IEF": 0.2, "VNQ": 0.2, "DBC": 0.2},
                              rebalance="M"),
        "B2 Classic 60/40": dict(weights={"SPY": 0.36, "EFA": 0.24, "IEF": 0.40}, rebalance="M"),
    },
    primary_benchmark="B1 Static 1/n",
    market_ticker="SPY",     # extra: market beta against US equity
    start="2007-01-01",      # first return month = January 2007 (explicit, brief R19)
    end="2025-12-31",        # last return month = December 2025
    history_start="1988-01-01",  # download start: warm-up for signals + inception dates + motivation
    base_ccy="EUR",          # "EUR" (USD prices converted unhedged) or "USD"
    rf_series={"EUR": "IR3TIB01EZM156N", "USD": "TB3MS"},  # FRED, annual % -> monthly decimal
    fx_series="DEXUSEU",     # FRED daily, USD per EUR
    cost_bps=10.0,           # one-way cost in basis points of traded value
    benchmark_costs=True,    # benchmarks pay the same cost on their rebalancing trades (fair comparison)
    signal_lag=1,            # 1 = trade at the signal month-end close, 2 = one month later (fully safe)
    motivation_ticker="^SP500TR",  # pre-sample evidence for the rule (total return index from 1988)
    motivation_end="2006-12-31",
    subperiods=[
        ["2007-01-01", "2012-12-31", "2007-12 Financial and euro crisis"],
        ["2013-01-01", "2019-12-31", "2013-19 Recovery and QE"],
        ["2020-01-01", "2025-12-31", "2020-25 Covid, inflation, rate shock"],
    ],
    crisis_windows=[
        ["2007-11-01", "2009-02-28", "Financial crisis"],
        ["2011-05-01", "2011-09-30", "Euro crisis"],
        ["2020-02-01", "2020-03-31", "Covid crash"],
        ["2022-01-01", "2022-12-31", "2022 inflation shock"],
    ],
    rolling_window=36,
    mc_paths=10000,
    mc_years=10,
    mc_block=12,
    mc_initial=10000.0,
    mc_seed=2270,
    price_source="auto",     # "auto" (yfinance, then Yahoo chart API) | "yfinance" | "yahoo_chart"
)


def get_config(**overrides) -> dict:
    """Return a deep copy of DEFAULT_CONFIG with overrides applied (never mutate the default)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in overrides.items():
        if k not in cfg:
            raise KeyError(f"Unknown CONFIG key: {k}")
        cfg[k] = copy.deepcopy(v)
    return cfg


def engine_sha256(path: str | None = None) -> str:
    """SHA-256 of the engine source file, printed by notebook and app to prove they run identical code."""
    path = path or __file__
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def _month_end_alias() -> str:
    # pandas >= 2.2 calls month-end "ME"; older versions only know "M".
    try:
        pd.date_range("2000-01-31", periods=2, freq="ME")
        return "ME"
    except (ValueError, KeyError):
        return "M"


ME = _month_end_alias()


def _to_month_end_index(idx) -> pd.DatetimeIndex:
    # FRED labels monthly data with the first day of the month; map every label to its month-end.
    idx = pd.DatetimeIndex(idx)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize() + pd.offsets.MonthEnd(0)


# %% [engine 2/8] data: Yahoo prices, FRED rates and FX
# Yahoo wants a browser-like User-Agent; FRED stalls on exactly that, so headers are set per host.
_UA_YAHOO = {"User-Agent": "Mozilla/5.0"}


def _http_get(url: str, params: dict | None = None, retries: int = 3, timeout: int = 30,
              headers: dict | None = None):
    import requests  # imported lazily so the module imports even where requests is missing
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except Exception as e:  # network hiccup: back off and retry
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Download failed after {retries} tries: {url} ({last})")


def _fetch_yfinance(tickers: list, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    # auto_adjust=True: Close is split- and dividend-adjusted (total return), passed explicitly
    # so the call does not depend on the library default. end is exclusive in yfinance.
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(tickers, start=start, end=end_excl, interval="1d", auto_adjust=True,
                      progress=False, threads=False)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = tickers[:1]
    close.index = pd.DatetimeIndex(close.index).tz_localize(None) if close.index.tz is not None \
        else pd.DatetimeIndex(close.index)
    return close.reindex(columns=tickers)


def _fetch_yahoo_chart(ticker: str, start: str, end: str) -> pd.Series:
    # Same Yahoo endpoint yfinance uses; the fallback keeps the notebook running if yfinance breaks.
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
    r = _http_get(f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
                  params=dict(period1=p1, period2=p2, interval="1d", events="div,split",
                              includeAdjustedClose="true"), headers=_UA_YAHOO)
    res = r.json()["chart"]["result"][0]
    tzname = res["meta"].get("exchangeTimezoneName", "America/New_York")
    dates = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(tzname)
    dates = dates.tz_localize(None).normalize()
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    s = pd.Series(adj, index=dates, dtype="float64", name=ticker)
    return s[~s.index.duplicated(keep="last")].dropna()


def fetch_prices_daily(tickers: list, start: str, end: str, source: str = "auto"):
    """Daily adjusted close (USD) for all tickers. Returns (DataFrame, {ticker: source used})."""
    out, used = {}, {}
    if source in ("auto", "yfinance"):
        try:
            px = _fetch_yfinance(tickers, start, end)
            for t in tickers:
                if t in px and px[t].notna().sum() > 0:
                    out[t] = px[t].dropna()
                    used[t] = "yfinance"
        except Exception as e:
            if source == "yfinance":
                raise
            print(f"yfinance unavailable ({type(e).__name__}: {e}); using the Yahoo chart API directly.")
    for t in tickers:
        if t not in out:
            if source == "yfinance":
                raise RuntimeError(f"yfinance returned no data for {t}")
            out[t] = _fetch_yahoo_chart(t, start, end)
            used[t] = "yahoo_chart_api"
    px = pd.DataFrame(out).sort_index()
    return px.reindex(columns=tickers), used


def fetch_fred(series_id: str) -> pd.Series:
    """Key-less FRED download (fredgraph.csv), as shown in the W3 API lecture."""
    r = _http_get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id})
    df = pd.read_csv(io.StringIO(r.text), na_values=["."])
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df.iloc[:, 0]), name=series_id)
    return s.dropna()


def fetch_ecb_euribor3m() -> pd.Series:
    """ECB Data Portal, monthly average 3-month Euribor (% p.a.). Fallback/extension for the EUR rate."""
    r = _http_get("https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
                  params={"format": "csvdata"})
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df["TIME_PERIOD"]), name="EURIBOR3M")
    return s.dropna()


def annual_pct_to_monthly(rate_pct: pd.Series) -> pd.Series:
    """Annual rate in % -> monthly simple return, compounding-consistent: (1 + x/100)^(1/12) - 1."""
    return (1.0 + rate_pct / 100.0) ** (1.0 / PERIODS) - 1.0


def load_data(cfg: dict) -> dict:
    """Download everything once. Returns raw monthly inputs; returns are built later per currency."""
    tickers = list(dict.fromkeys(list(cfg["tickers"]) + [cfg["market_ticker"]] +
                                 [t for b in cfg["benchmarks"].values() for t in b["weights"]] +
                                 ([cfg["motivation_ticker"]] if cfg.get("motivation_ticker") else [])))
    end = cfg["end"]
    px_d, used = fetch_prices_daily(tickers, cfg["history_start"], end, cfg.get("price_source", "auto"))
    first_daily = {t: (px_d[t].first_valid_index().strftime("%Y-%m-%d")
                       if px_d[t].notna().any() else None) for t in tickers}
    # Month-end price = last daily adjusted close of the month (avoids Yahoo's monthly-bar quirks).
    px_m = px_d.resample(ME).last()
    px_m.index = _to_month_end_index(px_m.index)
    # A month only counts for a ticker if the ticker traded in it (no carrying prices forward).
    counts = px_d.resample(ME).count()
    counts.index = px_m.index
    px_m = px_m.where(counts > 0)
    px_m = px_m.loc[: pd.Timestamp(end) + pd.offsets.MonthEnd(0)]

    sources = {"prices": used}
    rf = {}
    rf_usd = fetch_fred(cfg["rf_series"]["USD"])
    rf_usd.index = _to_month_end_index(rf_usd.index)
    rf["USD"] = annual_pct_to_monthly(rf_usd)
    sources["rf_USD"] = f"FRED {cfg['rf_series']['USD']}"
    rf_eur = fetch_fred(cfg["rf_series"]["EUR"])
    rf_eur.index = _to_month_end_index(rf_eur.index)
    sources["rf_EUR"] = f"FRED {cfg['rf_series']['EUR']}"
    need_end = pd.Timestamp(end) + pd.offsets.MonthEnd(0)
    if rf_eur.index.max() < need_end:
        # The OECD series on FRED can lag; fill only the missing tail from the ECB, and say so.
        ecb = fetch_ecb_euribor3m()
        ecb.index = _to_month_end_index(ecb.index)
        tail = ecb[ecb.index > rf_eur.index.max()]
        rf_eur = pd.concat([rf_eur, tail]).sort_index()
        sources["rf_EUR"] += f" (+ ECB 3m Euribor after {tail.index.min():%Y-%m})" if len(tail) else ""
    rf["EUR"] = annual_pct_to_monthly(rf_eur)

    fx_d = fetch_fred(cfg["fx_series"])
    fx = fx_d.resample(ME).last()
    fx.index = _to_month_end_index(fx.index)
    sources["fx"] = f"FRED {cfg['fx_series']} (daily, last obs. of month, USD per EUR)"
    return dict(prices_usd=px_m, fx_usd_per_eur=fx, rf=rf, first_daily=first_daily,
                sources=sources, retrieved_at=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
                daily_prices=px_d)


def synthetic_data(cfg: dict | None = None, seed: int = 7, start: str = "1995-01-31",
                   end: str = "2025-12-31") -> dict:
    """Random-walk prices with the same structure as load_data(): offline tests without a network."""
    cfg = cfg or get_config()
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq=ME)
    idx = _to_month_end_index(idx)
    tickers = list(dict.fromkeys(list(cfg["tickers"]) + [cfg["market_ticker"]] +
                                 [t for b in cfg["benchmarks"].values() for t in b["weights"]] +
                                 ([cfg["motivation_ticker"]] if cfg.get("motivation_ticker") else [])))
    rets = rng.normal(0.006, 0.045, size=(len(idx), len(tickers)))
    px = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=tickers)
    fx = pd.Series(1.2 * np.cumprod(1 + rng.normal(0, 0.02, len(idx))), index=idx)
    rf = {"EUR": pd.Series(0.0015, index=idx), "USD": pd.Series(0.002, index=idx)}
    return dict(prices_usd=px, fx_usd_per_eur=fx, rf=rf,
                first_daily={t: idx[0].strftime("%Y-%m-%d") for t in tickers},
                sources={"prices": {t: "synthetic" for t in tickers}, "rf_EUR": "synthetic",
                         "rf_USD": "synthetic", "fx": "synthetic"},
                retrieved_at="synthetic", daily_prices=None)


def base_ccy_prices(data: dict, ccy: str) -> pd.DataFrame:
    """Month-end prices in the investor's currency. EUR value of a USD asset = USD price / (USD per EUR)."""
    px = data["prices_usd"]
    if ccy == "USD":
        return px.copy()
    if ccy == "EUR":
        fx = data["fx_usd_per_eur"].reindex(px.index)
        return px.div(fx, axis=0)
    raise ValueError("base_ccy must be 'EUR' or 'USD'")


def asset_returns(data: dict, cfg: dict, ccy: str | None = None) -> pd.DataFrame:
    """Monthly simple returns in the base currency for every downloaded ticker, plus CASH = rf."""
    ccy = ccy or cfg["base_ccy"]
    px = base_ccy_prices(data, ccy)
    # fill_method=None: never invent a return across a missing month.
    r = px.pct_change(fill_method=None)
    r[CASH] = data["rf"][ccy].reindex(r.index)
    return r


def window_index(index: pd.DatetimeIndex, start: str, end: str) -> pd.DatetimeIndex:
    s = pd.Timestamp(start) + pd.offsets.MonthEnd(0)
    e = pd.Timestamp(end) + pd.offsets.MonthEnd(0)
    return index[(index >= s) & (index <= e)]


def data_report(data: dict, cfg: dict) -> pd.DataFrame:
    """The lecture's four checks per series (shape, date range, missing values; plot in the notebook)."""
    r = asset_returns(data, cfg)
    win = window_index(r.index, cfg["start"], cfg["end"])
    rows = []
    for t in list(data["prices_usd"].columns):
        p = data["prices_usd"][t]
        rw = r.loc[win, t]
        rows.append(dict(series=t, first_daily_price=data["first_daily"].get(t),
                         first_month_end=p.first_valid_index(), last_month_end=p.last_valid_index(),
                         months_in_window=int(rw.notna().sum()), missing_in_window=int(rw.isna().sum()),
                         min_monthly_return=float(rw.min()), max_monthly_return=float(rw.max()),
                         source=data["sources"]["prices"].get(t)))
    for ccy in ("EUR", "USD"):
        s = data["rf"][ccy].reindex(win)
        rows.append(dict(series=f"rf {ccy}", first_daily_price=None,
                         first_month_end=data["rf"][ccy].index.min(),
                         last_month_end=data["rf"][ccy].index.max(), months_in_window=int(s.notna().sum()),
                         missing_in_window=int(s.isna().sum()), min_monthly_return=float(s.min()),
                         max_monthly_return=float(s.max()), source=data["sources"][f"rf_{ccy}"]))
    fx = data["fx_usd_per_eur"].reindex(win)
    rows.append(dict(series="FX USD per EUR", first_daily_price=None,
                     first_month_end=data["fx_usd_per_eur"].index.min(),
                     last_month_end=data["fx_usd_per_eur"].index.max(), months_in_window=int(fx.notna().sum()),
                     missing_in_window=int(fx.isna().sum()), min_monthly_return=np.nan,
                     max_monthly_return=np.nan, source=data["sources"]["fx"]))
    return pd.DataFrame(rows).set_index("series")


# %% [engine 3/8] allocation rules (information up to t - lag only)
def base_weights(cfg: dict) -> pd.Series:
    tick = list(cfg["tickers"])
    if cfg.get("weights"):
        w = pd.Series({t: float(cfg["weights"].get(t, 0.0)) for t in tick})
    else:
        w = pd.Series(1.0 / len(tick), index=tick)
    if (w < -1e-12).any():
        raise ValueError("Negative base weights are not allowed (no shorting).")
    return w / w.sum()  # renormalise so app sliders never break the sum-to-one rule


def sma_signal(prices: pd.DataFrame, months: int) -> pd.DataFrame:
    """1.0 if the month-end price is above its own `months`-month simple moving average, else 0.0.
    The average includes the current month-end, exactly as in Faber (2007). NaN = not enough history."""
    sma = prices.rolling(months, min_periods=months).mean()
    sig = (prices > sma).astype(float)
    return sig.where(sma.notna())


def target_weights(cfg: dict, data: dict, index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Target weights for each HOLDING month (rows) over tickers + CASH, using data up to t - signal_lag.

    Row t is the portfolio held during month t. With signal_lag = 1 it uses month-end t-1 information:
    the decision is taken at the close of t-1 and earns month t's return (the lecture's shift(1))."""
    lag = int(cfg["signal_lag"])
    if lag < 0:
        raise ValueError("signal_lag must be >= 0")
    tick = list(cfg["tickers"])
    r = asset_returns(data, cfg)
    index = index if index is not None else window_index(r.index, cfg["start"], cfg["end"])
    w0 = base_weights(cfg)
    rule = cfg["rule"]
    if rule in ("fixed", "equal"):
        w = pd.DataFrame([w0.values] * len(index), index=index, columns=tick)
        if rule == "equal":
            w[:] = 1.0 / len(tick)
    elif rule == "trend_sma":
        # Signal on the asset's own USD price: the fund's trades do not depend on the investor's currency.
        sig = sma_signal(data["prices_usd"][tick], int(cfg["sma_months"]))
        held = sig.shift(lag).reindex(index)
        w = held.mul(w0, axis=1)
    elif rule == "inverse_vol":
        vol = r[tick].rolling(int(cfg["vol_window"]), min_periods=int(cfg["vol_window"])).std()
        inv = (1.0 / vol).shift(lag).reindex(index)
        w = inv.div(inv.sum(axis=1), axis=0)
    else:
        raise ValueError(f"Unknown rule: {rule}")
    if w.isna().any().any():
        bad = w.index[w.isna().any(axis=1)][0]
        raise ValueError(f"Not enough history for rule '{rule}' at {bad:%Y-%m} (asset too young for the "
                         f"warm-up window). Choose a later start date.")
    w[CASH] = 1.0 - w.sum(axis=1)
    w[CASH] = w[CASH].clip(lower=0.0)  # numerical noise only; real weights never exceed 1
    return w


def fixed_target(weights: dict, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Static target weights for a benchmark portfolio (plus a zero cash column)."""
    cols = list(weights)
    w = pd.DataFrame([[float(weights[c]) for c in cols]] * len(index), index=index, columns=cols)
    w = w.div(w.sum(axis=1), axis=0)
    w[CASH] = 0.0
    return w


# %% [engine 4/8] drift-aware simulation with transaction costs
@dataclass
class SimResult:
    name: str
    net: pd.Series             # monthly simple return after costs
    gross: pd.Series           # monthly simple return before costs
    held: pd.DataFrame         # weights held during month t (after trading at its start)
    drift: pd.DataFrame        # weights just before trading at the start of month t (drifted)
    traded: pd.Series          # sum over ETFs of |weight change| at the start of month t (buys + sells)
    cost: pd.Series            # cost as a fraction of portfolio value at the start of month t
    rebalanced: pd.Series      # True if a trade happened at the start of month t
    cost_bps: float = 0.0
    extra: dict = field(default_factory=dict)


def _is_scheduled(ts: pd.Timestamp, rebalance) -> bool:
    if rebalance == "M":
        return True
    if rebalance == "Q":
        return ts.month in (1, 4, 7, 10)
    if rebalance == "A":
        return ts.month == 1
    if rebalance in ("none", None):
        return False
    if isinstance(rebalance, (int, float)):
        return False  # threshold rebalancing is decided on drift, see simulate()
    raise ValueError(f"Unknown rebalance setting: {rebalance}")


def simulate(returns: pd.DataFrame, target: pd.DataFrame, rebalance="M", cost_bps: float = 0.0,
             trade_on_signal: bool = True, name: str = "portfolio") -> SimResult:
    """Simulate a portfolio month by month.

    At the start of month t the portfolio holds drifted weights d_t. If t is a trading date it trades to
    the target w_t, paying cost_bps x sum|w_t - d_t| over ETFs (cash itself costs nothing to hold).
    During month t the held weights earn the asset returns and drift: d_{t+1} = h_t (1 + r_t) / (1 + R_t).
    The first month forms the portfolio at target without cost, identically for strategy and benchmarks."""
    cols = list(target.columns)
    R = returns.reindex(index=target.index, columns=cols).to_numpy(dtype=float)
    if np.isnan(R).any():
        bad = target.index[np.isnan(R).any(axis=1)][0]
        missing = [c for c, v in zip(cols, np.isnan(R[target.index.get_loc(bad)])) if v]
        raise ValueError(f"Missing returns at {bad:%Y-%m} for {missing}")
    W = target.to_numpy(dtype=float)
    T, N = W.shape
    risky = np.array([c != CASH for c in cols])
    held = np.zeros((T, N)); drift = np.zeros((T, N))
    traded = np.zeros(T); gross = np.zeros(T); reb = np.zeros(T, dtype=bool)
    d = W[0].copy()
    for t in range(T):
        do = t == 0 or _is_scheduled(target.index[t], rebalance)
        if isinstance(rebalance, (int, float)) and not isinstance(rebalance, bool) and t > 0:
            do = do or np.max(np.abs(d - W[t])) > float(rebalance)
        if trade_on_signal and t > 0:
            # An asset switching between invested and not invested is a real decision: always trade it.
            do = do or bool(np.any((W[t] > 1e-12)[risky] != (W[t - 1] > 1e-12)[risky]))
        h = W[t].copy() if do else d.copy()
        drift[t] = d
        held[t] = h
        traded[t] = float(np.abs(h - d)[risky].sum())
        reb[t] = do and traded[t] > 1e-15
        g = float(h @ R[t])
        gross[t] = g
        d = h * (1.0 + R[t]) / (1.0 + g)
    c = cost_bps / 1e4
    cost = c * traded
    net = (1.0 - cost) * (1.0 + gross) - 1.0
    ix = target.index
    return SimResult(name=name, net=pd.Series(net, ix, name=name), gross=pd.Series(gross, ix, name=name),
                     held=pd.DataFrame(held, ix, cols), drift=pd.DataFrame(drift, ix, cols),
                     traded=pd.Series(traded, ix), cost=pd.Series(cost, ix), rebalanced=pd.Series(reb, ix),
                     cost_bps=float(cost_bps))


def net_from_gross(sim: SimResult, cost_bps: float) -> pd.Series:
    """Net returns for any other cost level. Exact, because costs are proportional and do not change weights."""
    return (1.0 - cost_bps / 1e4 * sim.traded) * (1.0 + sim.gross) - 1.0


def run_backtest(cfg: dict, data: dict) -> dict:
    """Strategy + benchmarks over the configured window, in the configured base currency."""
    r = asset_returns(data, cfg)
    idx = window_index(r.index, cfg["start"], cfg["end"])
    if len(idx) < 24:
        raise ValueError("Backtest window shorter than 24 months.")
    tgt = target_weights(cfg, data, idx)
    strat = simulate(r, tgt, cfg["rebalance"], cfg["cost_bps"], cfg.get("trade_on_signal", True),
                     name=cfg["strategy_name"])
    bms = {}
    for bname, b in cfg["benchmarks"].items():
        bt = fixed_target(b["weights"], idx)
        bms[bname] = simulate(r, bt, b.get("rebalance", "M"),
                              cfg["cost_bps"] if cfg.get("benchmark_costs", True) else 0.0,
                              trade_on_signal=False, name=bname)
    market = r.loc[idx, cfg["market_ticker"]].rename(f"{cfg['market_ticker']} ({cfg['base_ccy']})")
    return dict(cfg=cfg, returns=r.loc[idx], rf=r.loc[idx, CASH].rename("rf"), target=tgt, strategy=strat,
                benchmarks=bms, primary=cfg["primary_benchmark"], market=market, index=idx)


def wealth_index(r: pd.Series, start_value: float = 1.0) -> pd.Series:
    """Cumulative value of 1 invested, with an explicit start row one month before the first return,
    so every series starts at exactly 1.0 on the same date (brief requirement)."""
    r = r.dropna()
    w = start_value * (1.0 + r).cumprod()
    start_row = pd.Series([start_value], index=[r.index[0] - pd.offsets.MonthEnd(1)])
    return pd.concat([start_row, w]).rename(r.name)


# %% [engine 5/8] performance metrics (course definitions)
def drawdown(r: pd.Series) -> pd.Series:
    """DD_t = (HWM_t - V_t) / HWM_t, reported as a negative number (Pedersen 2015, as in W3)."""
    v = wealth_index(r)
    return v / v.cummax() - 1.0


def max_drawdown_info(r: pd.Series) -> dict:
    dd = drawdown(r)
    trough = dd.idxmin()
    peak = dd.loc[:trough][dd.loc[:trough] == 0].index.max()
    after = dd.loc[trough:]
    rec = after[after >= -1e-12].index.min() if (after >= -1e-12).any() else None
    months_to_recover = None
    if rec is not None and not pd.isna(rec):
        months_to_recover = int(round((rec - trough).days / 30.44))
    under = (dd < -1e-12).astype(int)
    longest, cur = 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    return dict(max_drawdown=float(dd.min()), peak=peak.strftime("%Y-%m"), trough=trough.strftime("%Y-%m"),
                recovery=(rec.strftime("%Y-%m") if rec is not None and not pd.isna(rec) else None),
                months_peak_to_trough=int(round((trough - peak).days / 30.44)),
                months_trough_to_recovery=months_to_recover, longest_underwater_months=int(longest))


def _ols(y: np.ndarray, x: np.ndarray, nw_lags: int = 6) -> dict:
    """OLS y = a + b x with classic and Newey-West (HAC) standard errors, hand-coded (no black box)."""
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    coef = XtX_inv @ X.T @ y
    e = y - X @ coef
    s2 = float(e @ e) / (n - 2)
    se = np.sqrt(np.diag(XtX_inv) * s2)
    # Newey-West: monthly returns can be autocorrelated; a robust t-stat guards against overconfidence.
    S = (X * e[:, None]).T @ (X * e[:, None])
    for L in range(1, nw_lags + 1):
        wL = 1.0 - L / (nw_lags + 1.0)
        G = (X[L:] * e[L:, None]).T @ (X[:-L] * e[:-L, None])
        S += wL * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    se_nw = np.sqrt(np.diag(V))
    r2 = 1.0 - float(e @ e) / float(((y - y.mean()) ** 2).sum()) if np.var(y) > 0 else np.nan
    return dict(alpha=float(coef[0]), beta=float(coef[1]), se_alpha=float(se[0]), se_beta=float(se[1]),
                se_alpha_nw=float(se_nw[0]), resid_std=math.sqrt(s2), r2=float(r2), n=n)


def perf_metrics(r: pd.Series, rb: pd.Series | None, rf: pd.Series) -> dict:
    """All metrics from monthly simple returns. rb = benchmark for alpha, beta, IR (None: absolute only)."""
    r = r.astype(float); rf = rf.reindex(r.index).astype(float)
    ex = r - rf
    n = len(r)
    m = dict(months=n,
             ann_return=float(PERIODS * r.mean()),                              # arithmetic, x12
             cagr=float((1.0 + r).prod() ** (PERIODS / n) - 1.0),
             ann_vol=float(math.sqrt(PERIODS) * r.std()),                       # x sqrt(12)
             ann_excess_return=float(PERIODS * ex.mean()),
             sharpe=float(math.sqrt(PERIODS) * ex.mean() / ex.std()) if ex.std() > 0 else np.nan)
    downside = np.minimum(ex.to_numpy(), 0.0)
    dsd = math.sqrt((downside ** 2).mean())
    m["sortino"] = float(math.sqrt(PERIODS) * ex.mean() / dsd) if dsd > 0 else np.nan
    m.update(max_drawdown_info(r))
    m["calmar"] = float(m["cagr"] / abs(m["max_drawdown"])) if m["max_drawdown"] < 0 else np.nan
    roll12 = (1.0 + r).rolling(12).apply(np.prod, raw=True) - 1.0
    m["worst_12m"] = float(roll12.min()); m["best_12m"] = float(roll12.max())
    m["worst_month"] = float(r.min()); m["best_month"] = float(r.max())
    m["pct_positive_months"] = float((r > 0).mean())
    if rb is not None:
        rb = rb.reindex(r.index).astype(float)
        exb = rb - rf
        beta_cov = float(np.cov(ex, exb, ddof=1)[0, 1] / np.var(exb, ddof=1))  # course formula cov/var
        reg = _ols(ex.to_numpy(), exb.to_numpy())
        active = r - rb
        te = float(active.std())
        m.update(beta=beta_cov,                                                    # NOT annualised
                 alpha_monthly=float(ex.mean() - beta_cov * exb.mean()),
                 alpha_ann=float(PERIODS * (ex.mean() - beta_cov * exb.mean())),  # x12
                 # A portfolio against itself has zero residuals: the t-stat is undefined, not noise.
                 alpha_t=float(reg["alpha"] / reg["se_alpha"]) if reg["resid_std"] > 1e-12 else np.nan,
                 alpha_t_nw=float(reg["alpha"] / reg["se_alpha_nw"]) if reg["resid_std"] > 1e-12 else np.nan,
                 r_squared=reg["r2"], correlation=float(np.corrcoef(r, rb)[0, 1]),
                 tracking_error=float(math.sqrt(PERIODS) * te),
                 information_ratio=float(math.sqrt(PERIODS) * active.mean() / te) if te > 1e-15 else np.nan,
                 information_ratio_regression=float(math.sqrt(PERIODS) * reg["alpha"] / reg["resid_std"])
                 if reg["resid_std"] > 1e-12 else np.nan,
                 ann_active_return=float(PERIODS * active.mean()),
                 hit_rate_vs_benchmark=float((active > 0).mean()))
    return m


def turnover_stats(sim: SimResult) -> dict:
    """Turnover = half of the traded value (one-way, the usual fund definition); costs from real trades."""
    years = len(sim.net) / PERIODS
    tv = float(sim.traded.sum() / years)
    cagr_g = float((1 + sim.gross).prod() ** (1 / years) - 1)
    cagr_n = float((1 + sim.net).prod() ** (1 / years) - 1)
    return dict(traded_value_pa=tv, turnover_pa=tv / 2.0, trades_per_year=float(sim.rebalanced.sum() / years),
                cost_drag_pa=cagr_g - cagr_n, cost_bps=sim.cost_bps, cagr_gross=cagr_g, cagr_net=cagr_n)


def breakeven_cost(strat: SimResult, bench: SimResult, bench_pays: bool = True, hi: float = 2000.0) -> float | None:
    """Cost level (bps per one-way trade) at which the strategy's net CAGR equals the benchmark's.
    None if the strategy is already behind at zero cost; inf if it stays ahead up to `hi` bps."""
    def gap(c):
        s = (1 + net_from_gross(strat, c)).prod()
        b = (1 + net_from_gross(bench, c if bench_pays else 0.0)).prod()
        return s - b
    if gap(0.0) <= 0:
        return None
    if gap(hi) > 0:
        return math.inf
    lo, up = 0.0, hi
    for _ in range(80):
        mid = 0.5 * (lo + up)
        lo, up = (mid, up) if gap(mid) > 0 else (lo, mid)
    return 0.5 * (lo + up)


def metrics_table(bt: dict, benchmark: str | None = None) -> pd.DataFrame:
    """Table 1: strategy (net and gross) and every benchmark, relative metrics against `benchmark`."""
    bname = benchmark or bt["primary"]
    rb = bt["benchmarks"][bname].net
    rows = {f"{bt['strategy'].name} (net)": perf_metrics(bt["strategy"].net, rb, bt["rf"]),
            f"{bt['strategy'].name} (gross)": perf_metrics(bt["strategy"].gross, rb, bt["rf"])}
    for k, s in bt["benchmarks"].items():
        rows[k] = perf_metrics(s.net, rb, bt["rf"])
    return pd.DataFrame(rows).T


def headline(bt: dict) -> pd.DataFrame:
    """The six required measures in the brief's order, ready for display."""
    t = metrics_table(bt)
    cols = ["ann_return", "ann_vol", "sharpe", "alpha_ann", "alpha_t", "information_ratio", "beta",
            "cagr", "max_drawdown", "tracking_error"]
    return t[cols].astype(float)


def srri_class(ann_vol: float) -> int:
    """UCITS KIID synthetic risk and reward indicator (CESR/10-673 volatility bands), indicative only."""
    bands = [0.005, 0.02, 0.05, 0.10, 0.15, 0.25]
    for i, b in enumerate(bands, start=1):
        if ann_vol < b:
            return i
    return 7


def annual_returns(series: dict) -> pd.DataFrame:
    """Calendar-year compounded returns for several monthly return series."""
    df = pd.DataFrame(series)
    return (1 + df).groupby(df.index.year).prod() - 1


def rolling_stats(r: pd.Series, rb: pd.Series, rf: pd.Series, window: int = 36) -> pd.DataFrame:
    """Rolling Sharpe (annualised) and beta (not annualised) on excess returns, data up to each month only."""
    ex = r - rf; exb = rb - rf
    sharpe = math.sqrt(PERIODS) * ex.rolling(window).mean() / ex.rolling(window).std()
    beta = ex.rolling(window).cov(exb) / exb.rolling(window).var()
    return pd.DataFrame({"rolling_sharpe": sharpe, "rolling_beta": beta}).dropna()


# %% [engine 6/8] robustness and Monte Carlo
def robustness(cfg: dict, data: dict, bt: dict | None = None) -> dict:
    """Does the conclusion survive other reasonable choices? Each block changes one assumption."""
    bt = bt or run_backtest(cfg, data)
    rf = bt["rf"]; prim = bt["primary"]
    out = {}
    # 1. Costs x0..x3 (exact re-pricing of the same trades).
    rows = []
    for mult in (0, 1, 2, 3):
        c = cfg["cost_bps"] * mult
        s = net_from_gross(bt["strategy"], c)
        b = net_from_gross(bt["benchmarks"][prim], c if cfg.get("benchmark_costs", True) else 0)
        m = perf_metrics(s, b, rf)
        rows.append(dict(cost_multiple=mult, cost_bps=c, cagr=m["cagr"], ann_return=m["ann_return"],
                         sharpe=m["sharpe"], alpha_ann=m["alpha_ann"], information_ratio=m["information_ratio"],
                         benchmark_cagr=perf_metrics(b, None, rf)["cagr"]))
    out["costs"] = pd.DataFrame(rows).set_index("cost_multiple")
    # 2. Signal lag 1 vs 2 (2 = decision one full month before trading, fully safe).
    rows = []
    for lag in (1, 2):
        b2 = run_backtest(get_config(**{**cfg, "signal_lag": lag}), data)
        m = perf_metrics(b2["strategy"].net, b2["benchmarks"][prim].net, b2["rf"])
        rows.append(dict(signal_lag=lag, cagr=m["cagr"], ann_vol=m["ann_vol"], sharpe=m["sharpe"],
                         max_drawdown=m["max_drawdown"], alpha_ann=m["alpha_ann"],
                         information_ratio=m["information_ratio"]))
    out["lag"] = pd.DataFrame(rows).set_index("signal_lag")
    # 3. Rebalancing frequency of the static benchmark B1 (hidden-rebalancing check, Lecture 4.3) and strategy.
    rows = []
    for reb in ("M", "Q", "A", "none", 0.05):
        bw = cfg["benchmarks"][prim]["weights"]
        sim = simulate(bt["returns"], fixed_target(bw, bt["index"]), reb, cfg["cost_bps"], False, prim)
        m = perf_metrics(sim.net, None, rf)
        ts = turnover_stats(sim)
        rows.append(dict(portfolio=prim, rebalance=str(reb), cagr=m["cagr"], ann_vol=m["ann_vol"],
                         sharpe=m["sharpe"], max_drawdown=m["max_drawdown"], turnover_pa=ts["turnover_pa"]))
    for reb in ("M", "Q", "A"):
        b2 = run_backtest(get_config(**{**cfg, "rebalance": reb}), data)
        m = perf_metrics(b2["strategy"].net, None, b2["rf"])
        ts = turnover_stats(b2["strategy"])
        rows.append(dict(portfolio="Strategy", rebalance=reb, cagr=m["cagr"], ann_vol=m["ann_vol"],
                         sharpe=m["sharpe"], max_drawdown=m["max_drawdown"], turnover_pa=ts["turnover_pa"]))
    out["rebalancing"] = pd.DataFrame(rows)
    # 4. Sub-periods: is the result driven by one episode?
    rows = []
    for s0, s1, label in cfg["subperiods"]:
        ix = window_index(bt["index"], s0, s1)
        for name, ser in [("Strategy", bt["strategy"].net)] + [(k, v.net) for k, v in bt["benchmarks"].items()]:
            m = perf_metrics(ser.loc[ix], bt["benchmarks"][prim].net.loc[ix] if name == "Strategy" else None,
                             rf.loc[ix])
            rows.append(dict(period=label, portfolio=name, cagr=m["cagr"], ann_vol=m["ann_vol"],
                             sharpe=m["sharpe"], max_drawdown=m["max_drawdown"],
                             information_ratio=m.get("information_ratio", np.nan)))
    out["subperiods"] = pd.DataFrame(rows)
    # 5. Crisis windows: cumulative return over each stress episode.
    rows = []
    for s0, s1, label in cfg["crisis_windows"]:
        ix = window_index(bt["index"], s0, s1)
        row = dict(window=label, start=ix[0].strftime("%Y-%m"), end=ix[-1].strftime("%Y-%m"),
                   Strategy=float((1 + bt["strategy"].net.loc[ix]).prod() - 1))
        for k, v in bt["benchmarks"].items():
            row[k] = float((1 + v.net.loc[ix]).prod() - 1)
        rows.append(row)
    out["crises"] = pd.DataFrame(rows).set_index("window")
    # 6. Currency view: same fund, measured in EUR vs USD.
    rows = []
    for ccy in ("EUR", "USD"):
        b2 = run_backtest(get_config(**{**cfg, "base_ccy": ccy}), data)
        for name, ser in [("Strategy", b2["strategy"].net)] + [(k, v.net) for k, v in b2["benchmarks"].items()]:
            m = perf_metrics(ser, b2["benchmarks"][prim].net if name == "Strategy" else None, b2["rf"])
            rows.append(dict(base_ccy=ccy, portfolio=name, cagr=m["cagr"], ann_vol=m["ann_vol"],
                             sharpe=m["sharpe"], max_drawdown=m["max_drawdown"],
                             alpha_ann=m.get("alpha_ann", np.nan)))
    out["currency"] = pd.DataFrame(rows)
    # 7. Parameter neighbourhood (NOT an optimisation: 10 months stays fixed from the paper).
    rows = []
    if cfg["rule"] == "trend_sma":
        for n in (6, 8, 10, 12):
            try:
                b2 = run_backtest(get_config(**{**cfg, "sma_months": n}), data)
            except ValueError:
                continue
            m = perf_metrics(b2["strategy"].net, b2["benchmarks"][prim].net, b2["rf"])
            rows.append(dict(sma_months=n, cagr=m["cagr"], ann_vol=m["ann_vol"], sharpe=m["sharpe"],
                             max_drawdown=m["max_drawdown"], alpha_ann=m["alpha_ann"]))
    out["sma_months"] = pd.DataFrame(rows).set_index("sma_months") if rows else pd.DataFrame()
    return out


def block_bootstrap(returns: pd.DataFrame, n_paths: int = 10000, n_months: int = 120, block: int = 12,
                    initial: float = 10000.0, seed: int = 2270) -> dict:
    """Moving-block bootstrap of historical monthly returns (Week 5 Monte Carlo).

    Blocks of `block` consecutive months are drawn jointly for all columns, which keeps the
    cross-correlation and part of the autocorrelation (crises last longer than one month)."""
    rng = np.random.default_rng(seed)
    X = returns.dropna().to_numpy(dtype=float)
    T, K = X.shape
    n_blocks = int(math.ceil(n_months / block))
    starts = rng.integers(0, T - block + 1, size=(n_paths, n_blocks))
    rows = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_paths, -1)[:, :n_months]
    paths = X[rows]                                  # (paths, months, K)
    wealth = initial * np.cumprod(1.0 + paths, axis=1)
    wealth = np.concatenate([np.full((n_paths, 1, K), initial), wealth], axis=1)
    peak = np.maximum.accumulate(wealth, axis=1)
    mdd = (wealth / peak - 1.0).min(axis=1)          # (paths, K)
    qs = [5, 25, 50, 75, 95]
    bands = {c: pd.DataFrame(np.percentile(wealth[:, :, k], qs, axis=0).T, columns=[f"p{q}" for q in qs])
             for k, c in enumerate(returns.columns)}
    final = wealth[:, -1, :]
    summary = {}
    for k, c in enumerate(returns.columns):
        f = final[:, k]
        summary[c] = dict(p5=float(np.percentile(f, 5)), p25=float(np.percentile(f, 25)),
                          median=float(np.median(f)), p75=float(np.percentile(f, 75)),
                          p95=float(np.percentile(f, 95)), mean=float(f.mean()),
                          prob_loss=float((f < initial).mean()),
                          prob_drawdown_over_20pct=float((mdd[:, k] < -0.20).mean()),
                          median_max_drawdown=float(np.median(mdd[:, k])))
    if K >= 2:
        summary["prob_first_beats_second"] = float((final[:, 0] > final[:, 1]).mean())
    return dict(bands=bands, summary=summary, n_paths=n_paths, n_months=n_months, block=block,
                initial=initial, seed=seed, columns=list(returns.columns))


def motivation(cfg: dict, data: dict) -> dict:
    """Pre-sample evidence (before the backtest window, so no look-ahead in the motivation itself):
    the same 10-month rule on the S&P 500 total return index, USD, up to motivation_end."""
    t = cfg.get("motivation_ticker")
    if not t or t not in data["prices_usd"]:
        return {}
    px = data["prices_usd"][t].dropna()
    px = px.loc[: pd.Timestamp(cfg["motivation_end"]) + pd.offsets.MonthEnd(0)]
    r = px.pct_change(fill_method=None)
    sig = sma_signal(px.to_frame(), int(cfg["sma_months"]))[t].shift(int(cfg["signal_lag"]))
    rf = data["rf"]["USD"].reindex(r.index)
    ok = sig.notna() & r.notna() & rf.notna()
    r, sig, rf = r[ok], sig[ok], rf[ok]
    timed = sig * r + (1 - sig) * rf
    bh = perf_metrics(r, None, rf); tm = perf_metrics(timed, None, rf)
    return dict(ticker=t, start=r.index[0].strftime("%Y-%m"), end=r.index[-1].strftime("%Y-%m"),
                buy_and_hold=bh, timed=tm, share_invested=float(sig.mean()),
                series=pd.DataFrame({"Buy and hold": r, "10-month SMA rule": timed}))


# %% [engine 7/8] figures and export
STYLE = dict(ink="#14213D", navy="#1F4E79", navy_light="#DCE6F0", ochre="#C08A2B", slate="#8A94A6",
             cash="#9DB7D5", loss="#A23B3B", grid="#E6E9EF", paper="#FFFFFF")
ASSET_COLOURS = {"SPY": "#1F4E79", "EFA": "#3D7AB5", "IEF": "#6FA3C8", "VNQ": "#C08A2B", "DBC": "#8C6D46",
                 CASH: "#D9E2EC"}
MM = 1 / 25.4
SIZE_FULL = (170 * MM, 80 * MM)
SIZE_HALF = (82 * MM, 60 * MM)
SOURCE_LINE = "Source: Yahoo Finance, FRED; group calculations."


def apply_style():
    """One calm institutional chart style (design tokens shared with prospectus and app)."""
    import matplotlib as mpl
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    family = [f for f in ("Inter", "DejaVu Sans") if f in names] or ["sans-serif"]
    mpl.rcParams.update({
        "font.family": family, "font.size": 7.5, "axes.titlesize": 8.5, "axes.labelsize": 7.5,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "axes.edgecolor": STYLE["ink"], "axes.labelcolor": STYLE["ink"], "text.color": STYLE["ink"],
        "xtick.color": STYLE["ink"], "ytick.color": STYLE["ink"],
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": STYLE["grid"], "grid.linewidth": 0.6, "axes.linewidth": 0.6,
        "figure.facecolor": STYLE["paper"], "axes.facecolor": STYLE["paper"], "savefig.facecolor": STYLE["paper"],
        "svg.fonttype": "none", "legend.frameon": False, "lines.linewidth": 1.4,
    })


def _pct_axis(ax, decimals=0):
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.{decimals}f}%"))


def _spread_labels(ax, items: list, min_gap: float = 0.065):
    """Direct end-of-line labels (instead of a legend), pushed apart in axes coordinates so they never
    overlap. items = [(y_value_in_data_units, text, colour, fontweight)]."""
    ax.get_ylim()  # forces autoscaling so the data-to-axes transform is final
    to_axes = ax.transAxes.inverted()
    x_ref = ax.get_xlim()[1]
    pts = sorted([(float(to_axes.transform(ax.transData.transform((x_ref, y)))[1]), t, c, fw)
                  for y, t, c, fw in items])
    ys = [p[0] for p in pts]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + min_gap)
    overflow = ys[-1] - 0.98 if ys else 0
    if overflow > 0:
        ys = [y - overflow for y in ys]
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - min_gap)
    for y, (_, t, c, fw) in zip(ys, pts):
        ax.annotate(t, xy=(1.01, y), xycoords="axes fraction", color=c, fontsize=6.8, va="center",
                    fontweight=fw, annotation_clip=False)


def _finish(fig, ax, title: str | None, subtitle: str | None, source: bool = True):
    if title:
        fig.suptitle(title, x=0.01, ha="left", fontsize=9, fontweight="semibold", y=0.995)
    if subtitle:
        ax.set_title(subtitle, loc="left", fontsize=7, color=STYLE["slate"])
    if source:
        fig.text(0.01, 0.005, SOURCE_LINE, fontsize=6, color=STYLE["slate"], ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 0.97 if title else 1))
    return fig


def fig_cumulative(bt: dict, title=None, subtitle=None, log=True):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=SIZE_FULL)
    s_net = wealth_index(bt["strategy"].net); s_gr = wealth_index(bt["strategy"].gross)
    ax.plot(s_gr.index, s_gr, color=STYLE["navy"], lw=0.9, ls="--", alpha=0.7)
    ax.plot(s_net.index, s_net, color=STYLE["navy"], lw=1.8)
    cols = [STYLE["ochre"], STYLE["slate"], "#5B6B82"]
    ends = [(s_net, "Strategy (net)", STYLE["navy"])]
    for (k, v), c in zip(bt["benchmarks"].items(), cols):
        w = wealth_index(v.net)
        ax.plot(w.index, w, color=c, lw=1.3, ls="-" if k == bt["primary"] else (0, (4, 2)))
        ends.append((w, k, c))
    ends.append((s_gr, "Strategy (gross)", STYLE["navy"]))
    if log:
        ax.set_yscale("log")
        from matplotlib.ticker import FuncFormatter, LogLocator
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2f}"))
        ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    ax.axhline(1.0, color=STYLE["ink"], lw=0.5, alpha=0.5)
    ax.set_ylabel(f"Value of 1 {bt['cfg']['base_ccy']} invested")
    ax.set_xlim(s_net.index[0], s_net.index[-1])
    _spread_labels(ax, [(w.iloc[-1], f"{lab} {w.iloc[-1]:.2f}", c, "normal" if "gross" in lab else "semibold")
                        for w, lab, c in ends])
    return _finish(fig, ax, title, subtitle)


def fig_drawdowns(bt: dict, title=None, subtitle=None):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=SIZE_FULL)
    dd = drawdown(bt["strategy"].net)
    ax.fill_between(dd.index, dd, 0, color=STYLE["loss"], alpha=0.25, lw=0)
    ax.plot(dd.index, dd, color=STYLE["navy"], lw=1.4, label="Strategy (net)")
    cols = [STYLE["ochre"], STYLE["slate"]]
    for (k, v), c in zip(bt["benchmarks"].items(), cols):
        d = drawdown(v.net)
        ax.plot(d.index, d, color=c, lw=1.1, ls="-" if k == bt["primary"] else (0, (4, 2)), label=k)
    _pct_axis(ax)
    ax.set_xlim(dd.index[0], dd.index[-1])
    ax.set_ylabel("Fall from previous high")
    ax.legend(loc="lower left", ncol=3)
    return _finish(fig, ax, title, subtitle)


def fig_weights(bt: dict, title=None, subtitle=None):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=SIZE_FULL)
    w = bt["strategy"].held
    cols = [c for c in w.columns if c != CASH] + [CASH]
    names = bt["cfg"]["asset_names"]
    ax.stackplot(w.index, *[w[c].to_numpy() for c in cols],
                 colors=[ASSET_COLOURS.get(c, STYLE["slate"]) for c in cols],
                 labels=[names.get(c, c) if c != CASH else "Cash (EUR 3m rate)" if bt["cfg"]["base_ccy"] == "EUR"
                         else "Cash (US T-bill)" for c in cols], lw=0, step="post")
    ax.set_ylim(0, 1); ax.set_xlim(w.index[0], w.index[-1])
    _pct_axis(ax)
    ax.set_ylabel("Portfolio weight")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=6.5)
    return _finish(fig, ax, title, subtitle)


def fig_rolling(bt: dict, window: int = 36, title=None, subtitle=None):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=SIZE_FULL)
    prim = bt["benchmarks"][bt["primary"]].net
    rs = rolling_stats(bt["strategy"].net, prim, bt["rf"], window)
    rb = rolling_stats(prim, prim, bt["rf"], window)
    axes[0].plot(rs.index, rs["rolling_sharpe"], color=STYLE["navy"], label="Strategy")
    axes[0].plot(rb.index, rb["rolling_sharpe"], color=STYLE["ochre"], label=bt["primary"])
    axes[0].axhline(0, color=STYLE["ink"], lw=0.5)
    axes[0].set_title(f"Rolling {window}-month Sharpe ratio (annualised)", loc="left", fontsize=7.5)
    axes[0].legend(loc="lower left")
    rm = rolling_stats(bt["strategy"].net, bt["market"], bt["rf"], window)
    axes[1].plot(rs.index, rs["rolling_beta"], color=STYLE["navy"], label=f"vs {bt['primary']}")
    axes[1].plot(rm.index, rm["rolling_beta"], color=STYLE["slate"], ls=(0, (4, 2)), label="vs US equity")
    axes[1].axhline(1, color=STYLE["ink"], lw=0.5)
    axes[1].set_title(f"Rolling {window}-month beta (not annualised)", loc="left", fontsize=7.5)
    axes[1].legend(loc="lower left")
    fig2 = _finish(fig, axes[0], title, None)
    if subtitle:
        fig2.text(0.01, 0.94 if title else 0.985, subtitle, fontsize=7, color=STYLE["slate"])
    return fig2


def cost_sensitivity(bt: dict, max_bps: int = 100, step: int = 5) -> pd.DataFrame:
    rows = []
    for c in range(0, max_bps + 1, step):
        row = {"cost_bps": c, "Strategy": float((1 + net_from_gross(bt["strategy"], c)).prod()
                                                 ** (PERIODS / len(bt["index"])) - 1)}
        for k, v in bt["benchmarks"].items():
            cb = c if bt["cfg"].get("benchmark_costs", True) else 0
            row[k] = float((1 + net_from_gross(v, cb)).prod() ** (PERIODS / len(bt["index"])) - 1)
        rows.append(row)
    return pd.DataFrame(rows).set_index("cost_bps")


def fig_costs(bt: dict, title=None, subtitle=None):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=SIZE_HALF)
    cs = cost_sensitivity(bt)
    ax.plot(cs.index, cs["Strategy"], color=STYLE["navy"], lw=1.8, label="Strategy")
    cols = [STYLE["ochre"], STYLE["slate"]]
    for k, c in zip(bt["benchmarks"], cols):
        ax.plot(cs.index, cs[k], color=c, lw=1.2, ls="-" if k == bt["primary"] else (0, (4, 2)), label=k)
    ax.axvline(bt["cfg"]["cost_bps"], color=STYLE["ink"], lw=0.6, ls=":")
    ax.annotate(f"assumed {bt['cfg']['cost_bps']:.0f} bps", xy=(bt["cfg"]["cost_bps"], 0.32),
                xycoords=("data", "axes fraction"), xytext=(-4, 0), textcoords="offset points", fontsize=6,
                rotation=90, ha="right", va="center")
    be = breakeven_cost(bt["strategy"], bt["benchmarks"][bt["primary"]], bt["cfg"].get("benchmark_costs", True))
    if be is not None and math.isfinite(be) and be <= cs.index.max():
        ax.axvline(be, color=STYLE["loss"], lw=0.8, ls="--")
        ax.annotate(f"breakeven {be:.0f} bps", xy=(be, 0.04), xycoords=("data", "axes fraction"),
                    xytext=(3, 0), textcoords="offset points", fontsize=6, color=STYLE["loss"])
    _pct_axis(ax, 1)
    ax.set_xlabel("Cost per trade (bps of traded value)")
    ax.set_ylabel("CAGR, net")
    ax.set_xlim(0, cs.index.max())
    _spread_labels(ax, [(cs[c].iloc[-1], "Strategy" if c == "Strategy" else c.split(" ")[0], col, "semibold")
                        for c, col in zip(cs.columns, [STYLE["navy"], STYLE["ochre"], STYLE["slate"]])])
    return _finish(fig, ax, title, subtitle)


def fig_subperiods(rob: dict, title=None, subtitle=None):
    import matplotlib.pyplot as plt
    sp = rob["subperiods"]
    periods = list(dict.fromkeys(sp["period"]))
    ports = list(dict.fromkeys(sp["portfolio"]))
    fig, ax = plt.subplots(figsize=SIZE_HALF)
    ax.set_axisbelow(True)  # gridlines behind the bars
    width = 0.8 / len(ports)
    cols = [STYLE["navy"], STYLE["ochre"], STYLE["slate"]]
    for i, p in enumerate(ports):
        vals = [float(sp[(sp.period == per) & (sp.portfolio == p)]["cagr"].iloc[0]) for per in periods]
        x = np.arange(len(periods)) + (i - (len(ports) - 1) / 2) * width
        ax.bar(x, vals, width=width * 0.95, color=cols[i % 3], label=p)
    ax.set_xticks(np.arange(len(periods)))
    ax.set_xticklabels([p.split(" ", 1)[0] for p in periods])
    ax.axhline(0, color=STYLE["ink"], lw=0.5)
    _pct_axis(ax, 0)
    ax.set_ylabel("CAGR, net")
    ax.legend(loc="upper left", fontsize=6)
    return _finish(fig, ax, title, subtitle)


def fig_montecarlo(mc: dict, labels: tuple = ("Strategy", "B2 Classic 60/40"), title=None, subtitle=None):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=SIZE_FULL)
    x = np.arange(mc["n_months"] + 1) / PERIODS
    cols = [STYLE["navy"], STYLE["slate"]]
    items = []
    for (c, colour, lab) in zip(mc["columns"][:2], cols, labels):
        b = mc["bands"][c]
        ax.fill_between(x, b["p5"], b["p95"], color=colour, alpha=0.10, lw=0)
        ax.fill_between(x, b["p25"], b["p75"], color=colour, alpha=0.22, lw=0)
        ax.plot(x, b["p50"], color=colour, lw=1.6, label=f"{lab}: median path")
        ax.plot(x, b["p5"], color=colour, lw=0.7, ls=":")
        items += [(b["p50"].iloc[-1], f"{lab} median {b['p50'].iloc[-1]:,.0f}", colour, "semibold"),
                  (b["p5"].iloc[-1], f"{lab} worst 5% {b['p5'].iloc[-1]:,.0f}", colour, "normal")]
    ax.axhline(mc["initial"], color=STYLE["ink"], lw=0.5)
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("Years from today"); ax.set_ylabel("Portfolio value (EUR)")
    ax.set_xlim(0, x[-1])
    ax.legend(loc="upper left", title="Dark band: middle 50% of paths, light band: 90%", title_fontsize=6)
    _spread_labels(ax, items)
    return _finish(fig, ax, title, subtitle)


def fig_motivation(mot: dict, title=None, subtitle=None):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=SIZE_HALF)
    s = mot["series"]
    for c, colour, ls in [("Buy and hold", STYLE["slate"], (0, (4, 2))), ("10-month SMA rule", STYLE["navy"], "-")]:
        w = wealth_index(s[c])
        ax.plot(w.index, w, color=colour, lw=1.4, ls=ls, label=c)
    ax.set_yscale("log")
    from matplotlib.ticker import FuncFormatter, NullFormatter
    from matplotlib.dates import YearLocator
    top = float(wealth_index(s["Buy and hold"]).max())
    ax.set_yticks([v for v in (1, 2, 3, 4, 6, 8, 12, 16) if v <= top * 1.1])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_locator(YearLocator(4))
    ax.set_ylabel("Value of 1 USD (log scale)")
    ax.legend(loc="upper left", fontsize=6)
    return _finish(fig, ax, title, subtitle)


def save_figure(fig, name: str, outdir: str = "output/figures"):
    """SVG for the prospectus (text stays text, font Inter via CSS) and PNG 200 dpi for display."""
    import os
    os.makedirs(outdir, exist_ok=True)
    svg = os.path.join(outdir, f"{name}.svg"); png = os.path.join(outdir, f"{name}.png")
    fig.savefig(svg, format="svg", metadata={"Date": None})  # no timestamp: reruns give identical files
    fig.savefig(png, format="png", dpi=200)
    with open(svg, "r", encoding="utf-8") as f:
        txt = f.read()
    txt = txt.replace("font-family:'DejaVu Sans'", "font-family:Inter,'DejaVu Sans',Arial,sans-serif") \
             .replace("font-family: 'DejaVu Sans'", "font-family: Inter, 'DejaVu Sans', Arial, sans-serif")
    with open(svg, "w", encoding="utf-8") as f:
        f.write(txt)
    return svg, png


def to_jsonable(obj):
    """Convert numpy/pandas objects to plain JSON types (NaN and inf become null)."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return {str(i.strftime("%Y-%m") if isinstance(i, pd.Timestamp) else i): to_jsonable(r.to_dict())
                for i, r in obj.iterrows()}
    if isinstance(obj, pd.Series):
        return {str(i.strftime("%Y-%m") if isinstance(i, pd.Timestamp) else i): to_jsonable(v)
                for i, v in obj.items()}
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if (math.isnan(obj) or math.isinf(obj)) else float(obj)
    return obj


# %% [engine 8/8] self-tests and results export
def self_tests(cfg: dict, data: dict, bt: dict | None = None) -> pd.DataFrame:
    """Automated checks of the engine itself. Each returns PASS/FAIL with a measured detail."""
    bt = bt or run_backtest(cfg, data)
    res = []

    def add(name, ok, detail):
        res.append(dict(test=name, result="PASS" if ok else "FAIL", detail=detail))

    # 1. Look-ahead: scramble every input after month T; nothing decided or earned up to T may change.
    T = bt["index"][len(bt["index"]) // 2]
    T1 = T + pd.offsets.MonthEnd(1)
    rng = np.random.default_rng(1)
    pert = dict(data)
    px = data["prices_usd"].copy()
    after = px.index > T
    px.loc[after] = px.loc[after].to_numpy() * rng.lognormal(0, 0.3, size=px.loc[after].shape)
    pert["prices_usd"] = px
    fx = data["fx_usd_per_eur"].copy()
    fx.loc[fx.index > T] = fx.loc[fx.index > T] * 1.5
    pert["fx_usd_per_eur"] = fx
    pert["rf"] = {k: v.where(v.index <= T, v * 3 + 0.01) for k, v in data["rf"].items()}
    bp = run_backtest(cfg, pert)
    dw = float((bt["strategy"].held.loc[:T1] - bp["strategy"].held.loc[:T1]).abs().max().max())
    dr = float((bt["strategy"].net.loc[:T] - bp["strategy"].net.loc[:T]).abs().max())
    add("Look-ahead: inputs after T scrambled, weights up to T+1 and returns up to T unchanged",
        dw < 1e-12 and dr < 1e-12, f"T={T:%Y-%m}, max weight diff {dw:.1e}, max return diff {dr:.1e}")
    # Negative control: with lag 0 (look-ahead on purpose) the same test must detect a change.
    if cfg["rule"] == "trend_sma":
        c0 = get_config(**{**cfg, "signal_lag": 0})
        a0, p0 = run_backtest(c0, data), run_backtest(c0, pert)
        d0 = float((a0["strategy"].held.loc[:T1] - p0["strategy"].held.loc[:T1]).abs().max().max())
        add("Negative control: the same test catches a lag-0 (look-ahead) version",
            d0 > 1e-6, f"lag-0 weight diff up to T+1 = {d0:.3f}")
    # 2. Weights: sum to 1 every month, no negatives (no shorting, no leverage).
    allw = [bt["strategy"].held, bt["strategy"].drift] + [b.held for b in bt["benchmarks"].values()]
    ssum = max(float((w.sum(axis=1) - 1).abs().max()) for w in allw)
    smin = min(float(w.min().min()) for w in allw)
    add("Weights sum to 1 at every date and are never negative", ssum < 1e-10 and smin >= -1e-12,
        f"max |sum - 1| = {ssum:.1e}, min weight = {smin:.4f}")
    # 3. Lecture 4.3 fixture: fixed 60/40, monthly rebalancing, zero cost = (w * r).sum(axis=1).
    r = bt["returns"]
    fw = {"SPY": 0.6, "IEF": 0.4}
    sim = simulate(r, fixed_target(fw, bt["index"]), "M", 0.0, False, "fixture")
    ref = (r[list(fw)] * pd.Series(fw)).sum(axis=1)
    d3 = float((sim.net - ref).abs().max())
    add("Fixture: 60/40 with monthly rebalancing and zero cost equals (w * r).sum(axis=1)", d3 < 1e-12,
        f"max diff {d3:.1e}")
    # 4. Drift fixture: never rebalanced = buy-and-hold of the two assets (weights really drift).
    sim_bh = simulate(r, fixed_target(fw, bt["index"]), "none", 0.0, False, "bh")
    bh = 0.6 * (1 + r["SPY"]).cumprod() + 0.4 * (1 + r["IEF"]).cumprod()
    d4 = float(((1 + sim_bh.net).cumprod() - bh).abs().max())
    add("Fixture: no rebalancing equals buy-and-hold of the individual assets (drift is modelled)", d4 < 1e-10,
        f"max wealth diff {d4:.1e}")
    # 5. Benchmark against itself: beta 1, alpha 0, tracking error 0.
    b = bt["benchmarks"][bt["primary"]].net
    m = perf_metrics(b, b, bt["rf"])
    ok = abs(m["beta"] - 1) < 1e-12 and abs(m["alpha_ann"]) < 1e-12 and m["tracking_error"] < 1e-12
    add("Benchmark regressed on itself gives beta 1, alpha 0, tracking error 0", ok,
        f"beta {m['beta']:.12f}, alpha {m['alpha_ann']:.1e}, TE {m['tracking_error']:.1e}")
    # 6. Cumulative series start at exactly 1 on the same date.
    ws = [wealth_index(bt["strategy"].net), wealth_index(bt["strategy"].gross)] + \
         [wealth_index(v.net) for v in bt["benchmarks"].values()]
    ok = all(w.iloc[0] == 1.0 for w in ws) and len({w.index[0] for w in ws}) == 1
    add("All cumulative series start at exactly 1.0 on the same date", ok, f"start {ws[0].index[0]:%Y-%m-%d}")
    # 7. Costs: net = (1 - c * traded)(1 + gross) - 1 and net never above gross.
    s = bt["strategy"]
    d7 = float((s.net - net_from_gross(s, s.cost_bps)).abs().max())
    add("Costs: net return identity holds and net <= gross every month",
        d7 < 1e-15 and bool((s.net <= s.gross + 1e-15).all()), f"identity diff {d7:.1e}")
    # 8. Independent recomputation of the signal for one asset at one date (plain Python, no rolling()).
    if cfg["rule"] == "trend_sma":
        tick = cfg["tickers"][0]; n = int(cfg["sma_months"]); lag = int(cfg["signal_lag"])
        t_hold = bt["index"][len(bt["index"]) // 3]
        p = data["prices_usd"][tick].dropna()
        k = p.index.get_loc(t_hold) - lag
        last = p.iloc[k - n + 1:k + 1].tolist()
        manual = 1.0 if p.iloc[k] > sum(last) / n else 0.0
        engine = float(bt["strategy"].held.loc[t_hold, tick] > 0)
        add(f"Signal recomputed by hand ({n} prices, plain average) matches the engine", manual == engine,
            f"{tick} held in {t_hold:%Y-%m}: manual {manual:.0f}, engine {engine:.0f}")
    # 9. Two independent formulas agree: beta = cov/var equals the OLS slope; Sharpe by hand.
    sr = bt["strategy"].net
    ex = (sr - bt["rf"]).to_numpy(); exb = (b - bt["rf"]).to_numpy()
    slope = float(np.polyfit(exb, ex, 1)[0])
    ms = perf_metrics(sr, b, bt["rf"])
    sharpe_hand = float(np.mean(ex) / np.std(ex, ddof=1) * math.sqrt(12))
    ok = abs(slope - ms["beta"]) < 1e-10 and abs(sharpe_hand - ms["sharpe"]) < 1e-12
    add("Beta (cov/var) equals the OLS slope; Sharpe recomputed by hand", ok,
        f"beta {ms['beta']:.6f} vs slope {slope:.6f}; Sharpe {ms['sharpe']:.6f} vs {sharpe_hand:.6f}")
    # 10. Annualisation conventions (the lecture's AI-bug list): vol x sqrt(12), mean x12, beta raw.
    ok = abs(ms["ann_vol"] - sr.std() * math.sqrt(12)) < 1e-14 and abs(ms["ann_return"] - 12 * sr.mean()) < 1e-14
    add("Annualisation: return x12, volatility x sqrt(12), beta not annualised", ok,
        f"ann. vol {ms['ann_vol']:.4f} = monthly {sr.std():.4f} x sqrt(12)")
    return pd.DataFrame(res)


def build_results(cfg: dict, data: dict, bt: dict, rob: dict, mc: dict, mot: dict, tests: pd.DataFrame,
                  extra: dict | None = None) -> dict:
    """Everything the prospectus prints, in one JSON-able dictionary (schema: RESULTS-SCHEMA.md)."""
    prim = bt["primary"]
    strat_name = bt["strategy"].name
    bench_keys = list(bt["benchmarks"])
    t1 = metrics_table(bt, prim)
    second = [k for k in bench_keys if k != prim]
    t2 = metrics_table(bt, second[0]) if second else None
    keys_rel = ["beta", "alpha_ann", "alpha_t", "alpha_t_nw", "information_ratio", "information_ratio_regression",
                "tracking_error", "r_squared", "correlation", "ann_active_return", "hit_rate_vs_benchmark"]
    labels = [(f"{strat_name} (net)", "strategy"), (f"{strat_name} (gross)", "strategy_gross")] + \
             [(k, k) for k in bench_keys]
    portfolios = {key: to_jsonable(t1.loc[lab].to_dict()) for lab, key in labels}
    vs_second = {}
    if t2 is not None:
        vs_second = {key: {kk: to_jsonable(t2.loc[lab, kk]) for kk in keys_rel} for lab, key in labels}
        vs_second["benchmark"] = second[0]
    series = [("strategy", bt["strategy"].net)] + [(k, v.net) for k, v in bt["benchmarks"].items()]
    vs_market = {k: {kk: to_jsonable(perf_metrics(v, bt["market"], bt["rf"])[kk])
                     for kk in ("beta", "alpha_ann", "alpha_t", "correlation")} for k, v in series}
    vs_market["market"] = bt["market"].name
    costs = dict(strategy=turnover_stats(bt["strategy"]),
                 **{k: turnover_stats(v) for k, v in bt["benchmarks"].items()})
    be = {k: breakeven_cost(bt["strategy"], v, cfg.get("benchmark_costs", True)) for k, v in bt["benchmarks"].items()}
    held = bt["strategy"].held
    risky = held.drop(columns=CASH)
    invested = 1 - held[CASH]
    years = len(held) / PERIODS
    switches = (risky > 1e-12).astype(int).diff().abs().sum()
    allocation = dict(avg_weight=to_jsonable(held.mean()),
                      share_months_invested=to_jsonable((risky > 1e-12).mean()),
                      avg_invested=float(invested.mean()), min_invested=float(invested.min()),
                      max_invested=float(invested.max()), months_fully_in_cash=int((invested < 1e-12).sum()),
                      months_fully_invested=int((invested > 1 - 1e-12).sum()),
                      switches_per_year=to_jsonable(switches / years),
                      latest_weights=to_jsonable(held.iloc[-1]), latest_month=held.index[-1].strftime("%Y-%m"))
    annual = annual_returns(dict(series))
    vols = {k: portfolios[k]["ann_vol"] for k in ["strategy"] + bench_keys}
    srri_5y = {k: srri_class(float(v.iloc[-60:].std() * math.sqrt(12))) for k, v in series}
    rep = data_report(data, cfg)
    rs = rolling_stats(bt["strategy"].net, bt["benchmarks"][prim].net, bt["rf"], cfg["rolling_window"])
    rsb = rolling_stats(bt["benchmarks"][prim].net, bt["benchmarks"][prim].net, bt["rf"], cfg["rolling_window"])
    out = dict(
        meta=dict(strategy_name=strat_name, group="BP", engine_version=ENGINE_VERSION,
                  generated_at=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
                  data_retrieved_at=data["retrieved_at"], base_ccy=cfg["base_ccy"],
                  sample_start=bt["index"][0].strftime("%Y-%m"), sample_end=bt["index"][-1].strftime("%Y-%m"),
                  start_value_date=(bt["index"][0] - pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d"),
                  n_months=len(bt["index"]), n_years=len(bt["index"]) / PERIODS, frequency="monthly",
                  primary_benchmark=prim, benchmarks=bench_keys, sources=data["sources"],
                  config=cfg),
        data_verification=rep.to_dict(orient="index"),
        portfolios=portfolios, relative_to_second_benchmark=vs_second, relative_to_market=vs_market,
        costs=costs, breakeven_cost_bps=be, allocation=allocation,
        annual_returns={str(y): r for y, r in annual.to_dict(orient="index").items()},
        risk_indicator=dict(srri_full_sample={k: srri_class(v) for k, v in vols.items()}, srri_last_5y=srri_5y,
                            ann_vol_full_sample=vols,
                            method="UCITS SRRI volatility bands (CESR/10-673) on monthly returns; indicative, "
                                   "not the PRIIPs SRI"),
        robustness=dict(costs=rob["costs"], signal_lag=rob["lag"],
                        rebalancing=rob["rebalancing"].to_dict(orient="records"),
                        subperiods=rob["subperiods"].to_dict(orient="records"),
                        crises=rob["crises"].reset_index().to_dict(orient="records"),
                        currency=rob["currency"].to_dict(orient="records"), sma_months=rob["sma_months"]),
        rolling=dict(window=cfg["rolling_window"], sharpe_min=float(rs["rolling_sharpe"].min()),
                     sharpe_max=float(rs["rolling_sharpe"].max()), sharpe_last=float(rs["rolling_sharpe"].iloc[-1]),
                     beta_min=float(rs["rolling_beta"].min()), beta_max=float(rs["rolling_beta"].max()),
                     beta_last=float(rs["rolling_beta"].iloc[-1]),
                     share_windows_sharpe_above_benchmark=float(
                         (rs["rolling_sharpe"] > rsb["rolling_sharpe"].reindex(rs.index)).mean())),
        monte_carlo=dict(n_paths=mc["n_paths"], years=mc["n_months"] / PERIODS, block_months=mc["block"],
                         initial_eur=mc["initial"], seed=mc["seed"], columns=mc["columns"], summary=mc["summary"]),
        motivation=({k: v for k, v in mot.items() if k != "series"} if mot else {}),
        tests=tests.to_dict(orient="records"),
        tests_all_pass=bool((tests["result"] == "PASS").all()),
    )
    if extra:
        out.update(extra)
    return to_jsonable(out)
