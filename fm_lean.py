# %% [lean 1/3] settings and data (APIs as in the W3 lecture)
"""fm_lean: the backtest behind Group BP's prospectus, in the style of the course notebooks (W3-W5).

Used by the Colab notebook (written to disk with %%writefile) and imported unchanged by the Streamlit app.
Analysis only: chart style and the export for the prospectus layout live in the notebook, not here.
Conventions: monthly simple returns; a position decided at the end of month t-1 earns the return of month t
(shift(1)); mean x12, volatility x sqrt(12), Sharpe and IR x sqrt(12), alpha x12, beta not annualised.
"""
import io
import time

import numpy as np
import pandas as pd
import requests

VERSION = "lean-2.0"
# Strategy 2: US equity, developed ex-US equity, US Treasuries 7-10y, US utilities, commodities, gold
WEIGHTS = {"SPY": 0.20, "EFA": 0.20, "IEF": 0.20, "XLU": 0.20, "DBC": 0.10, "GLD": 0.10}
TICKERS = list(WEIGHTS)
B2_WEIGHTS = {"SPY": 0.36, "EFA": 0.24, "IEF": 0.40}  # classic 60/40 (bonds hedged like the strategy's)
# Before a fund's first price its index stands in, chained at the fund's first price: DBC (Feb 2006) <- S&P GSCI,
# GLD (Nov 2004) <- gold futures (needed only for GLD's first 10-month average).
PROXIES = {"DBC": "^SPGSCI", "GLD": "GC=F"}
# B3 = MSCI World for a euro investor: iShares Core MSCI World UCITS ETF (Acc) on Xetra, EUR prices. Before the ETF's
# own returns start, the MSCI World price index plus the ETF's average monthly gap to it (net dividends minus TER).
B3_ETF, B3_INDEX = "EUNL.DE", "^990100-USD-STRD"
UCITS = {  # how an EU retail fund would implement each sleeve (justETF, 20.11.2026; XLU, GLD, B3: 26.11.2026); TER as a decimal
    "SPY": dict(ticker="SXR8", isin="IE00B5BMR087", name="iShares Core S&P 500 UCITS ETF (Acc)", ter=0.0007),
    "EFA": dict(ticker="EXUS", isin="IE0006WW1TQ4", name="Xtrackers MSCI World ex USA UCITS ETF 1C", ter=0.0015),
    "IEF": dict(ticker="IBB1", isin="IE00BGPP6697", name="iShares $ Treasury Bond 7-10yr UCITS ETF EUR Hedged (Dist)", ter=0.0010),
    "XLU": dict(ticker="ZPDU", isin="IE00BWBXMB69", name="State Street SPDR S&P U.S. Utilities Select Sector UCITS ETF (Acc)", ter=0.0015),
    "DBC": dict(ticker="SXRS", isin="IE00BDFL4P12", name="iShares Diversified Commodity Swap UCITS ETF", ter=0.0019),
    "GLD": dict(ticker="PPFB", isin="IE00B4ND3602", name="iShares Physical Gold ETC", ter=0.0012),
    "CASH": dict(ticker="XEON", isin="LU0290358497", name="Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C", ter=0.0010),
    "B3": dict(ticker="EUNL", isin="IE00B4L5Y983", name="iShares Core MSCI World UCITS ETF USD (Acc)", ter=0.0020),
}


def get(url, params=None, tries=4):
    """HTTP GET with a few retries; a clear message if the provider keeps refusing."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200 and r.content:
                return r
        except requests.RequestException:
            pass
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"No answer from {url}. Wait a minute and run the cell again.")


def fred(series, **extra):
    """Key-less FRED download (fredgraph.csv, as in the W3 lecture)."""
    df = pd.read_csv(io.StringIO(get("https://fred.stlouisfed.org/graph/fredgraph.csv", dict(id=series, **extra)).text),
                     index_col=0, parse_dates=True, na_values=".")
    return pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()


def ecb(key):
    """Key-less ECB Data Portal download (CSV)."""
    r = get(f"https://data-api.ecb.europa.eu/service/data/{key}", dict(format="csvdata", startPeriod="1999-01"))
    df = pd.read_csv(io.StringIO(r.text))
    return pd.Series(df["OBS_VALUE"].to_numpy(dtype=float), index=pd.to_datetime(df["TIME_PERIOD"])).sort_index()


def yahoo(tickers, start, end):
    """Daily adjusted closes (splits and dividends reinvested). Yahoo rate-limits shared machines such as Colab,
    so a failed download waits 60 s and tries once more before it stops with a clear message."""
    import yfinance as yf
    for attempt in range(2):
        try:
            px = yf.download(tickers, start=start, end=end, interval="1d", auto_adjust=True, progress=False,
                             threads=False)["Close"]
            if px.index.tz is not None:
                px.index = px.index.tz_localize(None)
            if px.reindex(columns=tickers).notna().sum().min() > 0:
                return px[tickers]
        except Exception as e:
            print(f"NOTE: yfinance error: {type(e).__name__}: {e}")
        if attempt == 0:
            print("NOTE: Yahoo did not deliver every price series; waiting 60 s and trying once more.")
            time.sleep(60)
    raise RuntimeError("Yahoo Finance did not deliver prices (it rate-limits shared machines such as Colab). Wait about a "
                       "minute and choose Runtime > Run all again; if it keeps failing, choose Runtime > Disconnect and "
                       "delete runtime (a new machine gets a new IP) and run all again.")


def to_month_end(s):
    s = s.copy()
    s.index = s.index + pd.offsets.MonthEnd(0)
    return s


def first_day_of_next_month(daily):
    """Close on the first trading day of the NEXT month, labelled with this month's end (next-day execution)."""
    first = daily.groupby(daily.index.to_period("M")).first()
    first.index = first.index.to_timestamp() + pd.offsets.MonthEnd(0)
    return first.shift(-1)


def splice(daily, tickers, proxies):
    """Before a fund's first price, chain its proxy's daily returns, scaled to the fund's first price. Only the
    trading days of our US funds are used, so every month-end close stays on the same day."""
    daily = daily.copy()
    days = daily[tickers].dropna(how="all").index
    for t, p in proxies.items():
        first = daily[t].first_valid_index()
        proxy = daily[p].reindex(days).ffill()
        fill = (proxy * daily.at[first, t] / proxy.at[first]).loc[:first]
        daily.loc[fill.index, t] = daily.loc[fill.index, t].fillna(fill)
    return daily


def chain_b3(etf_eur, index_usd, fx, months, end, etf_from=None):
    """B3 as a USD price (EUR price x USD per EUR), so the normal EUR conversion returns the ETF's euro return.
    The ETF's own returns from its second month-end after listing; before that the index return plus the ETF's
    average monthly gap to the index over the overlap up to `end` (net dividends minus TER), measured, never typed."""
    etf_from = etf_from or etf_eur.first_valid_index() + pd.offsets.MonthEnd(2)
    r_etf = (etf_eur * fx).dropna().pct_change().loc[etf_from:end]
    r_idx = index_usd.pct_change()
    gap = (r_etf - r_idx.reindex(r_etf.index)).mean()
    r = r_idx + gap
    r.loc[r_etf.index] = r_etf
    return (1 + r.reindex(months).fillna(0.0)).cumprod(), float(gap), etf_from


def load_data(end, tickers=TICKERS, proxies=PROXIES):
    """Everything from the APIs, once: prices (Yahoo), EUR cash rate (ECB), USD overnight rate and EUR/USD (FRED)."""
    end_dl = (pd.Timestamp(end) + pd.Timedelta(days=11)).strftime("%Y-%m-%d")   # a few days more, for next-day trades
    extra = list(dict.fromkeys(list(proxies.values()) + [B3_ETF, B3_INDEX]))
    raw = yahoo(list(dict.fromkeys(tickers + extra)), "1990-01-01", end_dl)    # from 1990, so each fund's first price is measured
    first_price = {t: raw[t].first_valid_index() for t in tickers}
    daily = splice(raw, tickers, proxies)
    eonia, estr = ecb("FM/M.U2.EUR.4F.MM.EONIA.HSTA"), ecb("FM/M.U2.EUR.4F.MM.UONSTR.HSTA")
    eur = to_month_end(pd.concat([eonia[:"2019-09-30"], estr["2019-10-01":]]))   # EONIA, then EUR STR (% p.a.)
    effr = fred("EFFR").resample("ME").mean()                                    # US overnight rate, monthly average
    fx = to_month_end(fred("DEXUSEU", fq="Monthly", fam="eop"))                   # USD per EUR, end of month
    fx_daily = fred("DEXUSEU").ffill()
    month_end = daily.resample("ME").last().loc[:end]                            # last trading day of each month
    next_day = first_day_of_next_month(daily).reindex(month_end.index)
    fx_me = fx.reindex(month_end.index)
    fx_next = first_day_of_next_month(fx_daily.to_frame()).iloc[:, 0].reindex(month_end.index)
    px, px_next = month_end[tickers].copy(), next_day[tickers].copy()
    px["B3"], gap, etf_from = chain_b3(month_end[B3_ETF], month_end[B3_INDEX], fx_me, px.index, end)
    px_next["B3"] = chain_b3(next_day[B3_ETF], next_day[B3_INDEX], fx_next, px.index, end, etf_from)[0]   # same months as month-end
    return dict(daily=daily, raw=raw, px=px, fx=fx_me, px_next=px_next, fx_next=fx_next, first_price=first_price,
                proxies=proxies, b3=dict(etf=B3_ETF, index=B3_INDEX, etf_from=etf_from, gap_monthly=gap),
                rf=((1 + eur / 100) ** (1 / 12) - 1).reindex(px.index),          # monthly EUR cash return, month t
                usd_on=((1 + effr / 100) ** (1 / 12) - 1).reindex(px.index),
                retrieved_at=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"))


# %% [lean 2/3] the backtest (Lecture 4.2 style: pct_change, rolling, shift, (w * r).sum)
def eur_returns(d, next_day=False, hedge=("IEF",)):
    """Monthly returns of every ticker in EUR; the bond sleeve is hedged (USD return + EUR rate - USD rate)."""
    px, fx = (d["px_next"], d["fx_next"]) if next_day else (d["px"], d["fx"])
    r = px.div(fx, axis=0).pct_change()
    for t in hedge:
        r[t] = px[t].pct_change() + d["rf"] - d["usd_on"]
    return r


def run_portfolio(w, r, rf, cost_bps):
    """Weights w (rows = months held) -> gross and net returns. Weights drift during each month; costs are
    charged on the ETF trades back to the target at the start of the next month (Lecture 4.3)."""
    gross = (w * r[w.columns]).sum(axis=1) + (1 - w.sum(axis=1)) * rf      # the rest of the money earns EUR cash
    drifted = (w * (1 + r[w.columns])).div(1 + gross, axis=0).shift(1)     # weights just before this month's trades
    drifted.iloc[0] = w.iloc[0]                                            # month 1: bought at target, no cost
    traded = (w - drifted).abs().sum(axis=1)                               # ETF trades only; the cash leg is free
    net = (1 - cost_bps / 1e4 * traded) * (1 + gross) - 1
    turnover = 0.5 * (traded + ((1 - w.sum(axis=1)) - (1 - drifted.sum(axis=1))).abs())
    return dict(gross=gross, net=net, traded=traded, turnover=turnover)


def backtest(d, start, end, weights=WEIGHTS, sma=10, lag=1, cost_bps=10.0, next_day=False, hedge=("IEF",)):
    """Faber's rule per sleeve: a sleeve holds its asset at its target weight while the month-end USD price is above
    its 10-month average, otherwise that sleeve waits in EUR cash; decided at month-end t-1 (lag 1), held during t.
    Benchmarks, same cost model: B1 = the same sleeves always invested, B2 = 60/40, B3 = MSCI World (unhedged)."""
    tickers, target = list(weights), pd.Series(weights, dtype=float)
    r = eur_returns(d, next_day, hedge)
    price = d["px"][tickers]                                    # the signal always uses month-end closes
    average = price.rolling(sma).mean()
    signal = (price > average).astype(float)
    w = signal.shift(lag) * target
    months = r.loc[start:end].index
    assert average.shift(lag).loc[months].notna().all().all(), "not enough price history for the first average"
    r, w, rf = r.loc[months], w.loc[months], d["rf"].loc[months]
    assert r[tickers + ["B3"]].notna().all().all() and rf.notna().all(), "missing data inside the sample"
    out = {"Strategy": run_portfolio(w, r, rf, cost_bps)}
    out["B1"] = run_portfolio(pd.DataFrame(weights, index=months), r, rf, cost_bps)
    out["B2"] = run_portfolio(pd.DataFrame(B2_WEIGHTS, index=months), r, rf, cost_bps)
    out["B3"] = run_portfolio(pd.DataFrame({"B3": 1.0}, index=months), r, rf, cost_bps)
    net = pd.DataFrame({k: v["net"] for k, v in out.items()})
    net["Strategy gross"] = out["Strategy"]["gross"]
    return dict(net=net, rf=rf, r=r, weights=w, signal=signal.shift(lag).loc[months], parts=out, cost_bps=cost_bps)


def at_cost(bt, name, cost_bps):
    """The same trades re-priced at another cost per trade (exact: costs do not change the weights)."""
    p = bt["parts"][name]
    return (1 - cost_bps / 1e4 * p["traded"]) * (1 + p["gross"]) - 1


# %% [lean 3/3] performance measures (W3 3.3-3.5), robustness and Monte Carlo (W5 5.3)
def wealth(r):
    """Growth of 1 with a start row one month before the first return, so every series starts at exactly 1."""
    return pd.concat([pd.Series([1.0], index=[r.index[0] - pd.offsets.MonthEnd(1)]), (1 + r).cumprod()])


def drawdown(r):
    v = wealth(r)
    return v / v.cummax() - 1


def measures(r, b, rf):
    """The six measures of the brief plus CAGR, drawdown and a few descriptive extras; b = benchmark (B1)."""
    ex, exb, act = r - rf, b - rf, r - b
    beta = ex.cov(exb) / exb.var()                                  # NOT annualised
    alpha = ex.mean() - beta * exb.mean()                           # = OLS intercept
    resid = ex - alpha - beta * exb
    s = resid.std(ddof=2)                                           # OLS residual standard error
    se_alpha = s * np.sqrt(1 / len(r) + exb.mean() ** 2 / ((exb - exb.mean()) ** 2).sum())
    dd = drawdown(r)
    trough = dd.idxmin()
    peak = dd[:trough][dd[:trough] >= -1e-12].index[-1]
    back = dd[trough:][dd[trough:] >= -1e-12]
    m = dict(months=len(r), ann_return=12 * r.mean(), cagr=(1 + r).prod() ** (12 / len(r)) - 1, final_wealth=(1 + r).prod(),
             ann_vol=r.std() * np.sqrt(12), ann_excess_return=12 * ex.mean(), sharpe=ex.mean() / ex.std() * np.sqrt(12),
             beta=beta, alpha_ann=12 * alpha, alpha_t=alpha / se_alpha if s > 1e-12 else np.nan,
             information_ratio_regression=alpha / s * np.sqrt(12) if s > 1e-12 else np.nan,
             tracking_error=act.std() * np.sqrt(12), ann_active_return=12 * act.mean(),
             information_ratio=act.mean() / act.std() * np.sqrt(12) if act.std() > 1e-12 else np.nan,
             max_drawdown=dd.min(), peak=peak.strftime("%Y-%m"), trough=trough.strftime("%Y-%m"),
             recovery=back.index[0].strftime("%Y-%m") if len(back) else None,
             months_peak_to_trough=(trough.year - peak.year) * 12 + trough.month - peak.month,
             worst_12m=((1 + r).rolling(12).apply(np.prod, raw=True) - 1).min(), worst_month=r.min(), best_month=r.max())
    m["months_trough_to_recovery"] = (None if not len(back) else
                                      (back.index[0].year - trough.year) * 12 + back.index[0].month - trough.month)
    return {k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in m.items()}


def table(bt, against="B1"):
    rf, n = bt["rf"], bt["net"]
    return pd.DataFrame({c: measures(n[c], n[against], rf) for c in n.columns}).T


def summary_row(r, b, rf):
    m = measures(r, b, rf)
    return {**{k: m[k] for k in ("cagr", "ann_return", "ann_vol", "sharpe", "max_drawdown", "alpha_ann", "information_ratio")},
            "benchmark_cagr": measures(b, b, rf)["cagr"], "benchmark_sharpe": measures(b, b, rf)["sharpe"]}


def cost_table(bt, grid=(0, 10, 25, 50)):
    """Both portfolios pay the same cost per trade; 50 bps = the lecture's all-in retail figure."""
    return pd.DataFrame({c: summary_row(at_cost(bt, "Strategy", c), at_cost(bt, "B1", c), bt["rf"]) for c in grid}).T


def breakeven(bt, bench="B1", on="cagr", max_bps=2000):
    """Cost per trade (bps) at which the strategy's CAGR (or Sharpe) equals the benchmark's, both paying it."""
    rf = bt["rf"]
    stat = ((lambda x: (1 + x).prod() ** (12 / len(x)) - 1) if on == "cagr" else
            (lambda x: (x - rf).mean() / (x - rf).std() * np.sqrt(12)))
    grid = np.arange(0, max_bps + 1.0)
    gap = np.array([stat(at_cost(bt, "Strategy", c)) - stat(at_cost(bt, bench, c)) for c in grid])
    if gap[0] <= 0:
        return None                                   # no edge even at zero cost
    if (gap > 0).all():
        return float("inf")
    i = int(np.argmax(gap <= 0))
    return float(grid[i - 1] + gap[i - 1] / (gap[i - 1] - gap[i]))     # linear interpolation between two bps


def rolling(r, b, rf, window=36):
    """Rolling Sharpe ratio and beta (W3: rolling cov / var), past data only."""
    ex, exb = r - rf, b - rf
    return pd.DataFrame({"sharpe": ex.rolling(window).mean() / ex.rolling(window).std() * np.sqrt(12),
                         "beta": ex.rolling(window).cov(exb) / exb.rolling(window).var()}).dropna()


def calendar_years(net):
    return (1 + net).groupby(net.index.year).prod() - 1


def monte_carlo(returns, n_sim=10_000, months=120, initial=10_000, seed=2270):
    """Lecture 5.3: seeded simulation, many paths, percentile fan. Each path draws 120 months at random from
    our own history (the same months for every column, so crises hit both portfolios together)."""
    np.random.seed(seed)
    X = returns.to_numpy()
    paths = np.zeros((n_sim, months + 1, X.shape[1]))
    for i in range(n_sim):
        rows = np.random.randint(0, len(X), months)
        paths[i] = initial * np.vstack([np.ones(X.shape[1]), np.cumprod(1 + X[rows], axis=0)])
    worst = (paths / np.maximum.accumulate(paths, axis=1) - 1).min(axis=1)
    q = [5, 10, 25, 50, 75, 90, 95]
    summary, bands = {}, {}
    for k, c in enumerate(returns.columns):
        f = paths[:, -1, k]
        bands[c] = pd.DataFrame(np.percentile(paths[:, :, k], q, axis=0).T, columns=[f"p{x}" for x in q])
        summary[c] = {**{f"p{x}": float(np.percentile(f, x)) for x in q}, "mean": float(f.mean()),
                      "prob_below_start": float((f < initial).mean()), "prob_drawdown_over_20pct": float((worst[:, k] < -0.2).mean()),
                      "median_max_drawdown": float(np.median(worst[:, k])),
                      "median_cagr": float((np.median(f) / initial) ** (12 / months) - 1)}
    if X.shape[1] > 1:
        summary["prob_first_beats_second"] = float((paths[:, -1, 0] > paths[:, -1, 1]).mean())
    return dict(summary=summary, bands=bands, n_sim=n_sim, months=months, initial=initial, seed=seed,
                columns=list(returns.columns))
