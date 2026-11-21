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
Importing this module has no side effects (no downloads, prints or plots).
"""
from __future__ import annotations

import copy
import hashlib
import io
import math
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ENGINE_VERSION = "2.0.0"
CASH = "CASH"
PERIODS = 12  # monthly data: 12 periods per year

# The proposed strategy (masterplan sections 3b and 12). The group edits only this dictionary.
DEFAULT_CONFIG = dict(
    strategy_name="BP Trend-Guarded Multi-Asset",
    # Backtest proxies with long Yahoo histories; the UCITS funds an EU investor would buy are in `ucits`.
    tickers=["SPY", "EFA", "IEF", "VNQ", "DBC"],
    asset_names={
        "SPY": "US equity (S&P 500)",
        "EFA": "Developed ex-US equity (MSCI EAFE)",
        "IEF": "US Treasuries 7-10y (EUR-hedged)",
        "VNQ": "US real estate (REITs)",
        "DBC": "Broad commodities",
    },
    rule="sma_trend",        # "sma_trend" (Faber 2007) | "fixed" | "equal" | "inverse_vol"
    weights=None,            # sleeve / base weights {ticker: w}; None = equal capital weights 1/n
    sma_window=10,           # months, taken from Faber (2007), not optimised
    signal_on="USD",         # "USD": signal on the asset's own USD price (the published rule) | "base"
    vol_window=36,           # only used by rule "inverse_vol"
    rebalance="M",           # "M" | "Q" | "A" | "none" | float drift threshold, e.g. 0.05
    benchmarks={
        "B1_equal_weight": dict(label="B1 Equal weight 1/n", weights=None, rebalance="M"),  # None = 1/n of tickers
        "B2_60_40": dict(label="B2 Classic 60/40", weights={"SPY": 0.36, "EFA": 0.24, "IEF": 0.40}, rebalance="M"),
    },
    primary_benchmark="B1_equal_weight",
    market_ticker="SPY",     # extra: beta against US equity
    start="2007-01-01",      # first return month (explicit, brief R19); value 1.0 sits at 2006-12-31
    end="2025-12-31",        # last return month; full calendar years (ESMA para 44)
    warmup_start="2006-02-01",   # first month needed for the first 10-month average (DBC inception)
    history_start="1990-01-01",  # download start, so inception dates are measured, not assumed
    base_ccy="EUR",          # "EUR" (USD assets converted unhedged, bonds hedged) | "USD"
    hedge_tickers=["IEF"],   # bond sleeve EUR-hedged in the EUR view: r_USD + (rf_EUR - rf_USD)
    rf_sources={"EUR": "ECB EONIA to 2019-09, then euro short-term rate (EUR STR); monthly average",
                "USD": "FRED TB3MS, 3-month T-bill, shifted one month (rate known at the start)"},
    fx_series="DEXUSEU",     # FRED, USD per EUR, end of month
    cost_bps=10.0,           # one-way, bps of traded value (fund-level base case)
    cost_grid=[0, 10, 25, 50],   # 50 bps = the lecture's conservative retail all-in figure
    benchmark_costs=True,    # benchmarks pay the same cost on their own rebalancing trades
    signal_lag=1,            # 1 = signal on the month-end close, earned next month (Faber); 2 = one month later
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
    sma_stability=[6, 8, 10, 12],
    sma_stability_start="2007-02-01",  # common sample: the 12-month average needs one more month of DBC
    rolling_window=36,
    mc_paths=10000, mc_years=10, mc_block=12, mc_block_alternatives=[6, 24],
    mc_initial=10000.0, mc_seed=2270,
    sri_rhp_years=10,        # recommended holding period = client horizon
    ucits={                  # implementation (R1 section 3.2, justETF, 2026-11-20); TER as decimal
        "SPY": dict(ticker="SXR8", isin="IE00B5BMR087", name="iShares Core S&P 500 UCITS ETF (Acc)", ter=0.0007),
        "EFA": dict(ticker="EXUS", isin="IE0006WW1TQ4", name="Xtrackers MSCI World ex USA UCITS ETF 1C",
                    ter=0.0015),
        "IEF": dict(ticker="IBB1", isin="IE00BGPP6697",
                    name="iShares $ Treasury Bond 7-10yr UCITS ETF EUR Hedged (Dist)", ter=0.0010),
        "VNQ": dict(ticker="IQQ7", isin="IE00B1FZSF77", name="iShares US Property Yield UCITS ETF", ter=0.0040),
        "DBC": dict(ticker="SXRS", isin="IE00BDFL4P12", name="iShares Diversified Commodity Swap UCITS ETF",
                    ter=0.0019),
        CASH: dict(ticker="XEON", isin="LU0290358497", name="Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C",
                   ter=0.0010),
    },
    price_source="auto",     # "auto" (yfinance, then Yahoo chart API, same data) | "yfinance" | "yahoo_chart"
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
    """SHA-256 of the engine source (line endings normalised): proves notebook and app run the same code."""
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
    # Monthly series (FRED, ECB) are labelled with the first day of the month; map every label to month-end.
    idx = pd.DatetimeIndex(idx)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize() + pd.offsets.MonthEnd(0)


def benchmark_weights(cfg: dict, key: str) -> dict:
    """Weights of a benchmark; None means 1/n over the strategy's own tickers (B1 follows the universe)."""
    w = cfg["benchmarks"][key].get("weights")
    return {t: 1.0 / len(cfg["tickers"]) for t in cfg["tickers"]} if w is None else dict(w)


def bench_label(cfg: dict, key: str) -> str:
    return cfg["benchmarks"][key].get("label", key)


# %% [engine 2/8] data: Yahoo prices, ECB/FRED rates, FRED FX
# Yahoo wants a browser-like User-Agent; FRED stalls on exactly that, so headers are set per host.
_UA_YAHOO = {"User-Agent": "Mozilla/5.0"}


def _http_get(url: str, params: dict | None = None, retries: int = 4, timeout: int = 30,
              headers: dict | None = None):
    import requests  # lazy import: the module imports even where requests is missing
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:  # network hiccup or rate limit: back off and retry
            last = e
        time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"Download failed after {retries} tries: {url} ({last}). The data provider is "
                       f"unreachable or rate-limiting; wait a minute and run the cell again.")


def _fetch_yfinance(tickers: list, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    try:  # yfinance >= 1.0: retry transient errors and raise instead of silently returning NaN
        yf.config.network.retries = 3
        yf.config.debug.hide_exceptions = False
    except AttributeError:
        pass
    # auto_adjust=True (passed explicitly): Close is split- and dividend-adjusted, i.e. total return.
    # yfinance treats `end` as exclusive, so ask for one day more to include END itself.
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(tickers, start=start, end=end_excl, interval="1d", auto_adjust=True,
                      progress=False, threads=False)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    raw = raw.copy()  # yfinance >= 1.2 can return read-only frames under pandas 3
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = tickers[:1]
    idx = pd.DatetimeIndex(close.index)
    close.index = idx.tz_localize(None) if idx.tz is not None else idx
    return close.reindex(columns=tickers)


def _fetch_yahoo_chart(ticker: str, start: str, end: str) -> pd.Series:
    # Same Yahoo endpoint and adjusted close that yfinance uses; a second route to the same source.
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
    r = _http_get(f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
                  params=dict(period1=p1, period2=p2, interval="1d", events="div,split",
                              includeAdjustedClose="true"), headers=_UA_YAHOO)
    res = r.json()["chart"]["result"][0]
    tzname = res["meta"].get("exchangeTimezoneName", "America/New_York")
    dates = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(tzname)
    dates = dates.tz_localize(None).normalize()
    s = pd.Series(res["indicators"]["adjclose"][0]["adjclose"], index=dates, dtype="float64", name=ticker)
    return s[~s.index.duplicated(keep="last")].dropna()


def fetch_prices_daily(tickers: list, start: str, end: str, source: str = "auto"):
    """Daily adjusted close (USD) for all tickers. Returns (DataFrame, {ticker: route used})."""
    out, used = {}, {}
    if source in ("auto", "yfinance"):
        try:
            px = _fetch_yfinance(tickers, start, end)
            for t in tickers:
                if t in px and px[t].notna().sum() > 0:
                    out[t] = px[t].dropna()
                    used[t] = "Yahoo Finance via yfinance"
        except Exception as e:
            if source == "yfinance":
                raise
            print(f"NOTE: yfinance failed ({type(e).__name__}: {e}). Retrying the same Yahoo data via its chart API.")
    for t in tickers:
        if t not in out:
            if source == "yfinance":
                raise RuntimeError(f"yfinance returned no data for {t}")
            out[t] = _fetch_yahoo_chart(t, start, end)
            used[t] = "Yahoo Finance via chart API"
    px = pd.DataFrame(out).sort_index()
    return px.reindex(columns=tickers), used


def fetch_fred(series_id: str, **extra) -> pd.Series:
    """Key-less FRED download (fredgraph.csv), as in the W3 API lecture."""
    r = _http_get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id, **extra})
    df = pd.read_csv(io.StringIO(r.text), na_values=["."])
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df.iloc[:, 0]), name=series_id)
    return s.dropna()


def fetch_ecb(key: str, start: str = "1999-01") -> pd.Series:
    """Key-less ECB Data Portal download (CSV): columns TIME_PERIOD, OBS_VALUE."""
    r = _http_get(f"https://data-api.ecb.europa.eu/service/data/{key}",
                  params={"format": "csvdata", "startPeriod": start})
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df["TIME_PERIOD"]), name=key)
    return s.dropna().sort_index()


def annual_pct_to_monthly(rate_pct: pd.Series) -> pd.Series:
    """Annual rate in % -> monthly simple return, compounding-consistent: (1 + x/100)^(1/12) - 1."""
    return (1.0 + rate_pct / 100.0) ** (1.0 / PERIODS) - 1.0


def load_eur_overnight() -> pd.Series:
    """EUR cash rate a retail money-market fund earns: EONIA monthly average up to 2019-09, EUR STR after.
    Overnight (not 3m Euribor): Euribor carries a bank credit spread that would flatter the cash sleeve in 2008."""
    eonia = fetch_ecb("FM/M.U2.EUR.4F.MM.EONIA.HSTA")
    estr = fetch_ecb("FM/M.U2.EUR.4F.MM.UONSTR.HSTA")
    eonia.index = _to_month_end_index(eonia.index)
    estr.index = _to_month_end_index(estr.index)
    switch = pd.Timestamp("2019-10-31")
    return pd.concat([eonia[eonia.index < switch], estr[estr.index >= switch]]).sort_index()


def load_data(cfg: dict) -> dict:
    """Download everything once (prices, rates, FX). Returns raw monthly inputs; returns are built later."""
    tickers = list(dict.fromkeys(list(cfg["tickers"]) + [cfg["market_ticker"]] +
                                 [t for k in cfg["benchmarks"] for t in benchmark_weights(cfg, k)]))
    end = cfg["end"]
    px_d, used = fetch_prices_daily(tickers, cfg["history_start"], end, cfg.get("price_source", "auto"))
    for t in tickers:  # yfinance can fail silently: assert every series really arrived and is long enough
        s = px_d[t].dropna()
        if s.empty:
            raise RuntimeError(f"No price data for {t}. Yahoo may be rate-limiting; run the cell again.")
        if s.index[0] > pd.Timestamp(cfg["warmup_start"]) + pd.offsets.MonthEnd(1):
            raise RuntimeError(f"{t} starts {s.index[0]:%Y-%m-%d}, after the warm-up start {cfg['warmup_start']}.")
    first_daily = {t: px_d[t].first_valid_index().strftime("%Y-%m-%d") for t in tickers}
    # Month-end price = last daily adjusted close of the month (avoids Yahoo's monthly-bar quirks).
    px_m = px_d.resample(ME).last()
    px_m.index = _to_month_end_index(px_m.index)
    counts = px_d.resample(ME).count()
    counts.index = px_m.index
    px_m = px_m.where(counts > 0)  # a month only counts if the ticker traded in it (nothing carried forward)
    px_m = px_m.loc[: pd.Timestamp(end) + pd.offsets.MonthEnd(0)]

    rf_eur = annual_pct_to_monthly(load_eur_overnight())     # realised accrual in month t: no shift
    tb3 = fetch_fred("TB3MS")
    tb3.index = _to_month_end_index(tb3.index)
    rf_usd = annual_pct_to_monthly(tb3).shift(1)               # 3m yield set at the start of the month
    try:
        fx = fetch_fred(cfg["fx_series"], fq="Monthly", fam="eop")
        fx_src = f"FRED {cfg['fx_series']} (USD per EUR, end of month)"
    except RuntimeError:
        fx = fetch_ecb("EXR/D.USD.EUR.SP00.A").resample(ME).last()
        fx_src = "ECB EXR D.USD.EUR.SP00.A (USD per EUR, last daily fixing of the month)"
    fx.index = _to_month_end_index(fx.index)
    sources = {"prices": used, "rf_EUR": cfg["rf_sources"]["EUR"], "rf_USD": cfg["rf_sources"]["USD"],
               "fx": fx_src}
    return dict(prices_usd=px_m, fx_usd_per_eur=fx, rf={"EUR": rf_eur, "USD": rf_usd}, first_daily=first_daily,
                n_daily_rows={t: int(px_d[t].notna().sum()) for t in tickers}, sources=sources,
                retrieved_at=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"))


def synthetic_data(cfg: dict | None = None, seed: int = 7, start: str = "2000-01-31",
                   end: str = "2025-12-31") -> dict:
    """Random-walk inputs with the same structure as load_data(): offline tests without a network."""
    cfg = cfg or get_config()
    rng = np.random.default_rng(seed)
    idx = _to_month_end_index(pd.date_range(start, end, freq=ME))
    tickers = list(dict.fromkeys(list(cfg["tickers"]) + [cfg["market_ticker"]] +
                                 [t for k in cfg["benchmarks"] for t in benchmark_weights(cfg, k)]))
    rets = rng.normal(0.006, 0.045, size=(len(idx), len(tickers)))
    px = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=tickers)
    fx = pd.Series(1.2 * np.cumprod(1 + rng.normal(0, 0.02, len(idx))), index=idx)
    rf = {"EUR": pd.Series(0.0015, index=idx), "USD": pd.Series(0.002, index=idx)}
    return dict(prices_usd=px, fx_usd_per_eur=fx, rf=rf, first_daily={t: idx[0].strftime("%Y-%m-%d") for t in tickers},
                n_daily_rows={t: len(idx) for t in tickers},
                sources={"prices": {t: "synthetic" for t in tickers}, "rf_EUR": "synthetic", "rf_USD": "synthetic",
                         "fx": "synthetic"}, retrieved_at="synthetic")


def snapshot_frame(data: dict) -> pd.DataFrame:
    """All raw monthly inputs in one table (for the app's offline fallback and for audits)."""
    df = data["prices_usd"].copy()
    df["FX_USDperEUR"] = data["fx_usd_per_eur"].reindex(df.index)
    df["RF_EUR_monthly"] = data["rf"]["EUR"].reindex(df.index)
    df["RF_USD_monthly_shifted"] = data["rf"]["USD"].reindex(df.index)
    return df


def base_ccy_prices(data: dict, ccy: str) -> pd.DataFrame:
    """Month-end prices in the investor's currency. EUR value of a USD asset = USD price / (USD per EUR),
    so r_EUR = (1 + r_USD) * S_{t-1} / S_t - 1 with S = USD per EUR."""
    px = data["prices_usd"]
    if ccy == "USD":
        return px.copy()
    if ccy == "EUR":
        return px.div(data["fx_usd_per_eur"].reindex(px.index), axis=0)
    raise ValueError("base_ccy must be 'EUR' or 'USD'")


def asset_returns(data: dict, cfg: dict, ccy: str | None = None) -> pd.DataFrame:
    """Monthly simple returns in the base currency for every downloaded ticker, plus CASH = rf."""
    ccy = ccy or cfg["base_ccy"]
    r = base_ccy_prices(data, ccy).pct_change(fill_method=None)  # never invent a return across a gap
    if ccy == "EUR":
        # Hedged bond sleeve (covered-interest-parity approximation): USD return plus the rate differential.
        diff = data["rf"]["EUR"].reindex(r.index) - data["rf"]["USD"].reindex(r.index)
        for t in cfg.get("hedge_tickers") or []:
            r[t] = data["prices_usd"][t].pct_change(fill_method=None) + diff
    r[CASH] = data["rf"][ccy].reindex(r.index)
    return r


def window_index(index: pd.DatetimeIndex, start: str, end: str) -> pd.DatetimeIndex:
    s = pd.Timestamp(start) + pd.offsets.MonthEnd(0)
    e = pd.Timestamp(end) + pd.offsets.MonthEnd(0)
    return index[(index >= s) & (index <= e)]


def data_report(data: dict, cfg: dict) -> pd.DataFrame:
    """The lecture's checks per series (shape, date range, missing values; the plot is in the notebook),
    plus a fingerprint (sum of month-end prices) that changes if Yahoo ever revises history."""
    r = asset_returns(data, cfg)
    win = window_index(r.index, cfg["start"], cfg["end"])
    rows = []
    for t in list(data["prices_usd"].columns):
        p = data["prices_usd"][t]
        rw = r.loc[win, t]
        rows.append(dict(series=t, first_daily_price=data["first_daily"].get(t),
                         daily_rows=data.get("n_daily_rows", {}).get(t),
                         first_month_end=p.first_valid_index().strftime("%Y-%m"),
                         last_month_end=p.last_valid_index().strftime("%Y-%m"),
                         months_in_window=int(rw.notna().sum()), missing_in_window=int(rw.isna().sum()),
                         min_monthly_return=float(rw.min()), max_monthly_return=float(rw.max()),
                         fingerprint=round(float(p.loc[win].sum()), 4), source=data["sources"]["prices"].get(t)))
    for ccy in ("EUR", "USD"):
        s = data["rf"][ccy]
        sw = s.reindex(win)
        rows.append(dict(series=f"rf {ccy}", first_month_end=s.dropna().index.min().strftime("%Y-%m"),
                         last_month_end=s.dropna().index.max().strftime("%Y-%m"),
                         months_in_window=int(sw.notna().sum()), missing_in_window=int(sw.isna().sum()),
                         min_monthly_return=float(sw.min()), max_monthly_return=float(sw.max()),
                         fingerprint=round(float(sw.sum()), 6), source=data["sources"][f"rf_{ccy}"]))
    fx = data["fx_usd_per_eur"]
    fw = fx.reindex(win)
    rows.append(dict(series="FX USD per EUR", first_month_end=fx.index.min().strftime("%Y-%m"),
                     last_month_end=fx.index.max().strftime("%Y-%m"), months_in_window=int(fw.notna().sum()),
                     missing_in_window=int(fw.isna().sum()), fingerprint=round(float(fw.sum()), 4),
                     source=data["sources"]["fx"]))
    return pd.DataFrame(rows).set_index("series")


# %% [engine 3/8] allocation rules (information up to t - lag only)
def base_weights(cfg: dict) -> pd.Series:
    tick = list(cfg["tickers"])
    if cfg.get("weights"):
        w = pd.Series({t: float(cfg["weights"].get(t, 0.0)) for t in tick})
    else:
        w = pd.Series(1.0 / len(tick), index=tick)
    if (w < -1e-12).any() or w.sum() <= 0:
        raise ValueError("Weights must be non-negative with a positive sum (no shorting).")
    return w / w.sum()  # renormalise so app sliders can never break the sum-to-one rule


def sma_signal(prices: pd.DataFrame, months: int) -> pd.DataFrame:
    """1.0 if the month-end price is above its own `months`-month simple moving average, else 0.0.
    The average includes the current month-end, exactly as in Faber (2007). NaN = not enough history."""
    sma = prices.rolling(months, min_periods=months).mean()
    return (prices > sma).astype(float).where(sma.notna())


def held_signals(cfg: dict, data: dict, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Signal used during each holding month t: computed at month-end t - signal_lag (the lecture's shift)."""
    tick = list(cfg["tickers"])
    px = data["prices_usd"][tick] if cfg.get("signal_on", "USD") == "USD" else base_ccy_prices(data, cfg["base_ccy"])[tick]
    sig = sma_signal(px, int(cfg["sma_window"])).shift(int(cfg["signal_lag"])).reindex(index)
    if sig.isna().any().any():
        bad = sig.index[sig.isna().any(axis=1)][0]
        raise ValueError(f"Not enough price history for a {cfg['sma_window']}-month average at {bad:%Y-%m} "
                         f"(an asset is too young). Choose a later start date.")
    return sig


def target_weights(cfg: dict, data: dict, index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Target weights for each HOLDING month (rows) over tickers + CASH, using data up to t - signal_lag."""
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
    elif rule == "sma_trend":
        w = held_signals(cfg, data, index).mul(w0, axis=1)
    elif rule == "inverse_vol":
        vol = r[tick].rolling(int(cfg["vol_window"]), min_periods=int(cfg["vol_window"])).std()
        inv = (1.0 / vol).shift(lag).reindex(index)
        if inv.isna().any().any():
            raise ValueError("Not enough history for inverse-volatility weights. Choose a later start date.")
        w = inv.div(inv.sum(axis=1), axis=0)
    else:
        raise ValueError(f"Unknown rule: {rule}")
    w[CASH] = (1.0 - w.sum(axis=1)).clip(lower=0.0)
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
    held: pd.DataFrame         # weights held during month t (after trading at its start), incl. CASH
    drift: pd.DataFrame        # weights just before trading at the start of month t (drifted)
    traded: pd.Series          # sum over ETFs of |weight change| at the start of month t (cost base)
    turnover: pd.Series        # one-way turnover = 1/2 sum |weight change| incl. cash
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
    if rebalance in ("none", None) or isinstance(rebalance, (int, float)):
        return False  # thresholds are decided on drift inside the simulation
    raise ValueError(f"Unknown rebalance setting: {rebalance}")


def _is_threshold(rebalance) -> bool:
    return isinstance(rebalance, (int, float)) and not isinstance(rebalance, bool)


def _package(name, ix, cols, held, drift, gross, risky, cost_bps) -> SimResult:
    traded = np.abs(held - drift)[:, risky].sum(axis=1)
    turnover = 0.5 * np.abs(held - drift).sum(axis=1)
    cost = cost_bps / 1e4 * traded
    net = (1.0 - cost) * (1.0 + gross) - 1.0
    return SimResult(name=name, net=pd.Series(net, ix, name=name), gross=pd.Series(gross, ix, name=name),
                     held=pd.DataFrame(held, ix, cols), drift=pd.DataFrame(drift, ix, cols),
                     traded=pd.Series(traded, ix), turnover=pd.Series(turnover, ix), cost=pd.Series(cost, ix),
                     rebalanced=pd.Series(traded > 1e-15, ix), cost_bps=float(cost_bps))


def _returns_matrix(returns: pd.DataFrame, index, cols) -> np.ndarray:
    R = returns.reindex(index=index, columns=cols).to_numpy(dtype=float)
    if np.isnan(R).any():
        bad = index[np.isnan(R).any(axis=1)][0]
        missing = [c for c, v in zip(cols, np.isnan(R[index.get_loc(bad)])) if v]
        raise ValueError(f"Missing returns at {bad:%Y-%m} for {missing}")
    return R


def simulate(returns: pd.DataFrame, target: pd.DataFrame, rebalance="M", cost_bps: float = 0.0,
             name: str = "portfolio") -> SimResult:
    """Fixed-target portfolio (benchmarks, fixed or inverse-vol rules), simulated month by month.

    At the start of month t the portfolio holds drifted weights d_t. On a trading date it trades to the
    target w_t. During the month the held weights earn the asset returns and drift:
    d_{t+1} = h_t (1 + r_t) / (1 + R_t). The first month forms the portfolio at target without cost,
    identically for every portfolio."""
    cols = list(target.columns)
    R = _returns_matrix(returns, target.index, cols)
    W = target.to_numpy(dtype=float)
    T, N = W.shape
    held = np.zeros((T, N)); drift = np.zeros((T, N)); gross = np.zeros(T)
    d = W[0].copy()
    for t in range(T):
        do = t == 0 or _is_scheduled(target.index[t], rebalance)
        if _is_threshold(rebalance) and t > 0:
            do = do or np.max(np.abs(d - W[t])) > float(rebalance)
        h = W[t].copy() if do else d.copy()
        drift[t], held[t] = d, h
        gross[t] = float(h @ R[t])
        d = h * (1.0 + R[t]) / (1.0 + gross[t])
    risky = np.array([c != CASH for c in cols])
    return _package(name, target.index, cols, held, drift, gross, risky, cost_bps)


def simulate_sleeves(returns: pd.DataFrame, signals: pd.DataFrame, base: pd.Series, rebalance="M",
                     cost_bps: float = 0.0, name: str = "strategy") -> SimResult:
    """Faber trend rule with per-sleeve accounting (masterplan S8).

    Each asset owns a sleeve. A sleeve sits fully in its asset while the signal is 1 and fully in EUR cash
    while it is 0; signals are checked every month. On scheduled dates ("M", "Q", "A" or a drift threshold)
    sleeves are reset to their base weights; in between each sleeve drifts with its own asset or cash."""
    tick = list(signals.columns)
    cols = tick + [CASH]
    R = _returns_matrix(returns, signals.index, cols)
    S = signals.to_numpy(dtype=float)
    w0 = base.reindex(tick).to_numpy(dtype=float)
    T, n = S.shape
    held = np.zeros((T, n + 1)); drift = np.zeros((T, n + 1)); gross = np.zeros(T)
    v = w0.copy()            # sleeve values as a share of the portfolio at the start of the month
    inv = S[0].copy()        # month 1: formed directly at target (no cost, like every portfolio)
    for t in range(T):
        pre = np.append(v * inv, (v * (1 - inv)).sum())
        reset = t == 0 or _is_scheduled(signals.index[t], rebalance)
        if _is_threshold(rebalance) and t > 0:
            reset = reset or np.max(np.abs(v - w0)) > float(rebalance)
        if reset:
            v = w0.copy()
        inv = S[t]
        post = np.append(v * inv, (v * (1 - inv)).sum())
        drift[t], held[t] = (post if t == 0 else pre), post
        sleeve_r = np.where(inv > 0.5, R[t, :n], R[t, n])
        gross[t] = float(v @ sleeve_r)
        v = v * (1.0 + sleeve_r) / (1.0 + gross[t])
    risky = np.array([c != CASH for c in cols])
    return _package(name, signals.index, cols, held, drift, gross, risky, cost_bps)


def net_from_gross(sim: SimResult, cost_bps: float) -> pd.Series:
    """Net returns for any other cost level. Exact, because costs are proportional and do not change weights."""
    return (1.0 - cost_bps / 1e4 * sim.traded) * (1.0 + sim.gross) - 1.0


def run_backtest(cfg: dict, data: dict) -> dict:
    """Strategy + benchmarks over the configured window, in the configured base currency. No network."""
    r = asset_returns(data, cfg)
    idx = window_index(r.index, cfg["start"], cfg["end"])
    if len(idx) < 24:
        raise ValueError("Backtest window shorter than 24 months.")
    if cfg["rule"] == "sma_trend":
        sig = held_signals(cfg, data, idx)
        strat = simulate_sleeves(r, sig, base_weights(cfg), cfg["rebalance"], cfg["cost_bps"], cfg["strategy_name"])
        tgt = sig.mul(base_weights(cfg), axis=1)
        tgt[CASH] = 1.0 - tgt.sum(axis=1)
    else:
        sig = None
        tgt = target_weights(cfg, data, idx)
        strat = simulate(r, tgt, cfg["rebalance"], cfg["cost_bps"], cfg["strategy_name"])
    bms = {}
    for k, b in cfg["benchmarks"].items():
        bms[k] = simulate(r, fixed_target(benchmark_weights(cfg, k), idx), b.get("rebalance", "M"),
                          cfg["cost_bps"] if cfg.get("benchmark_costs", True) else 0.0, bench_label(cfg, k))
    market = r.loc[idx, cfg["market_ticker"]].rename(f"{cfg['market_ticker']} ({cfg['base_ccy']})")
    return dict(cfg=cfg, returns=r.loc[idx], rf=r.loc[idx, CASH].rename("rf"), target=tgt, signals=sig,
                strategy=strat, benchmarks=bms, primary=cfg["primary_benchmark"], market=market, index=idx)


def wealth_index(r: pd.Series, start_value: float = 1.0) -> pd.Series:
    """Cumulative value of 1 invested, with an explicit start row one month before the first return,
    so every series starts at exactly 1.0 on the same date (brief requirement)."""
    r = r.dropna()
    w = start_value * (1.0 + r).cumprod()
    start_row = pd.Series([start_value], index=[r.index[0] - pd.offsets.MonthEnd(1)])
    return pd.concat([start_row, w]).rename(r.name)


# %% [engine 5/8] performance metrics (course definitions)
def drawdown(r: pd.Series) -> pd.Series:
    """DD_t = V_t / HWM_t - 1 (negative number), HWM = running high incl. the start value 1 (W3, Pedersen)."""
    v = wealth_index(r)
    return v / v.cummax() - 1.0


def max_drawdown_info(r: pd.Series) -> dict:
    dd = drawdown(r)
    trough = dd.idxmin()
    peak = dd.loc[:trough][dd.loc[:trough] == 0].index.max()
    after = dd.loc[trough:]
    rec = after[after >= -1e-12].index.min() if (after >= -1e-12).any() else None
    recovered = rec is not None and not pd.isna(rec)
    under = (dd < -1e-12).astype(int).to_numpy()
    longest = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)

    def months(a, b):
        return int((b.year - a.year) * 12 + b.month - a.month)
    return dict(max_drawdown=float(dd.min()), peak=peak.strftime("%Y-%m"), trough=trough.strftime("%Y-%m"),
                recovery=rec.strftime("%Y-%m") if recovered else None,
                months_peak_to_trough=months(peak, trough),
                months_trough_to_recovery=months(trough, rec) if recovered else None,
                longest_underwater_months=int(longest))


def _ols(y: np.ndarray, x: np.ndarray, nw_lags: int = 6) -> dict:
    """OLS y = a + b x with classic and Newey-West (HAC, Bartlett) standard errors, hand-coded."""
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    coef = XtX_inv @ X.T @ y
    e = y - X @ coef
    s2 = float(e @ e) / (n - 2)
    se = np.sqrt(np.diag(XtX_inv) * s2)
    # Newey-West: monthly returns can be autocorrelated; a robust t-stat guards against overconfidence.
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, nw_lags + 1):
        G = Xe[L:].T @ Xe[:-L]
        S += (1.0 - L / (nw_lags + 1.0)) * (G + G.T)
    se_nw = np.sqrt(np.diag(XtX_inv @ S @ XtX_inv))
    tss = float(((y - y.mean()) ** 2).sum())
    return dict(alpha=float(coef[0]), beta=float(coef[1]), se_alpha=float(se[0]), se_beta=float(se[1]),
                se_alpha_nw=float(se_nw[0]), resid_std=math.sqrt(s2), r2=1.0 - float(e @ e) / tss if tss > 0 else np.nan)


def perf_metrics(r: pd.Series, rb: pd.Series | None, rf: pd.Series) -> dict:
    """All metrics from monthly simple returns. rb = benchmark for alpha, beta, IR (None: absolute only)."""
    r = r.astype(float); rf = rf.reindex(r.index).astype(float)
    ex = r - rf
    n = len(r)
    sr_m = ex.mean() / ex.std() if ex.std() > 0 else np.nan
    m = dict(months=n,
             ann_return=float(PERIODS * r.mean()),                          # arithmetic mean x12 (brief)
             cagr=float((1.0 + r).prod() ** (PERIODS / n) - 1.0),
             final_wealth=float((1.0 + r).prod()),
             ann_vol=float(math.sqrt(PERIODS) * r.std()),                   # x sqrt(12)
             ann_excess_return=float(PERIODS * ex.mean()),
             sharpe=float(math.sqrt(PERIODS) * sr_m),
             # Lo (2002): the Sharpe ratio is an estimate; its standard error for iid returns.
             sharpe_se=float(math.sqrt(PERIODS) * math.sqrt((1 + 0.5 * sr_m ** 2) / n)))
    downside = np.minimum(ex.to_numpy(), 0.0)
    dsd = math.sqrt((downside ** 2).mean())
    m["sortino"] = float(math.sqrt(PERIODS) * ex.mean() / dsd) if dsd > 0 else np.nan
    m.update(max_drawdown_info(r))
    m["calmar"] = float(m["cagr"] / abs(m["max_drawdown"])) if m["max_drawdown"] < 0 else np.nan
    roll12 = (1.0 + r).rolling(12).apply(np.prod, raw=True) - 1.0
    m.update(worst_12m=float(roll12.min()), best_12m=float(roll12.max()), worst_month=float(r.min()),
             best_month=float(r.max()), pct_positive_months=float((r > 0).mean()))
    if rb is not None:
        rb = rb.reindex(r.index).astype(float)
        exb = rb - rf
        beta = float(np.cov(ex, exb, ddof=1)[0, 1] / np.var(exb, ddof=1))  # course formula cov/var
        reg = _ols(ex.to_numpy(), exb.to_numpy())
        active = r - rb
        te = float(active.std())
        ok = reg["resid_std"] > 1e-12  # a portfolio against itself: zero residuals, t-stats undefined
        m.update(beta=beta,                                                # NOT annualised (brief)
                 alpha_monthly=float(ex.mean() - beta * exb.mean()),
                 alpha_ann=float(PERIODS * (ex.mean() - beta * exb.mean())),  # x12
                 alpha_t=float(reg["alpha"] / reg["se_alpha"]) if ok else np.nan,
                 alpha_t_nw=float(reg["alpha"] / reg["se_alpha_nw"]) if ok else np.nan,
                 r_squared=reg["r2"], correlation=float(np.corrcoef(r, rb)[0, 1]),
                 tracking_error=float(math.sqrt(PERIODS) * te),
                 information_ratio=float(math.sqrt(PERIODS) * active.mean() / te) if te > 1e-15 else np.nan,
                 information_ratio_regression=float(math.sqrt(PERIODS) * reg["alpha"] / reg["resid_std"])
                 if ok else np.nan,
                 ann_active_return=float(PERIODS * active.mean()),
                 hit_rate_vs_benchmark=float((active > 0).mean()) if te > 1e-15 else np.nan)
    return m


def turnover_stats(sim: SimResult) -> dict:
    """Turnover p.a. = 1/2 sum|dw| incl. cash (one-way, comparable to Faber's ~70%); costs on ETF trades."""
    years = len(sim.net) / PERIODS
    cagr_g = float((1 + sim.gross).prod() ** (1 / years) - 1)
    cagr_n = float((1 + sim.net).prod() ** (1 / years) - 1)
    return dict(turnover_pa=float(sim.turnover.sum() / years), traded_value_pa=float(sim.traded.sum() / years),
                months_with_trades_pa=float(sim.rebalanced.sum() / years), cost_drag_pa=cagr_g - cagr_n,
                cost_bps=sim.cost_bps, cagr_gross=cagr_g, cagr_net=cagr_n)


def _bisect_breakeven(gap, hi: float = 2000.0):
    if gap(0.0) <= 0:
        return None          # no edge even before costs
    if gap(hi) > 0:
        return math.inf      # edge survives any plausible cost
    lo, up = 0.0, hi
    for _ in range(80):
        mid = 0.5 * (lo + up)
        lo, up = (mid, up) if gap(mid) > 0 else (lo, mid)
    return 0.5 * (lo + up)


def breakeven_cost(strat: SimResult, bench: SimResult, rf: pd.Series | None = None, on: str = "cagr",
                   bench_pays: bool = True):
    """Cost (bps per one-way trade) at which the strategy's edge over the benchmark disappears.
    on="cagr": net CAGR equal; on="sharpe": net Sharpe equal (needs rf). Both portfolios pay the cost.
    None = no edge even at zero cost; inf = edge survives 2000 bps."""
    def stat(sim, c):
        x = net_from_gross(sim, c)
        if on == "cagr":
            return float((1 + x).prod())
        ex = x - rf.reindex(x.index)
        return float(ex.mean() / ex.std())
    return _bisect_breakeven(lambda c: stat(strat, c) - stat(bench, c if bench_pays else 0.0))


def metrics_table(bt: dict, benchmark: str | None = None) -> pd.DataFrame:
    """Table 1: strategy (net and gross) and every benchmark; relative metrics against `benchmark`."""
    bkey = benchmark or bt["primary"]
    rb = bt["benchmarks"][bkey].net
    rows = {f"{bt['strategy'].name} (net)": perf_metrics(bt["strategy"].net, rb, bt["rf"]),
            f"{bt['strategy'].name} (gross)": perf_metrics(bt["strategy"].gross, rb, bt["rf"])}
    for k, s in bt["benchmarks"].items():
        rows[s.name] = perf_metrics(s.net, rb, bt["rf"])
    return pd.DataFrame(rows).T


def headline(bt: dict) -> pd.DataFrame:
    """The six required measures in the brief's order, plus CAGR, max drawdown and turnover."""
    t = metrics_table(bt)
    cols = ["ann_return", "ann_vol", "sharpe", "alpha_ann", "alpha_t", "information_ratio", "beta", "cagr",
            "max_drawdown"]
    out = t[cols].astype(float)
    sims = [bt["strategy"], bt["strategy"]] + list(bt["benchmarks"].values())
    out["turnover_pa"] = [turnover_stats(s)["turnover_pa"] for s in sims]
    return out


def annual_returns(series: dict) -> pd.DataFrame:
    """Calendar-year compounded returns (net) for several monthly return series."""
    df = pd.DataFrame(series)
    return (1 + df).groupby(df.index.year).prod() - 1


def rolling_stats(r: pd.Series, rb: pd.Series, rf: pd.Series, window: int = 36) -> pd.DataFrame:
    """Rolling Sharpe (annualised) and beta (not annualised) on excess returns, past data only."""
    ex = r - rf; exb = rb - rf
    sharpe = math.sqrt(PERIODS) * ex.rolling(window).mean() / ex.rolling(window).std()
    beta = ex.rolling(window).cov(exb) / exb.rolling(window).var()
    return pd.DataFrame({"rolling_sharpe": sharpe, "rolling_beta": beta}).dropna()


def signal_events(bt: dict, start: str, end: str) -> list:
    """Every exit to cash and re-entry of each sleeve in a window (e.g. the 2020 V-shape)."""
    sig = bt["signals"]
    if sig is None:
        return []
    prev = sig.shift(1)
    ix = window_index(sig.index, start, end)
    ev = []
    for t in ix:
        for c in sig.columns:
            if not pd.isna(prev.loc[t, c]) and sig.loc[t, c] != prev.loc[t, c]:
                ev.append(dict(month_held=t.strftime("%Y-%m"), ticker=c,
                               action="exit to cash" if sig.loc[t, c] == 0 else "re-enter"))
    return ev


def sri_priips(r_monthly: pd.Series, rhp_years: int = 10) -> dict:
    """Indicative PRIIPs market-risk class (Delegated Reg. 2017/653, Annex II): Cornish-Fisher VaR 97.5%
    over the holding period from the last 60 monthly log returns, VaR-equivalent volatility (VEV),
    MRM bands, then +1 class because only monthly data are used (point 15)."""
    x = np.log1p(r_monthly.dropna().iloc[-60:].to_numpy(dtype=float))
    m1 = x.mean(); c = x - m1
    m2, m3, m4 = (c ** 2).mean(), (c ** 3).mean(), (c ** 4).mean()
    sigma = math.sqrt(m2); skew = m3 / sigma ** 3; exkurt = m4 / sigma ** 4 - 3.0
    N = rhp_years * PERIODS
    var_ret = sigma * math.sqrt(N) * (-1.96 + 0.474 * skew / math.sqrt(N) - 0.0687 * exkurt / N
                                      + 0.146 * skew ** 2 / N) - 0.5 * sigma ** 2 * N
    vev = (math.sqrt(3.842 - 2.0 * var_ret) - 1.96) / math.sqrt(rhp_years)
    bands = [0.005, 0.05, 0.12, 0.20, 0.30, 0.80]
    mrm = next((i for i, b in enumerate(bands, start=1) if vev < b), 7)
    return dict(vev=float(vev), mrm_class=int(mrm), sri_class=int(min(mrm + 1, 7)), skew=float(skew),
                excess_kurtosis=float(exkurt), months=int(len(x)), rhp_years=rhp_years)


def srri_class(ann_vol: float) -> int:
    """Old UCITS SRRI volatility bands (CESR/10-673), only for a footnote comparison."""
    return next((i for i, b in enumerate([0.005, 0.02, 0.05, 0.10, 0.15, 0.25], start=1) if ann_vol < b), 7)


# %% [engine 6/8] robustness and Monte Carlo
def _summary_row(sim_net, bench_net, rf):
    m = perf_metrics(sim_net, bench_net, rf)
    keys = ["cagr", "ann_return", "ann_vol", "sharpe", "max_drawdown", "alpha_ann", "information_ratio"]
    return {k: m.get(k, np.nan) for k in keys}


def robustness(cfg: dict, data: dict, bt: dict | None = None) -> dict:
    """Does the conclusion survive other reasonable choices? Each block changes ONE assumption."""
    bt = bt or run_backtest(cfg, data)
    rf = bt["rf"]; prim = bt["primary"]
    pb = bt["benchmarks"][prim]
    out = {}
    # 1. Cost grid (exact re-pricing of the same trades; the benchmark pays the same cost).
    rows = []
    for c in cfg["cost_grid"]:
        s = net_from_gross(bt["strategy"], c)
        b = net_from_gross(pb, c if cfg.get("benchmark_costs", True) else 0)
        rows.append(dict(cost_bps=c, **_summary_row(s, b, rf), final_wealth=float((1 + s).prod()),
                         benchmark_cagr=perf_metrics(b, None, rf)["cagr"],
                         benchmark_sharpe=perf_metrics(b, None, rf)["sharpe"]))
    out["costs"] = pd.DataFrame(rows).set_index("cost_bps")
    out["breakeven"] = {f"{k}_{on}": breakeven_cost(bt["strategy"], v, rf, on, cfg.get("benchmark_costs", True))
                        for k, v in bt["benchmarks"].items() for on in ("cagr", "sharpe")}

    def variant(label, **over):
        b2 = run_backtest(get_config(**{**cfg, **over}), data)
        return dict(variant=label, **_summary_row(b2["strategy"].net, b2["benchmarks"][prim].net, b2["rf"]),
                    turnover_pa=turnover_stats(b2["strategy"])["turnover_pa"],
                    benchmark_cagr=perf_metrics(b2["benchmarks"][prim].net, None, b2["rf"])["cagr"],
                    benchmark_sharpe=perf_metrics(b2["benchmarks"][prim].net, None, b2["rf"])["sharpe"])
    # 2. Timing: lag 1 (Faber) vs lag 2 (one month later, fully safe); lag 0 = look-ahead, shown as a warning.
    out["lag"] = pd.DataFrame([variant(f"lag {L}", signal_lag=L) for L in (1, 2)] +
                              [variant("lag 0 (look-ahead, NOT implementable)", signal_lag=0)]).set_index("variant")
    # 3. Rebalancing: the static benchmark (hidden-rebalancing check, Lecture 4.3) and the strategy's sleeves.
    rows = []
    for reb in ("M", "Q", "A", "none", 0.05):
        sim = simulate(bt["returns"], fixed_target(benchmark_weights(cfg, prim), bt["index"]), reb,
                       cfg["cost_bps"], pb.name)
        rows.append(dict(portfolio=pb.name, rebalance=str(reb), **_summary_row(sim.net, None, rf),
                         turnover_pa=turnover_stats(sim)["turnover_pa"]))
    for reb in ("M", "Q", "A"):
        v = variant(reb, rebalance=reb)
        for k in ("variant", "benchmark_cagr", "benchmark_sharpe"):
            v.pop(k)
        rows.append(dict(portfolio="Strategy", rebalance=reb, **v))
    out["rebalancing"] = pd.DataFrame(rows)
    # 4. Sub-periods: is the result driven by one episode?
    rows = []
    for s0, s1, label in cfg["subperiods"]:
        ix = window_index(bt["index"], s0, s1)
        for name, ser in [("Strategy", bt["strategy"].net)] + [(v.name, v.net) for v in bt["benchmarks"].values()]:
            rows.append(dict(period=label, portfolio=name,
                             **_summary_row(ser.loc[ix], pb.net.loc[ix] if name == "Strategy" else None, rf.loc[ix])))
    out["subperiods"] = pd.DataFrame(rows)
    # 5. Crisis windows: cumulative return over each stress episode.
    rows = []
    for s0, s1, label in cfg["crisis_windows"]:
        ix = window_index(bt["index"], s0, s1)
        row = dict(window=label, start=ix[0].strftime("%Y-%m"), end=ix[-1].strftime("%Y-%m"),
                   Strategy=float((1 + bt["strategy"].net.loc[ix]).prod() - 1))
        for v in bt["benchmarks"].values():
            row[v.name] = float((1 + v.net.loc[ix]).prod() - 1)
        rows.append(row)
    out["crises"] = pd.DataFrame(rows).set_index("window")
    # 6. Currency and hedging views of the same fund.
    rows = []
    views = [("EUR, bonds hedged (base case)", dict(base_ccy="EUR")),
             ("EUR, bonds unhedged", dict(base_ccy="EUR", hedge_tickers=[])),
             ("USD (no FX)", dict(base_ccy="USD"))]
    for label, over in views:
        b2 = run_backtest(get_config(**{**cfg, **over}), data)
        for name, ser in [("Strategy", b2["strategy"].net)] + [(v.name, v.net) for v in b2["benchmarks"].values()]:
            rows.append(dict(view=label, portfolio=name,
                             **_summary_row(ser, b2["benchmarks"][prim].net if name == "Strategy" else None, b2["rf"])))
    out["currency"] = pd.DataFrame(rows)
    # 7. Parameter stability (NOT optimisation: 10 months stays fixed from the paper), on a common sample.
    if cfg["rule"] == "sma_trend":
        out["sma_stability"] = pd.DataFrame(
            [variant(f"{n} months", sma_window=n, start=cfg["sma_stability_start"]) for n in cfg["sma_stability"]]
        ).set_index("variant")
        out["signal_currency"] = pd.DataFrame([variant("signal on USD price (base case)", signal_on="USD"),
                                               variant("signal on EUR price", signal_on="base")]).set_index("variant")
        out["events_2020"] = signal_events(bt, "2020-01-01", "2020-12-31")
    return out


def block_bootstrap(returns: pd.DataFrame, n_paths: int = 10000, n_months: int = 120, block: int = 12,
                    initial: float = 10000.0, seed: int = 2270) -> dict:
    """Circular block bootstrap of historical monthly returns (Week 5 Monte Carlo).

    Blocks of `block` consecutive months are drawn jointly for all columns (the same calendar months for
    strategy and benchmark), which keeps their correlation and part of the autocorrelation."""
    rng = np.random.default_rng(seed)
    X = returns.dropna().to_numpy(dtype=float)
    T, K = X.shape
    n_blocks = int(math.ceil(n_months / block))
    starts = rng.integers(0, T, size=(n_paths, n_blocks))
    rows = ((starts[:, :, None] + np.arange(block)[None, None, :]) % T).reshape(n_paths, -1)[:, :n_months]
    paths = X[rows]                                      # (paths, months, K)
    wealth = initial * np.cumprod(1.0 + paths, axis=1)
    wealth = np.concatenate([np.full((n_paths, 1, K), initial), wealth], axis=1)
    mdd = (wealth / np.maximum.accumulate(wealth, axis=1) - 1.0).min(axis=1)
    qs = [5, 10, 25, 50, 75, 90, 95]
    bands = {c: pd.DataFrame(np.percentile(wealth[:, :, k], qs, axis=0).T, columns=[f"p{q}" for q in qs])
             for k, c in enumerate(returns.columns)}
    final = wealth[:, -1, :]
    years = n_months / PERIODS
    summary = {}
    for k, c in enumerate(returns.columns):
        f = final[:, k]
        summary[c] = {**{f"p{q}": float(np.percentile(f, q)) for q in qs},
                      "mean": float(f.mean()), "prob_below_start": float((f < initial).mean()),
                      "prob_drawdown_over_20pct": float((mdd[:, k] < -0.20).mean()),
                      "median_max_drawdown": float(np.median(mdd[:, k])),
                      "median_cagr": float((np.median(f) / initial) ** (1 / years) - 1)}
    if K >= 2:
        summary["prob_first_beats_second"] = float((final[:, 0] > final[:, 1]).mean())
    return dict(bands=bands, summary=summary, n_paths=n_paths, n_months=n_months, block=block,
                initial=initial, seed=seed, columns=list(returns.columns))


def monte_carlo(cfg: dict, bt: dict, against: str | None = None) -> dict:
    """Base case + haircut (excess return halved, McLean-Pontiff 2016) + block-length checks."""
    against = against or [k for k in bt["benchmarks"] if k != bt["primary"]][0]
    bn = bt["benchmarks"][against]
    df = pd.DataFrame({"Strategy": bt["strategy"].net, bn.name: bn.net})
    kw = dict(n_paths=cfg["mc_paths"], n_months=cfg["mc_years"] * PERIODS, initial=cfg["mc_initial"],
              seed=cfg["mc_seed"])
    base = block_bootstrap(df, block=cfg["mc_block"], **kw)
    excess_mean = df.sub(bt["rf"], axis=0).mean()
    base["haircut_summary"] = block_bootstrap(df - 0.5 * excess_mean, block=cfg["mc_block"], **kw)["summary"]
    base["block_alternatives"] = {b: block_bootstrap(df, block=b, **kw)["summary"] for b in cfg["mc_block_alternatives"]}
    return base


# %% [engine 7/8] figures (matplotlib, shared design tokens)
STYLE = dict(ink="#14213D", navy="#1F4E79", navy_light="#DCE6F0", ochre="#C08A2B", slate="#8A94A6",
             cash="#9DB7D5", loss="#A23B3B", grid="#E6E9EF", paper="#FFFFFF")
ASSET_COLOURS = {"SPY": "#1F4E79", "EFA": "#3D7AB5", "IEF": "#6FA3C8", "VNQ": "#C08A2B", "DBC": "#8C6D46",
                 CASH: "#D9E2EC"}
MM = 1 / 25.4
SIZES = {"F1": (170, 78), "F2": (170, 42), "F3": (82, 56), "F4": (82, 56), "F5": (82, 56), "F6": (82, 56),
         "F7": (82, 56), "F8": (170, 40)}
SOURCE_LINE = "Source: Yahoo Finance, ECB, FRED; group calculations. Simulated (back-tested) results."


def _size(fid):
    w, h = SIZES[fid]
    return (w * MM, h * MM)


def apply_style():
    """One calm institutional chart style (design tokens shared with prospectus and app)."""
    import matplotlib as mpl
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    family = [f for f in ("Inter", "DejaVu Sans") if f in names] or ["sans-serif"]
    mpl.rcParams.update({
        "font.family": family, "font.size": 6.5, "axes.titlesize": 7, "axes.labelsize": 6.5,
        "xtick.labelsize": 6, "ytick.labelsize": 6, "legend.fontsize": 6,
        "axes.edgecolor": STYLE["ink"], "axes.labelcolor": STYLE["ink"], "text.color": STYLE["ink"],
        "xtick.color": STYLE["ink"], "ytick.color": STYLE["ink"],
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
        "axes.axisbelow": True, "grid.color": STYLE["grid"], "grid.linewidth": 0.5, "axes.linewidth": 0.5,
        "xtick.major.width": 0.5, "ytick.major.width": 0.5, "xtick.major.size": 2, "ytick.major.size": 2,
        "figure.facecolor": STYLE["paper"], "axes.facecolor": STYLE["paper"], "savefig.facecolor": STYLE["paper"],
        "svg.fonttype": "none", "legend.frameon": False, "lines.linewidth": 1.2,
    })


def _pct_axis(ax, decimals=0):
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.{decimals}f}%"))


def _spread_labels(ax, items: list, min_gap: float = 0.075, fontsize: float = 6.0):
    """Direct end-of-line labels instead of a legend, pushed apart (axes coordinates) so they never overlap.
    items = [(y_value_in_data_units, text, colour, fontweight)]."""
    ax.get_ylim()  # forces autoscaling so the data-to-axes transform is final
    to_axes = ax.transAxes.inverted()
    x_ref = ax.get_xlim()[1]
    pts = sorted([(float(to_axes.transform(ax.transData.transform((x_ref, y)))[1]), t, c, fw)
                  for y, t, c, fw in items])
    ys = [p[0] for p in pts]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + min_gap)
    if ys and ys[-1] > 0.98:
        ys = [y - (ys[-1] - 0.98) for y in ys]
    for y, (_, t, c, fw) in zip(ys, pts):
        ax.annotate(t, xy=(1.01, y), xycoords="axes fraction", color=c, fontsize=fontsize, va="center",
                    fontweight=fw, annotation_clip=False)


def _finish(fig, ax, title: str | None, subtitle: str | None, source: bool = True):
    if title:
        fig.suptitle(title, x=0.01, ha="left", fontsize=8, fontweight="bold", y=0.995)
    if subtitle:
        ax.set_title(subtitle, loc="left", fontsize=6.5, color=STYLE["slate"])
    if source:
        fig.text(0.01, 0.005, SOURCE_LINE, fontsize=5, color=STYLE["slate"], ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04 if source else 0, 1, 0.95 if title else 1), pad=0.3)
    # tight_layout ignores annotations placed outside the axes (our end-of-line labels): shrink the axes
    # until the widest label fits inside the figure.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fw = fig.get_window_extent().width
    margin = 0.025 * fw  # glyphs render a little wider at print resolution than at screen resolution
    right = max([t.get_window_extent(renderer).x1 for a in fig.axes for t in a.texts] + [0])
    left = min([a.yaxis.label.get_window_extent(renderer).x0 for a in fig.axes] + [fw])
    adj = {}
    if right > fw - margin:
        adj["right"] = fig.subplotpars.right - (right - fw + margin) / fw
    if left < margin * 0.4:
        adj["left"] = fig.subplotpars.left + (margin * 0.4 - left) / fw
    if adj:
        fig.subplots_adjust(**adj)
    return fig


def _bench_style(bt, k):
    keys = list(bt["benchmarks"])
    colour = [STYLE["ochre"], STYLE["slate"], "#5B6B82"][keys.index(k) % 3]
    return colour, "-" if k == bt["primary"] else (0, (4, 2))


def fig_cumulative(bt: dict, title=None, subtitle=None, log=True):
    """F1: growth of 1 (all series start at exactly 1.0 on the same date)."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, FixedLocator, NullFormatter
    fig, ax = plt.subplots(figsize=_size("F1"))
    s_net = wealth_index(bt["strategy"].net); s_gr = wealth_index(bt["strategy"].gross)
    ax.plot(s_gr.index, s_gr, color=STYLE["navy"], lw=0.8, ls=(0, (3, 2)), alpha=0.8)
    ax.plot(s_net.index, s_net, color=STYLE["navy"], lw=1.6)
    ends = [(s_net, "Strategy (net)", STYLE["navy"], "bold"), (s_gr, "Strategy (gross)", STYLE["navy"], "normal")]
    for k, v in bt["benchmarks"].items():
        w = wealth_index(v.net)
        c, ls = _bench_style(bt, k)
        ax.plot(w.index, w, color=c, lw=1.1, ls=ls)
        ends.append((w, v.name, c, "bold"))
    if log:
        ax.set_yscale("log")
        top = max(float(e[0].max()) for e in ends); bot = min(float(e[0].min()) for e in ends)
        ticks = [t for t in (0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8) if bot * 0.9 <= t <= top * 1.1]
        ax.yaxis.set_major_locator(FixedLocator(ticks))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        ax.yaxis.set_minor_formatter(NullFormatter())
    ax.axhline(1.0, color=STYLE["ink"], lw=0.4, alpha=0.6)
    ax.set_ylabel(f"Value of 1 {bt['cfg']['base_ccy']} invested")
    ax.set_xlim(s_net.index[0], s_net.index[-1])
    _spread_labels(ax, [(w.iloc[-1], f"{lab} {w.iloc[-1]:.2f}", c, fw) for w, lab, c, fw in ends])
    return _finish(fig, ax, title, subtitle)


def fig_drawdowns(bt: dict, title=None, subtitle=None):
    """F2: fall from the previous high, strategy vs benchmarks; labels give each worst fall."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=_size("F2"))
    dd = drawdown(bt["strategy"].net)
    ax.fill_between(dd.index, dd, 0, color=STYLE["navy"], alpha=0.18, lw=0)
    ax.plot(dd.index, dd, color=STYLE["navy"], lw=1.1)
    items = [(float(dd.min()), f"Strategy worst {dd.min():.0%}", STYLE["navy"], "bold")]
    for k, v in bt["benchmarks"].items():
        d = drawdown(v.net)
        c, ls = _bench_style(bt, k)
        ax.plot(d.index, d, color=c, lw=0.9, ls=ls)
        items.append((float(d.min()), f"{v.name.split(' ')[0]} worst {d.min():.0%}", c, "bold"))
    _pct_axis(ax)
    ax.set_xlim(dd.index[0], dd.index[-1])
    ax.set_ylabel("Fall from high")
    _spread_labels(ax, items, min_gap=0.16)
    return _finish(fig, ax, title, subtitle)


def fig_weights(bt: dict, title=None, subtitle=None):
    """F3: what the strategy held each month (sleeves in their asset or in cash)."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=_size("F3"))
    w = bt["strategy"].held
    cols = [c for c in w.columns if c != CASH] + [CASH]
    ax.stackplot(w.index, *[w[c].to_numpy() for c in cols], colors=[ASSET_COLOURS.get(c, STYLE["slate"]) for c in cols],
                 labels=[c if c != CASH else "Cash" for c in cols], lw=0, step="post")
    ax.set_ylim(0, 1); ax.set_xlim(w.index[0], w.index[-1])
    _pct_axis(ax)
    ax.set_ylabel("Weight")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=6, fontsize=5.5, handlelength=0.9,
              columnspacing=0.8, handletextpad=0.3)
    return _finish(fig, ax, title, subtitle)


def fig_rolling(bt: dict, window: int = 36, title=None, subtitle=None):
    """F4: rolling 36-month Sharpe ratio (top) and beta vs the primary benchmark (bottom)."""
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(2, 1, figsize=_size("F4"), sharex=True)
    pb = bt["benchmarks"][bt["primary"]]
    rs = rolling_stats(bt["strategy"].net, pb.net, bt["rf"], window)
    rb = rolling_stats(pb.net, pb.net, bt["rf"], window)
    a1.plot(rs.index, rs["rolling_sharpe"], color=STYLE["navy"], lw=1.1)
    a1.plot(rb.index, rb["rolling_sharpe"], color=STYLE["ochre"], lw=0.9)
    a1.axhline(0, color=STYLE["ink"], lw=0.4)
    a1.set_ylabel(f"Sharpe ({window}m)")
    _spread_labels(a1, [(rs["rolling_sharpe"].iloc[-1], "Strategy", STYLE["navy"], "bold"),
                        (rb["rolling_sharpe"].iloc[-1], pb.name.split(" ")[0], STYLE["ochre"], "bold")], min_gap=0.14)
    a2.plot(rs.index, rs["rolling_beta"], color=STYLE["navy"], lw=1.1)
    a2.axhline(1, color=STYLE["ink"], lw=0.4, ls=":")
    a2.set_ylabel(f"Beta ({window}m)")
    a2.set_ylim(0, max(1.1, float(rs["rolling_beta"].max()) * 1.1))
    _spread_labels(a2, [(rs["rolling_beta"].iloc[-1], f"vs {pb.name.split(' ')[0]}", STYLE["navy"], "bold")])
    return _finish(fig, a1, title, subtitle)


def cost_sensitivity(bt: dict, max_bps: int = 60, step: int = 2) -> pd.DataFrame:
    """Growth of 1 by the end of the sample for each cost level (strategy and benchmarks pay it)."""
    rows = []
    for c in range(0, max_bps + 1, step):
        row = {"cost_bps": c, "Strategy": float((1 + net_from_gross(bt["strategy"], c)).prod())}
        for v in bt["benchmarks"].values():
            row[v.name] = float((1 + net_from_gross(v, c if bt["cfg"].get("benchmark_costs", True) else 0)).prod())
        rows.append(row)
    return pd.DataFrame(rows).set_index("cost_bps")


def fig_costs(bt: dict, title=None, subtitle=None):
    """F5: final value of 1 against the cost per trade; breakeven vs the primary benchmark marked."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=_size("F5"))
    cs = cost_sensitivity(bt)
    ax.plot(cs.index, cs["Strategy"], color=STYLE["navy"], lw=1.6)
    items = [(cs["Strategy"].iloc[-1], "Strategy", STYLE["navy"], "bold")]
    for k, v in bt["benchmarks"].items():
        c, ls = _bench_style(bt, k)
        ax.plot(cs.index, cs[v.name], color=c, lw=1.0, ls=ls)
        items.append((cs[v.name].iloc[-1], v.name.split(" ")[0], c, "bold"))
    cb = bt["cfg"]["cost_bps"]
    ax.axvline(cb, color=STYLE["ink"], lw=0.5, ls=":")
    ax.annotate(f"base case {cb:.0f} bps", xy=(cb, 0.3), xycoords=("data", "axes fraction"), xytext=(-3, 0),
                textcoords="offset points", fontsize=5.5, rotation=90, ha="right", va="center")
    be = breakeven_cost(bt["strategy"], bt["benchmarks"][bt["primary"]], bt["rf"], "cagr",
                        bt["cfg"].get("benchmark_costs", True))
    if be is not None and math.isfinite(be) and be <= cs.index.max():
        ax.axvline(be, color=STYLE["loss"], lw=0.7, ls="--")
        ax.annotate(f"breakeven {be:.0f} bps", xy=(be, 0.06), xycoords=("data", "axes fraction"), xytext=(3, 0),
                    textcoords="offset points", fontsize=5.5, color=STYLE["loss"])
    ax.set_xlim(0, cs.index.max())
    ax.set_xlabel("Cost per trade (bps of traded value)")
    ax.set_ylabel("Final value of 1")
    _spread_labels(ax, items, min_gap=0.09)
    return _finish(fig, ax, title, subtitle)


def fig_subperiods(rob: dict, title=None, subtitle=None):
    """F6: CAGR by sub-period, strategy vs benchmarks."""
    import matplotlib.pyplot as plt
    sp = rob["subperiods"]
    periods = list(dict.fromkeys(sp["period"])); ports = list(dict.fromkeys(sp["portfolio"]))
    fig, ax = plt.subplots(figsize=_size("F6"))
    width = 0.8 / len(ports)
    cols = [STYLE["navy"], STYLE["ochre"], STYLE["slate"]]
    for i, p in enumerate(ports):
        vals = [float(sp[(sp.period == per) & (sp.portfolio == p)]["cagr"].iloc[0]) for per in periods]
        x = np.arange(len(periods)) + (i - (len(ports) - 1) / 2) * width
        ax.bar(x, vals, width=width * 0.92, color=cols[i % 3], label=p.split(" ")[0] if i else "Strategy")
    ax.set_xticks(np.arange(len(periods))); ax.set_xticklabels([p.split(" ", 1)[0] for p in periods])
    ax.axhline(0, color=STYLE["ink"], lw=0.4)
    _pct_axis(ax)
    ax.set_ylabel("CAGR, net")
    ax.legend(loc="upper left", fontsize=5.5, ncol=3)
    return _finish(fig, ax, title, subtitle)


def fig_montecarlo(mc: dict, title=None, subtitle=None):
    """F7: 10-year outcome ranges for 10,000 EUR (P10-P90 band, median line), strategy vs 60/40."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    fig, ax = plt.subplots(figsize=_size("F7"))
    x = np.arange(mc["n_months"] + 1) / PERIODS
    items = []
    for c, colour in zip(mc["columns"][:2], [STYLE["navy"], STYLE["slate"]]):
        b = mc["bands"][c]
        short = "Strategy" if c == "Strategy" else c.split(" ")[0]
        ax.fill_between(x, b["p10"], b["p90"], color=colour, alpha=0.16, lw=0)
        ax.plot(x, b["p50"], color=colour, lw=1.3)
        ax.plot(x, b["p10"], color=colour, lw=0.6, ls=":")
        items += [(b["p50"].iloc[-1], f"{short} P50 {b['p50'].iloc[-1]:,.0f}", colour, "bold"),
                  (b["p10"].iloc[-1], f"{short} P10 {b['p10'].iloc[-1]:,.0f}", colour, "normal"),
                  (b["p90"].iloc[-1], f"{short} P90 {b['p90'].iloc[-1]:,.0f}", colour, "normal")]
    ax.axhline(mc["initial"], color=STYLE["ink"], lw=0.4)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k"))
    ax.set_xlabel("Years"); ax.set_ylabel("Value (EUR)")
    ax.set_xlim(0, x[-1])
    _spread_labels(ax, items, min_gap=0.085, fontsize=5.3)
    return _finish(fig, ax, title, subtitle)


def fig_calendar(bt: dict, title=None, subtitle=None, include_second=False):
    """F8: calendar-year returns, PRIIPs KID chart rules (linear axis, axis at 0%, label on every bar)."""
    import matplotlib.pyplot as plt
    pb = bt["benchmarks"][bt["primary"]]
    series = {"Strategy": bt["strategy"].net, pb.name: pb.net}
    if include_second:
        for k, v in bt["benchmarks"].items():
            if k != bt["primary"]:
                series[v.name] = v.net
    ann = annual_returns(series)
    fig, ax = plt.subplots(figsize=_size("F8") if not include_second else (170 * MM, 55 * MM))
    k = len(series); width = 0.8 / k
    colours = [STYLE["navy"], STYLE["ochre"], STYLE["slate"]]
    for i, c in enumerate(ann.columns):
        x = np.arange(len(ann)) + (i - (k - 1) / 2) * width
        ax.bar(x, ann[c].to_numpy(), width=width * 0.9, color=colours[i], label=c)
        for xi, v in zip(x, ann[c].to_numpy()):
            label = f"{v * 100:.1f}".replace("-0.0", "0.0")
            ax.annotate(label, xy=(xi, v), xytext=(0, 1.2 if v >= 0 else -1.2), textcoords="offset points",
                        ha="center", va="bottom" if v >= 0 else "top", fontsize=3.3, color=colours[i])
    ax.axhline(0, color=STYLE["ink"], lw=0.5)
    ax.set_xticks(np.arange(len(ann))); ax.set_xticklabels([str(y) for y in ann.index])
    ax.tick_params(axis="x", length=0)
    _pct_axis(ax)
    lo, hi = ax.get_ylim(); ax.set_ylim(lo * 1.15, hi * 1.2)
    ax.legend(loc="upper left", ncol=k, fontsize=5.5)
    ax.text(0.995, 0.03, "Simulated (back-tested) past performance", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=5.5, fontweight="bold")
    return _finish(fig, ax, title, subtitle)


def save_figure(fig, name: str, outdir: str = "output/figures"):
    """SVG for the prospectus (transparent, text stays text, Inter first) and PNG 200 dpi for display."""
    import os
    os.makedirs(outdir, exist_ok=True)
    svg = os.path.join(outdir, f"{name}.svg"); png = os.path.join(outdir, f"{name}.png")
    fig.savefig(svg, format="svg", transparent=True, metadata={"Date": None})  # no timestamp: stable files
    fig.savefig(png, format="png", dpi=200)
    with open(svg, "r", encoding="utf-8") as f:
        txt = f.read()
    for old in ("font-family:'DejaVu Sans'", "font-family: 'DejaVu Sans'"):
        txt = txt.replace(old, "font-family:Inter,'DejaVu Sans',Arial,sans-serif")
    with open(svg, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    return svg, png


def to_jsonable(obj):
    """Convert numpy/pandas objects to plain JSON types (NaN and inf become null)."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return {(i.strftime("%Y-%m") if isinstance(i, pd.Timestamp) else str(i)): to_jsonable(r.to_dict())
                for i, r in obj.iterrows()}
    if isinstance(obj, pd.Series):
        return {(i.strftime("%Y-%m") if isinstance(i, pd.Timestamp) else str(i)): to_jsonable(v)
                for i, v in obj.items()}
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.integer):
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
    # Negative control: a lag-0 (look-ahead) version must be caught by the same test.
    if cfg["rule"] == "sma_trend":
        c0 = get_config(**{**cfg, "signal_lag": 0})
        a0, p0 = run_backtest(c0, data), run_backtest(c0, pert)
        d0 = float((a0["strategy"].held.loc[:T1] - p0["strategy"].held.loc[:T1]).abs().max().max())
        s0 = perf_metrics(a0["strategy"].net, None, a0["rf"])["sharpe"]
        s1 = perf_metrics(bt["strategy"].net, None, bt["rf"])["sharpe"]
        add("Negative control: the same test catches a lag-0 (look-ahead) version", d0 > 1e-6,
            f"lag-0 weight diff up to T+1 = {d0:.2f}; Sharpe lag 0 {s0:.2f} vs lag 1 {s1:.2f}")
    # 2. Weights: sum to 1 every month, no negatives (no shorting, no leverage).
    allw = [bt["strategy"].held, bt["strategy"].drift] + [b.held for b in bt["benchmarks"].values()]
    ssum = max(float((w.sum(axis=1) - 1).abs().max()) for w in allw)
    smin = min(float(w.min().min()) for w in allw)
    add("Weights sum to 1 at every date and are never negative", ssum < 1e-10 and smin >= -1e-12,
        f"max |sum - 1| = {ssum:.1e}, min weight = {smin:.4f}")
    # 3. Lecture 4.3 fixture: fixed 60/40, monthly rebalancing, zero cost = (w * r).sum(axis=1).
    r = bt["returns"]
    fw = {"SPY": 0.6, "IEF": 0.4}
    sim = simulate(r, fixed_target(fw, bt["index"]), "M", 0.0, "fixture")
    ref = (r[list(fw)] * pd.Series(fw)).sum(axis=1)
    d3 = float((sim.net - ref).abs().max())
    add("Fixture: 60/40 with monthly rebalancing and zero cost equals (w * r).sum(axis=1)", d3 < 1e-12,
        f"max diff {d3:.1e}")
    # 4. Drift fixture: never rebalanced = buy-and-hold of the two assets (weights really drift).
    sim_bh = simulate(r, fixed_target(fw, bt["index"]), "none", 0.0, "bh")
    bh = 0.6 * (1 + r["SPY"]).cumprod() + 0.4 * (1 + r["IEF"]).cumprod()
    d4 = float(((1 + sim_bh.net).cumprod() - bh).abs().max())
    add("Fixture: no rebalancing equals buy-and-hold of the individual assets (drift is modelled)", d4 < 1e-10,
        f"max wealth diff {d4:.1e}")
    # 5. Sleeve accounting: with monthly resets it must equal the plain target-weight simulation.
    if cfg["rule"] == "sma_trend":
        gen = simulate(r, bt["target"], "M", cfg["cost_bps"], "generic")
        slv = simulate_sleeves(r, bt["signals"], base_weights(cfg), "M", cfg["cost_bps"], "sleeves")
        d5 = float((gen.net - slv.net).abs().max())
        add("Sleeve accounting with monthly reset equals the target-weight simulation", d5 < 1e-12,
            f"max return diff {d5:.1e}")
    # 6. Benchmark against itself: beta 1, alpha 0, tracking error 0.
    b = bt["benchmarks"][bt["primary"]].net
    m = perf_metrics(b, b, bt["rf"])
    ok = abs(m["beta"] - 1) < 1e-12 and abs(m["alpha_ann"]) < 1e-12 and m["tracking_error"] < 1e-12
    add("Benchmark regressed on itself gives beta 1, alpha 0, tracking error 0", ok,
        f"beta {m['beta']:.12f}, alpha {m['alpha_ann']:.1e}, TE {m['tracking_error']:.1e}")
    # 7. Cumulative series start at exactly 1 on the same date.
    ws = [wealth_index(bt["strategy"].net), wealth_index(bt["strategy"].gross)] + \
         [wealth_index(v.net) for v in bt["benchmarks"].values()]
    ok = all(w.iloc[0] == 1.0 for w in ws) and len({w.index[0] for w in ws}) == 1
    add("All cumulative series start at exactly 1.0 on the same date", ok, f"start {ws[0].index[0]:%Y-%m-%d}")
    # 8. Costs: net = (1 - c * traded)(1 + gross) - 1 and net never above gross.
    s = bt["strategy"]
    d8 = float((s.net - net_from_gross(s, s.cost_bps)).abs().max())
    add("Costs: net return identity holds and net <= gross every month",
        d8 < 1e-15 and bool((s.net <= s.gross + 1e-15).all()), f"identity diff {d8:.1e}")
    # 9. Independent recomputation of the signal for one asset at one date (plain Python, no rolling()).
    if cfg["rule"] == "sma_trend":
        tick = cfg["tickers"][0]; n = int(cfg["sma_window"]); lag = int(cfg["signal_lag"])
        t_hold = bt["index"][len(bt["index"]) // 3]
        p = data["prices_usd"][tick].dropna()
        k = p.index.get_loc(t_hold) - lag
        manual = 1.0 if p.iloc[k] > sum(p.iloc[k - n + 1:k + 1].tolist()) / n else 0.0
        engine = float(bt["strategy"].held.loc[t_hold, tick] > 0)
        add(f"Signal recomputed by hand ({n} prices, plain average) matches the engine", manual == engine,
            f"{tick} held in {t_hold:%Y-%m}: manual {manual:.0f}, engine {engine:.0f}")
    # 10. Two independent formulas agree: beta = cov/var equals the OLS slope; Sharpe by hand.
    sr = bt["strategy"].net
    ex = (sr - bt["rf"]).to_numpy(); exb = (b - bt["rf"]).to_numpy()
    slope = float(np.polyfit(exb, ex, 1)[0])
    ms = perf_metrics(sr, b, bt["rf"])
    sharpe_hand = float(np.mean(ex) / np.std(ex, ddof=1) * math.sqrt(12))
    ok = abs(slope - ms["beta"]) < 1e-10 and abs(sharpe_hand - ms["sharpe"]) < 1e-12
    add("Beta (cov/var) equals the OLS slope; Sharpe recomputed by hand", ok,
        f"beta {ms['beta']:.6f} vs slope {slope:.6f}; Sharpe {ms['sharpe']:.6f} vs {sharpe_hand:.6f}")
    # 11. Annualisation conventions (the lecture's AI-bug list): mean x12, vol x sqrt(12), beta raw.
    ok = abs(ms["ann_vol"] - sr.std() * math.sqrt(12)) < 1e-14 and abs(ms["ann_return"] - 12 * sr.mean()) < 1e-14
    add("Annualisation: return x12, volatility x sqrt(12), beta not annualised", ok,
        f"ann. vol {ms['ann_vol']:.4f} = monthly {sr.std():.4f} x sqrt(12)")
    # 12. Currency unit test (masterplan S2): USD asset flat, euro up 10% -> EUR investor loses about 9.1%.
    ix = pd.DatetimeIndex([pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")])
    mini = dict(prices_usd=pd.DataFrame({"X": [100.0, 100.0]}, index=ix),
                fx_usd_per_eur=pd.Series([1.10, 1.21], index=ix),
                rf={"EUR": pd.Series(0.0, index=ix), "USD": pd.Series(0.0, index=ix)})
    r_eur = float(asset_returns(mini, {**cfg, "hedge_tickers": []}, "EUR")["X"].iloc[1])
    add("Currency: USD asset flat and euro +10% gives an EUR return of -9.09%", abs(r_eur - (1 / 1.1 - 1)) < 1e-12,
        f"r_EUR = {r_eur:.4%}")
    # 13. Hedged bond sleeve: EUR return = USD return + (rf_EUR - rf_USD), independent of the exchange rate.
    if cfg.get("hedge_tickers") and cfg["base_ccy"] == "EUR":
        h = cfg["hedge_tickers"][0]
        usd = data["prices_usd"][h].pct_change(fill_method=None).reindex(bt["index"])
        want = usd + data["rf"]["EUR"].reindex(bt["index"]) - data["rf"]["USD"].reindex(bt["index"])
        d13 = float((bt["returns"][h] - want).abs().max())
        add(f"Hedged {h} return = USD return + (rf EUR - rf USD)", d13 < 1e-15, f"max diff {d13:.1e}")
    return pd.DataFrame(res)


def build_results(cfg: dict, data: dict, bt: dict, rob: dict, mc: dict, tests: pd.DataFrame,
                  extra: dict | None = None) -> dict:
    """Everything the prospectus prints, in one JSON-able dictionary (schema: RESULTS-SCHEMA.md)."""
    import platform
    prim = bt["primary"]
    bkeys = list(bt["benchmarks"])
    second = [k for k in bkeys if k != prim]
    sname = bt["strategy"].name
    t1 = metrics_table(bt, prim)
    lab = {"strategy": f"{sname} (net)", "strategy_gross": f"{sname} (gross)",
           **{k: bt["benchmarks"][k].name for k in bkeys}}
    sims = {"strategy": bt["strategy"], "strategy_gross": bt["strategy"], **bt["benchmarks"]}
    portfolios = {}
    for key, rowlabel in lab.items():
        p = t1.loc[rowlabel].to_dict()
        ts = turnover_stats(sims[key])
        p.update(turnover_pa=ts["turnover_pa"], traded_value_pa=ts["traded_value_pa"],
                 cost_drag_pa=ts["cost_drag_pa"] if key != "strategy_gross" else 0.0,
                 avg_invested=float(1 - sims[key].held[CASH].mean()))
        portfolios[key] = p
    rel = ["beta", "alpha_ann", "alpha_t", "alpha_t_nw", "information_ratio", "information_ratio_regression",
           "tracking_error", "r_squared", "correlation", "ann_active_return", "hit_rate_vs_benchmark"]
    vs_second = {}
    if second:
        t2 = metrics_table(bt, second[0])
        vs_second = {key: {k: t2.loc[rowlabel, k] for k in rel} for key, rowlabel in lab.items()}
        vs_second["benchmark"] = second[0]
    series = {"strategy": bt["strategy"].net, **{k: v.net for k, v in bt["benchmarks"].items()}}
    vs_market = {k: {kk: perf_metrics(v, bt["market"], bt["rf"])[kk] for kk in ("beta", "alpha_ann", "alpha_t",
                                                                               "correlation")}
                 for k, v in series.items()}
    vs_market["market"] = bt["market"].name
    held = bt["strategy"].held
    risky = held.drop(columns=CASH)
    years = len(held) / PERIODS
    allocation = dict(avg_weight=held.mean(), share_months_invested=(risky > 1e-12).mean(),
                      avg_invested=float(1 - held[CASH].mean()), min_invested=float(1 - held[CASH].max()),
                      max_invested=float(1 - held[CASH].min()),
                      months_fully_in_cash=int((held[CASH] > 1 - 1e-12).sum()),
                      months_fully_invested=int((held[CASH] < 1e-12).sum()),
                      switches_per_year=(risky > 1e-12).astype(int).diff().abs().sum() / years,
                      latest_weights=held.iloc[-1], latest_month=held.index[-1].strftime("%Y-%m"))
    ann = annual_returns(series)
    sri_s = sri_priips(bt["strategy"].net, cfg["sri_rhp_years"])
    sri_b = sri_priips(bt["benchmarks"][prim].net, cfg["sri_rhp_years"])
    vols5 = {k: float(v.iloc[-60:].std() * math.sqrt(PERIODS)) for k, v in series.items()}
    w_avg = held.mean()
    ter = sum(float(w_avg.get(t, 0.0)) * cfg["ucits"].get(t, {}).get("ter", 0.0) for t in w_avg.index)
    trade_pa = turnover_stats(bt["strategy"])["cost_drag_pa"]
    rep = data_report(data, cfg)
    rs = rolling_stats(bt["strategy"].net, bt["benchmarks"][prim].net, bt["rf"], cfg["rolling_window"])
    rsb = rolling_stats(bt["benchmarks"][prim].net, bt["benchmarks"][prim].net, bt["rf"], cfg["rolling_window"])
    versions = dict(python=platform.python_version(), pandas=pd.__version__, numpy=np.__version__)
    for mod in ("yfinance", "quantstats", "statsmodels", "matplotlib"):
        try:
            versions[mod] = __import__(mod).__version__
        except Exception:
            versions[mod] = None
    try:
        sha = engine_sha256()
    except Exception:
        sha = None
    missing = int(rep.loc[[t for t in cfg["tickers"]], "missing_in_window"].sum())
    out = dict(
        meta=dict(strategy_name=sname, group="BP", is_mock=False, engine_version=ENGINE_VERSION, engine_sha256=sha,
                  versions=versions, generated_at=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"),
                  data_retrieved_at=data["retrieved_at"], base_ccy=cfg["base_ccy"],
                  sample_start=bt["index"][0].strftime("%Y-%m"), sample_end=bt["index"][-1].strftime("%Y-%m"),
                  start_value_date=(bt["index"][0] - pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d"),
                  data_start=cfg["warmup_start"][:7], n_months=len(bt["index"]), n_years=len(bt["index"]) / PERIODS,
                  frequency="monthly", cost_bps=cfg["cost_bps"], signal_lag=cfg["signal_lag"],
                  sma_window=cfg["sma_window"], rebalance=cfg["rebalance"], hedge_tickers=cfg["hedge_tickers"],
                  primary_benchmark=prim, benchmark_labels={k: bt["benchmarks"][k].name for k in bkeys},
                  sources=data["sources"],
                  cleaning=(f"Daily adjusted closes resampled to the last trading day of each month; no gaps filled. "
                            f"{len(bt['index'])} monthly returns {bt['index'][0]:%b %Y} to {bt['index'][-1]:%b %Y} "
                            f"for all {len(cfg['tickers'])} assets, {missing} missing values, no rows dropped."),
                  config=cfg),
        assets=[dict(ticker=t, name=cfg["asset_names"].get(t, t), inception=data["first_daily"].get(t, "")[:7],
                     ccy="USD", hedged_in_eur_view=t in (cfg.get("hedge_tickers") or []),
                     ucits=cfg["ucits"].get(t)) for t in cfg["tickers"]],
        cash_ucits=cfg["ucits"].get(CASH),
        data_verification=rep.to_dict(orient="index"),
        portfolios=portfolios, relative_to_second_benchmark=vs_second, relative_to_market=vs_market,
        costs={k: turnover_stats(v) for k, v in [("strategy", bt["strategy"])] + list(bt["benchmarks"].items())},
        breakeven_cost_bps=rob["breakeven"], allocation=allocation,
        calendar_year_returns=[dict(year=int(y), **{k: float(v) for k, v in row.items()})
                               for y, row in ann.iterrows()],
        risk_indicator=dict(sri=max(sri_s["sri_class"], sri_b["sri_class"]), strategy=sri_s,
                            unfiltered_reference_mix=sri_b,
                            method=(f"Indicative PRIIPs SRI, authors' calculation: Cornish-Fisher VaR 97.5% on the "
                                    f"last 60 monthly returns, RHP {cfg['sri_rhp_years']} years, +1 class for monthly "
                                    f"data, higher of strategy and unfiltered 1/n mix. Not an official KID figure."),
                            srri_old_bands={k: srri_class(v) for k, v in vols5.items()}, ann_vol_last_5y=vols5),
        robustness=dict(costs=rob["costs"], lag=rob["lag"], rebalancing=rob["rebalancing"].to_dict(orient="records"),
                        subperiods=rob["subperiods"].to_dict(orient="records"),
                        crises=rob["crises"].reset_index().to_dict(orient="records"),
                        currency=rob["currency"].to_dict(orient="records"),
                        sma_stability=rob.get("sma_stability", pd.DataFrame()),
                        signal_currency=rob.get("signal_currency", pd.DataFrame()),
                        events_2020=rob.get("events_2020", [])),
        rolling=dict(window=cfg["rolling_window"], sharpe_min=rs["rolling_sharpe"].min(),
                     sharpe_max=rs["rolling_sharpe"].max(), sharpe_last=rs["rolling_sharpe"].iloc[-1],
                     beta_min=rs["rolling_beta"].min(), beta_max=rs["rolling_beta"].max(),
                     beta_last=rs["rolling_beta"].iloc[-1],
                     share_windows_sharpe_above_benchmark=float(
                         (rs["rolling_sharpe"] > rsb["rolling_sharpe"].reindex(rs.index)).mean())),
        monte_carlo=dict(n_paths=mc["n_paths"], years=mc["n_months"] / PERIODS, block_months=mc["block"],
                         method="circular block bootstrap, strategy and benchmark drawn on the same months",
                         initial_eur=mc["initial"], seed=mc["seed"], columns=mc["columns"], summary=mc["summary"],
                         haircut_summary=mc.get("haircut_summary"), block_alternatives=mc.get("block_alternatives")),
        costs_illustration=dict(initial_eur=10000.0, weighted_ter=ter, trading_cost_pa=trade_pa,
                                total_first_year_eur=10000.0 * (ter + trade_pa),
                                note="UCITS TERs weighted by the strategy's average holdings (incl. cash fund); "
                                     "trading cost = backtest cost drag at the base-case cost. Taxes excluded."),
        signals=dict(dates=[d.strftime("%Y-%m") for d in bt["index"]],
                     **({t: [int(x) for x in bt["signals"][t].to_numpy()] for t in bt["signals"].columns}
                        if bt["signals"] is not None else {})),
        tests=tests.to_dict(orient="records"),
        tests_all_pass=bool((tests["result"] != "FAIL").all()),   # SKIPPED = optional library unavailable
        tests_summary=tests["result"].value_counts().to_dict(),
    )
    if extra:
        out.update(extra)
    return to_jsonable(out)
