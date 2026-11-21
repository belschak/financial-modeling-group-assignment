"""BP Trend-Guarded Multi-Asset: interactive backtest (Nova SBE 2270 Financial Modeling, Group BP).

Run locally:  streamlit run app.py
Every number comes from fm_backtest.py, the same engine file the submitted notebook runs.
"""
from __future__ import annotations

import io
import math
import time
from contextlib import contextmanager

import pandas as pd
import streamlit as st

import charts
import core
import data_layer as dl
import fm_backtest as fb

REPO_URL = "https://github.com/belschak/fm-2270-backtest-app"
NOTEBOOK_URL = ""  # Colab link: filled in by the group once the notebook is shared
GROUP = ("Tim Fischer, David Konrad Belschak, Tom Nico H Croe, Lennart Schmülling, Fridolin Treibig, "
         "Bastian Volkery")

st.set_page_config(page_title="BP Trend-Guarded Multi-Asset | Backtest", page_icon="📈", layout="wide",
                   initial_sidebar_state="auto")

st.markdown(
    """
    <style>
      [data-testid="stMetricValue"], [data-testid="stDataFrame"], .tabnum { font-variant-numeric: tabular-nums; }
      [data-testid="stMetric"] { border: 1px solid rgba(128,138,155,.28); border-radius: .4rem;
                                 padding: .7rem .9rem .5rem; }
      [data-testid="stMetricLabel"] p { font-size: .85rem; opacity: .85; }
      .lede { font-size: 1.02rem; line-height: 1.55; max-width: 60rem; opacity: .92; margin-top: -.3rem; }
      .src { font-size: .78rem; opacity: .7; line-height: 1.45; }
      .block-container { padding-top: 2.4rem; max-width: 76rem; }
      .meta { text-align: right; }
      @media (max-width: 640px) { .meta { text-align: left; } }
    </style>
    """,
    unsafe_allow_html=True,
)

ENGINE_SHA = fb.engine_sha256()
DISCLAIMER = "Hypothetical back-tested results. Past performance does not predict future returns."
COST_STEPS = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100]


@st.cache_data(ttl="5m", show_spinner=False)
def _commit() -> str:
    """Short git commit of the running code (Streamlit Cloud deploys a git checkout and hot-reloads pushes,
    so this is re-read every few minutes rather than once per server)."""
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=str(dl.DATA_DIR.parent))
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


COMMIT = _commit()
REBAL = {"M": "Monthly", "Q": "Quarterly", "A": "Annually", "none": "Never (only on signal switches)"}
LIVE_RETRY_AFTER_S = 600  # after a failed live download, use the snapshot for 10 minutes before trying again

# ---------------------------------------------------------------- state
for k, v in core.DEFAULTS.items():
    if k not in ("start", "end"):
        st.session_state.setdefault(k, list(v) if k == "tickers" else v)
st.session_state.setdefault("data_pref", "live")
st.session_state.setdefault("period_rev", 0)   # bumped by Reset: gives the period slider a fresh identity


def reset_defaults():
    for k, v in core.DEFAULTS.items():
        if k not in ("start", "end"):
            st.session_state[k] = list(v) if k == "tickers" else v
    st.session_state.pop(f"period_{st.session_state['period_rev']}", None)
    st.session_state["period_rev"] += 1


# ---------------------------------------------------------------- data + runs (cached)
@st.cache_data(ttl="12h", show_spinner="Downloading prices (Yahoo Finance) and rates (FRED, ECB)...")
def live_data(engine_sha: str) -> dict:
    # engine_sha in the cache key: a new engine (new data sources) never reuses an old download.
    return dl.load_live()  # raises on failure, and failures are never cached here


@st.cache_data(show_spinner=False)
def snapshot_data(file_stamp: float) -> dict:
    return dl.load_snapshot()


@st.cache_resource(show_spinner=False)
def _live_failure() -> dict:
    """Server-wide memory of the last failed live download, so a throttled server is not retried on every click."""
    return {}


def get_data(pref: str) -> tuple[dict, str | None]:
    """Returns (data, warning). Called ONCE per page run; everything below uses this exact data."""
    snap_ok = dl.snapshot_available()
    if pref == "snapshot":
        if not snap_ok:
            raise RuntimeError("The stored data snapshot is not part of this deployment. Choose live data.")
        return snapshot_data(dl.SNAP_CSV.stat().st_mtime), None
    fail = _live_failure()
    recent = fail.get("t") and time.time() - fail["t"] < LIVE_RETRY_AFTER_S
    if not recent:
        try:
            data = live_data(ENGINE_SHA)
            fail.clear()
            return data, None
        except Exception as e:  # noqa: BLE001
            fail.update(t=time.time(), err=type(e).__name__)
    if snap_ok:
        snap = snapshot_data(dl.SNAP_CSV.stat().st_mtime)
        return snap, (
            f"Live data unavailable, showing snapshot as of {snap['retrieved_at']}. "
            f"({fail.get('err', 'download error')}: Yahoo Finance sometimes throttles shared cloud servers; same "
            "sources and same code. The app tries live data again after a few minutes.)")
    raise RuntimeError("Market data could not be downloaded right now.")


# Cached computations take the page's data as `_data` (not hashed); `data_stamp` identifies it in the cache key,
# so a result is always computed from exactly the data the page says it shows.
@st.cache_data(show_spinner="Running the backtest...", max_entries=128)
def run_cached(ui_items: tuple, data_stamp: str, engine_sha: str, _data: dict) -> core.Result:
    ui = dict(ui_items)
    ui["tickers"] = list(ui["tickers"])
    return core.run(ui, _data)


@st.cache_data(show_spinner="Simulating 10,000 ten-year paths...", max_entries=32)
def mc_cached(ui_items: tuple, data_stamp: str, engine_sha: str, _data: dict) -> dict:
    return core.monte_carlo(run_cached(ui_items, data_stamp, engine_sha, _data))


@st.cache_data(show_spinner="Simulating the cautious variant...", max_entries=32)
def mc_haircut_cached(ui_items: tuple, data_stamp: str, engine_sha: str, _data: dict) -> dict:
    return core.monte_carlo_haircut(run_cached(ui_items, data_stamp, engine_sha, _data))


@st.cache_data(show_spinner="Running the notebook's robustness checks...", max_entries=32)
def rob_cached(ui_items: tuple, data_stamp: str, engine_sha: str, _data: dict) -> dict:
    return core.robustness(run_cached(ui_items, data_stamp, engine_sha, _data), _data)


@st.cache_data(show_spinner="Running the four window lengths...", max_entries=32)
def sma_cached(ui_items: tuple, data_stamp: str, engine_sha: str, _data: dict) -> dict:
    ui = dict(ui_items)
    ui["tickers"] = list(ui["tickers"])
    return core.sma_stability(ui, _data)


# ---------------------------------------------------------------- load data first (sidebar needs the date range)
try:
    data, data_warning = get_data(st.session_state["data_pref"])
except Exception as e:  # noqa: BLE001
    st.error(f"{e} Please reload in a few minutes.", icon=":material/cloud_off:")
    st.stop()
last_month = dl.last_complete_month(data, list(core.ASSET_NAMES))
months = pd.period_range("2007-01", last_month.strftime("%Y-%m"), freq="M").strftime("%Y-%m").tolist()

# ---------------------------------------------------------------- sidebar: assumptions
with st.sidebar:
    st.markdown("### Your assumptions")
    st.caption("Change any input and every number recalculates. The defaults reproduce the prospectus and the notebook.")

    st.markdown("**Trend rule**")
    st.slider("Moving-average window (months)", *core.SMA_RANGE, key="sma_window",
              help="An asset is held only while its month-end price is above its average price over this many "
                   "months. 10 comes from Faber (2007); we did not optimise it. 6 to 12 is the range Faber shows "
                   "works similarly (a stability check, not a search for the best value).")
    st.radio("Signal delay (months)", [1, 2], key="signal_lag", horizontal=True,
             help="1: the signal from the close of month t sets the holdings for month t+1. 2: act one month "
                  "later, a fully safe version with zero look-ahead risk.")
    st.selectbox("Rebalance back to target", list(REBAL), format_func=REBAL.get, key="rebalance",
                 help="Between these dates the holdings drift with the markets. A signal switch always triggers "
                      "a trade back to target at that month-end.")

    st.markdown("**Costs**")
    st.select_slider("Trading cost (bps per trade, one-way)", options=COST_STEPS, key="cost_bps",
                     help="Charged on every euro bought or sold (1 bp = 0.01%). 10 bps = fund-level trading cost "
                          "(base case). 50 bps = the lecture's conservative all-in figure for a retail investor "
                          "trading the ETFs alone (stress case). Benchmarks pay the same cost on their trades.")

    st.markdown("**Investor**")
    st.radio("Base currency", ["EUR", "USD"], key="base_ccy", horizontal=True,
             help="EUR: US-listed fund returns converted to euro; cash earns the euro short-term rate. USD: no "
                  "conversion; cash earns the US 3-month T-bill rate. Trade signals always use each fund's own USD "
                  "price.")
    if core.HEDGE_KEY:
        st.toggle("Hedge bond sleeve to EUR", key="hedge", disabled=st.session_state["base_ccy"] != "EUR",
                  help="On: the US Treasury slice is currency-hedged (its return plus the EUR-USD rate difference), "
                       "as a euro investor would usually hold bonds. Equities, real estate and commodities stay "
                       "unhedged. Applies to the strategy and both benchmarks.")
    # value= makes it a RANGE slider (without it Streamlit treats it as single-value and resets the range).
    # The key changes on Reset, so the browser shows the default range again (a reused key keeps its old range).
    PKEY = f"period_{st.session_state['period_rev']}"
    default_period = (core.DEFAULTS["start"], min(core.DEFAULTS["end"], months[-1]))
    if PKEY in st.session_state and any(m not in months for m in st.session_state[PKEY]):
        del st.session_state[PKEY]
    st.select_slider("Backtest period", options=months, key=PKEY,
                     value=st.session_state.get(PKEY, default_period),
                     help="Earliest start is Jan 2007: the commodity fund (DBC) starts in Feb 2006 and the rule needs "
                          "a full moving-average window first. Jan 2007 is also after the rule was published.")

    st.markdown("**Assets in the portfolio**")
    st.pills("Assets", list(core.ASSET_NAMES), selection_mode="multi", key="tickers",
             format_func=lambda t: f"{t} · {core.ASSET_NAMES[t].split(' (')[0]}", label_visibility="collapsed",
             help="Each selected asset gets an equal slice (1/n). Benchmark B1 holds the same assets.")

    st.markdown("**Benchmark for alpha, beta and IR**")
    st.radio("Benchmark", [core.BENCH_B1, core.BENCH_B2], key="primary_benchmark", label_visibility="collapsed",
             format_func=lambda b: {core.BENCH_B1: f"{core.BENCH_B1} (same assets)"}.get(b, b),
             help="B1 holds the same assets in equal weights, rebalanced monthly, so it isolates what the trend "
                  "filter adds. B2 is the 60% equity / 40% bond mix the client could buy instead.")

    with st.expander("Data source"):
        st.radio("Data", ["live", "snapshot"], key="data_pref", label_visibility="collapsed",
                 format_func=lambda s: "Live: Yahoo Finance, FRED, ECB" if s == "live" else "Stored snapshot (offline)")
        st.caption("Live data are cached for 12 hours. The snapshot only steps in if Yahoo throttles the server.")

    st.button("Reset to prospectus defaults", on_click=reset_defaults, width="stretch")

ui = {k: st.session_state[k] for k in core.DEFAULTS if k not in ("start", "end")}
ui["start"], ui["end"] = st.session_state[PKEY]
ui["tickers"] = tuple(t for t in core.ASSET_NAMES if t in (st.session_state["tickers"] or []))
is_default = all(ui[k] == core.DEFAULTS[k] for k in core.DEFAULTS)
start_note = None
if len(ui["tickers"]) >= 2:
    # A longer average or delay needs more history than the youngest fund has: start later instead of failing.
    first_ok = core.earliest_start(data, ui["tickers"], ui["sma_window"], ui["signal_lag"])
    if pd.Timestamp(ui["start"] + "-01") + pd.offsets.MonthEnd(0) < first_ok:
        start_note = (f"Start moved to {first_ok:%b %Y}: with a {ui['sma_window']}-month average and a "
                      f"{ui['signal_lag']}-month delay, the youngest fund needs that much history first.")
        ui["start"] = first_ok.strftime("%Y-%m")

# ---------------------------------------------------------------- header
st.title(core.STRATEGY)
st.markdown(
    "<p class='lede'>Five broad asset classes, an equal slice each. At every month-end an asset stays in the "
    "portfolio only while its price is above its 10-month average; otherwise its slice waits in cash. "
    "Designed for cautious euro-area savers about 10 years from retirement.</p>",
    unsafe_allow_html=True,
)
h1, h2 = st.columns([1, 1], vertical_alignment="center")
with h1:
    if is_default:
        st.badge("Defaults: matches prospectus Table 1", icon=":material/verified:", color="green")
    else:
        st.badge("Custom assumptions: numbers differ from the prospectus", icon=":material/tune:", color="orange")
data_as_of = (f"Data as of {data['retrieved_at']} ({'live download' if data['origin'] == 'live' else 'stored snapshot'}), "
              f"latest complete month {last_month:%b %Y}")
if data_warning:
    st.warning(data_warning, icon=":material/cloud_off:")
if start_note:
    st.info(start_note, icon=":material/history:")

if len(ui["tickers"]) < 2:
    st.warning("Select at least two assets in the sidebar.")
    st.stop()
if (pd.Period(ui["end"], "M") - pd.Period(ui["start"], "M")).n < 23:
    st.warning("Choose a backtest period of at least 24 months.")
    st.stop()

UI_ITEMS = tuple(sorted(ui.items()))
DATA_STAMP = f"{data['origin']}|{data['retrieved_at']}"
CACHE_ARGS = (UI_ITEMS, DATA_STAMP, ENGINE_SHA, data)
try:
    res = run_cached(*CACHE_ARGS)
except ValueError as e:
    msg = f"The backtest cannot run with these settings: {e}"
    if "not enough" in str(e).lower() and "history" in str(e).lower():
        youngest = max(data["prices_usd"][t].first_valid_index() for t in ui["tickers"])
        earliest = youngest + pd.offsets.MonthEnd(int(ui["sma_window"]) - 1 + int(ui["signal_lag"]))
        msg = (f"With a {ui['sma_window']}-month average and a {ui['signal_lag']}-month delay, the youngest selected "
               f"fund needs history until {earliest:%b %Y} before the first decision. Move the start of the backtest "
               f"period to {earliest:%Y-%m} or later, or shorten the window.")
    st.error(msg, icon=":material/history:")
    st.stop()
except Exception as e:  # noqa: BLE001  (never show a traceback)
    st.error(f"The backtest could not run with these settings ({type(e).__name__}: {e}). Try other settings or "
             "press Reset.", icon=":material/error:")
    st.stop()

M = res.metrics
S, P = core.STRATEGY, res.primary
bn = P.split(" ", 1)[0]
ccy = ui["base_ccy"]
pal = charts.PALETTE
LBL_S, LBL_G = "Strategy (net)", "Strategy before costs"
styles = {
    LBL_S: dict(color=pal["strategy"], width=2.6),
    LBL_G: dict(color=pal["strategy"], width=1.2, dash="dot"),
    core.BENCH_B1: dict(color=pal["b1"], width=2),
    core.BENCH_B2: dict(color=pal["b2"], width=2, dash="dash"),
}
first, last = res.index[0], res.index[-1]
w_s, w_b = core.wealth(res.strat_net), core.wealth(res.bench_net[P])

with h2:
    st.markdown(f"<div class='src meta'>{first:%b %Y} to {last:%b %Y} · {len(res.index)} months · "
                f"{ccy} · net of {ui['cost_bps']} bps trading costs</div>", unsafe_allow_html=True)
if res.sri:
    with h1:
        st.badge(f"Risk class {res.sri['sri']} of 7 (indicative SRI)",
                 icon=":material/speed:", color="blue",
                 help="PRIIPs summary risk indicator, authors' calculation, 1 = lowest, 7 = highest risk. "
                      + ("From daily back-tested returns of the last five years over a 10-year holding period "
                         "(Cornish-Fisher VaR), the higher of the strategy and the unfiltered 1/n mix. "
                         if str(res.sri.get("method", "")).startswith("daily") else
                         "From the last 60 monthly returns plus one class (only monthly data available here), the "
                         "higher of the strategy and the unfiltered 1/n mix. ")
                      + "Indicative only.")

st.markdown(
    f"**10,000 {ccy}** invested at the end of {first - pd.offsets.MonthEnd(1):%b %Y} would have grown to "
    f"**{10000 * w_s.iloc[-1]:,.0f} {ccy}** by {last:%b %Y} ({bn}: {10000 * w_b.iloc[-1]:,.0f} {ccy}). "
    f"Largest fall from a previous high: **{-M.loc['max_drawdown', S]:.1%}** ({bn}: {-M.loc['max_drawdown', P]:.1%})."
)
st.caption(DISCLAIMER)


def pct(x, d=1):
    if x is None or pd.isna(x):
        return "n/a"
    return f"{0.0 if abs(x) < 0.5 * 10 ** -(d + 2) else x:.{d}%}"  # no "-0.0%"


def num(x, d=2):
    if x is None or pd.isna(x):
        return "n/a"
    return f"{0.0 if abs(x) < 0.5 * 10 ** -d else x:.{d}f}"


HELP = {
    "ann_return": "Average monthly return x 12 (arithmetic, as the brief asks). The growth rate actually earned "
                  "(CAGR) is in the full table.",
    "ann_vol": "How much returns swing: standard deviation of monthly returns x sqrt(12). Lower means a smoother ride.",
    "sharpe": "Return above the risk-free rate per unit of risk: mean monthly excess return / its standard deviation, "
              "x sqrt(12). Higher means a better reward for the risk taken.",
    "alpha_ann": "Return beyond what the exposure to the benchmark explains (Jensen's alpha on monthly excess "
                 "returns), x 12. The t-statistic tells whether it is distinguishable from luck (roughly |t| > 2).",
    "information_ratio": "Average return above the benchmark divided by tracking error (the volatility of that "
                         "difference), x sqrt(12). How consistently the strategy beats the benchmark.",
    "beta": "Sensitivity to the benchmark: covariance / variance of monthly excess returns. Not annualised. "
            "0.4 means it moves about 40% as much as the benchmark.",
}

# ---------------------------------------------------------------- the six required measures
cards = [
    ("Average return p.a.", pct(M.loc["ann_return", S]), M.loc["ann_return", S] - M.loc["ann_return", P], "pp", "normal", "ann_return"),
    ("Volatility p.a.", pct(M.loc["ann_vol", S]), M.loc["ann_vol", S] - M.loc["ann_vol", P], "pp", "inverse", "ann_vol"),
    ("Sharpe ratio", num(M.loc["sharpe", S]), M.loc["sharpe", S] - M.loc["sharpe", P], "x", "normal", "sharpe"),
    (f"Alpha p.a. vs {bn}", f"{pct(M.loc['alpha_ann', S])} (t = {num(M.loc['alpha_t', S], 1)})", None, "", "off", "alpha_ann"),
    (f"Information ratio vs {bn}", num(M.loc["information_ratio", S]), None, "", "off", "information_ratio"),
    (f"Beta vs {bn}", num(M.loc["beta", S]), None, "", "off", "beta"),
]
grid_rows = [st.columns(3), st.columns(3)]
for i, (label, value, delta, unit, dcol, key) in enumerate(cards):
    col = grid_rows[i // 3][i % 3]
    if delta is not None and not pd.isna(delta):
        dtxt = f"{delta * 100:+.1f} pp vs {bn}" if unit == "pp" else f"{delta:+.2f} vs {bn}"
        col.metric(label, value, dtxt, delta_color=dcol, help=HELP[key])
    else:
        col.metric(label, value, help=HELP[key])

# ---------------------------------------------------------------- tabs
@contextmanager
def guard(view: str):
    """A failing view shows a short notice instead of a traceback, and the other tabs keep working."""
    try:
        yield
    except Exception as e:  # noqa: BLE001
        st.info(f"{view} cannot be shown with these settings ({e}). The other tabs are unaffected.",
                icon=":material/info:")


t_perf, t_crisis, t_table, t_hold, t_cost, t_sma, t_rob, t_mc, t_method = st.tabs(
    ["Performance", "Crisis replay", "All metrics", "Holdings", "Costs", "Window stability", "Robustness",
     "10-year outlook",
     "Method"])

with t_perf, guard("This view"):
    c1, c2 = st.columns(2)
    log = c1.toggle("Log scale", value=False, help="Equal distances on the axis = equal percentage changes.")
    show_gross = c2.toggle("Show strategy before costs", value=False)
    wealth = {LBL_S: w_s}
    if show_gross:
        wealth[LBL_G] = core.wealth(res.strat_gross)
    for b in (core.BENCH_B1, core.BENCH_B2):
        wealth[b] = core.wealth(res.bench_net[b])
    st.markdown(f"##### Growth of 1 {ccy}, net of costs")
    st.caption(DISCLAIMER + " The fund did not exist over this period.")
    st.plotly_chart(charts.cumulative(wealth, styles, pal, log=log), width="stretch", config={"displayModeBar": False})
    st.markdown("##### Drawdown: fall from the previous high")
    dd = {LBL_S: core.drawdown(res.strat_net)}
    dd.update({b: core.drawdown(res.bench_net[b]) for b in (core.BENCH_B1, core.BENCH_B2)})
    st.plotly_chart(charts.drawdowns(dd, styles, pal), width="stretch", config={"displayModeBar": False})
    st.markdown(f"##### Calendar-year returns: strategy vs {bn}")
    st.caption(DISCLAIMER)
    st.plotly_chart(charts.annual_bars(res.annual, ["Strategy", P], [LBL_S, P],
                                       [pal["strategy"], pal["b1"] if P == core.BENCH_B1 else pal["b2"]], pal),
                    width="stretch", config={"displayModeBar": False})
    st.markdown("<div class='src'>Source: Yahoo Finance (adjusted close, dividends reinvested), FRED, ECB; group "
                "calculations. All series start at exactly 1.00 on the same date.</div>", unsafe_allow_html=True)

ROWS = [
    ("ann_return", "Average return p.a.", pct, True),
    ("ann_vol", "Volatility p.a.", pct, True),
    ("sharpe", "Sharpe ratio", num, True),
    ("alpha_ann", f"Alpha p.a. (vs {bn})", pct, True),
    ("information_ratio", f"Information ratio (vs {bn})", num, True),
    ("beta", f"Beta (vs {bn}, not annualised)", num, True),
    ("alpha_t", "Alpha t-statistic", lambda x: num(x, 1), False),
    ("alpha_t_nw", "Alpha t-statistic (Newey-West)", lambda x: num(x, 1), False),
    ("cagr", "Growth rate p.a. (CAGR)", pct, False),
    ("max_drawdown", "Maximum drawdown", pct, False),
    ("months_trough_to_recovery", "Months from bottom back to the old high",
     lambda x: "not yet" if x is None or pd.isna(x) else f"{x:.0f}", False),
    ("worst_12m", "Worst 12 months", pct, False),
    ("tracking_error", f"Tracking error p.a. (vs {bn})", pct, False),
    ("information_ratio_regression", "Regression IR (alpha / residual volatility)", num, False),
    ("hit_rate_vs_benchmark", f"Share of months beating {bn}", lambda x: pct(x, 0), False),
    ("sortino", "Sortino ratio", num, False),
]
with t_table, guard("The metrics table"):
    st.caption(DISCLAIMER)
    cols = [S, f"{S} (before costs)", core.BENCH_B1, core.BENCH_B2]
    table = pd.DataFrame({c: [f(M.loc[k, c]) if k in M.index else "n/a" for k, _, f, _ in ROWS] for c in cols},
                         index=[lbl for _, lbl, _, _ in ROWS])
    table.columns = ["Strategy (net)", "Before costs", "B1 Static 1/n", "B2 60/40"]
    table.insert(0, "Brief", ["Required" if req else "Extra" for *_, req in ROWS])
    table.insert(0, "Measure", table.index)
    st.dataframe(table, width="stretch", hide_index=True, height=35 * (len(ROWS) + 1) + 3,
                 column_config={"Measure": st.column_config.TextColumn(width="medium", pinned=True),
                                "Brief": st.column_config.TextColumn(width="small")})
    st.caption(f"Monthly data, {first:%b %Y} to {last:%b %Y}, in {ccy}. Excess returns use the {ccy} risk-free rate. "
               f"Relative measures are against {P}; a benchmark against itself gives beta 1, alpha 0 (sanity check).")
    out = pd.DataFrame({"strategy_net": res.strat_net, "strategy_gross": res.strat_gross,
                        **{f"{k.split(' ', 1)[0]}_net": v for k, v in res.bench_net.items()}})
    d1, d2 = st.columns(2)
    d1.download_button("Download monthly returns (CSV)", out.to_csv(), "bp_backtest_monthly_returns.csv",
                       "text/csv", width="stretch")
    d2.download_button("Download metrics (CSV)", M.to_csv(), "bp_backtest_metrics.csv", "text/csv", width="stretch")

with t_hold, guard("The holdings view"):
    cash = res.held[core.CASH]
    st.caption(DISCLAIMER)
    st.markdown(f"##### On average {1 - cash.mean():.0%} invested and {cash.mean():.0%} in cash")
    st.plotly_chart(charts.weights_area(res.held, core.ASSET_NAMES, pal), width="stretch",
                    config={"displayModeBar": False})
    st.caption("Weights held during each month, after trading at its start. A slice moves fully to cash when its fund "
               "closes a month below its moving average, and back when it recovers.")

with t_cost, guard("The cost view"):
    st.caption(DISCLAIMER)
    tv = res.turnover


    def be_fmt(v, what):
        if v is None:
            return "none", f"Even at zero cost the strategy's {what} is below the benchmark's in this setting."
        if math.isinf(v):
            return "> 2000 bps", f"The strategy's {what} stays above the benchmark's at any realistic cost."
        return f"{v:.0f} bps", (f"One-way cost at which the strategy's {what} falls to the benchmark's "
                                f"(both pay the same cost on their own trades).")


    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Turnover p.a. (one-way)", pct(tv["turnover_pa"], 0),
              help="Half of the value bought plus sold in a year (one-way, the usual fund definition).")
    k2.metric("Cost drag p.a.", pct(tv["cost_drag_pa"], 2), help="Growth rate lost to trading costs per year.")
    t3, h3 = be_fmt(res.breakeven_bps, "growth rate (CAGR)")
    t4, h4 = be_fmt(res.breakeven_sharpe_bps, "Sharpe ratio")
    k3.metric(f"Breakeven on return vs {bn}", t3, help=h3)
    k4.metric(f"Breakeven on Sharpe vs {bn}", t4, help=h4)
    st.markdown("##### Value of 1 at the end of the sample, at different trading costs")
    grid = res.cost_grid[["Strategy", P]].rename(columns={"Strategy": "strategy", P: "benchmark"})
    be = res.breakeven_bps
    be_plot = be if (be is not None and not math.isinf(be) and be <= 100) else None
    st.plotly_chart(charts.cost_curve(grid, ui["cost_bps"], be_plot, (LBL_S, P), pal,
                                      ytitle=f"Final value of 1 {ccy} invested", yfmt=".2f"), width="stretch",
                    config={"displayModeBar": False})
    ahead = M.loc["cagr", S] > M.loc["cagr", P]
    st.caption(f"At {ui['cost_bps']} bps the strategy grows {'faster' if ahead else 'more slowly'} than {bn} "
               f"({pct(M.loc['cagr', S])} vs {pct(M.loc['cagr', P])} a year). " + (
               f"Risk-adjusted (Sharpe) it stays ahead up to {t4} per trade." if res.breakeven_sharpe_bps
               else "Risk-adjusted (Sharpe) it is behind even before costs."))

with t_crisis, guard("The crisis replay"):
    st.caption("How the strategy behaved in the big sell-offs of the sample, next to both benchmarks, and when each "
               "slice moved to cash. " + DISCLAIMER)
    in_sample = [c for c in core.CRISES if core.crisis_view(res, c[0], c[1])["in_sample"]]
    if not in_sample:
        st.info("None of the crisis windows lies inside the backtest period you chose.")
    else:
        pick = st.radio("Crisis", [c[2] for c in in_sample], horizontal=True, key="crisis_pick",
                        label_visibility="collapsed")
        s0, s1, lbl = next(c for c in in_sample if c[2] == pick)
        cv = core.crisis_view(res, s0, s1)
        st.markdown(f"**Return over the crisis window, {cv['window'][0]:%b %Y} to {cv['window'][1]:%b %Y}**")
        cols = st.columns(len(cv["returns"]))
        for colw, (name, v) in zip(cols, cv["returns"].items()):
            colw.metric(LBL_S if name == "Strategy" else name, pct(v))
        cpaths = {LBL_S if k == "Strategy" else k: v for k, v in cv["paths"].items()}
        st.plotly_chart(charts.crisis_paths(cpaths, styles, cv["window"], pal), width="stretch",
                        config={"displayModeBar": False})
        if cv["signals"] is not None:
            st.markdown("##### Which slices were invested (dark) or in cash (light)")
            st.plotly_chart(charts.signal_strip(cv["signals"], core.ASSET_NAMES, pal), width="stretch",
                            config={"displayModeBar": False})
            if cv["events"]:
                ev = pd.DataFrame(cv["events"]).rename(columns={"month_held": "Month held", "ticker": "Fund",
                                                               "action": "Change"})
                with st.expander(f"{len(ev)} switches in this view"):
                    st.dataframe(ev, hide_index=True, width="stretch")
        st.caption("Paths start at 1.00 three months before the window (or at the start of your sample) so you see the "
                   "run-up. Signals use month-end prices and are acted on with your signal delay.")

with t_sma, guard("The window comparison"):
    stab = sma_cached(*CACHE_ARGS)
    st.markdown("##### Does the result depend on the 10-month window?")
    st.caption("The 10-month window comes from Faber (2007) and was fixed before looking at our results. This view "
               "is a stability check, not a menu: picking the window that looks best afterwards would be data-snooping "
               f"and would overstate future results. All four use the same sample, from {stab['start']:%b %Y}, so "
               "the longest window has enough history. " + DISCLAIMER)
    rows, wl = [], {}
    for n, rr in stab["results"].items():
        mm = rr.metrics[core.STRATEGY]
        rows.append({"Window": f"{n} months" + (" (paper)" if n == 10 else ""), "CAGR": pct(mm["cagr"]),
                     "Volatility": pct(mm["ann_vol"]), "Sharpe": num(mm["sharpe"]),
                     "Max drawdown": pct(mm["max_drawdown"]), f"Alpha vs {bn}": pct(mm["alpha_ann"]),
                     "Turnover p.a.": pct(rr.turnover["turnover_pa"], 0)})
        wl[n] = core.wealth(rr.strat_net)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.plotly_chart(charts.stability_lines(wl, 10, pal), width="stretch", config={"displayModeBar": False})
    sh = [rr.metrics.loc["sharpe", core.STRATEGY] for rr in stab["results"].values()]
    worst_dd = min(rr.metrics.loc["max_drawdown", core.STRATEGY] for rr in stab["results"].values())
    bench_dd = next(iter(stab["results"].values())).metrics.loc["max_drawdown", P]
    st.caption(f"Sharpe ratios range from {min(sh):.2f} to {max(sh):.2f} across the four windows. The deepest "
               f"drawdown of any window is {pct(worst_dd)}, against {pct(bench_dd)} for {bn} on the same sample. "
               "The window you chose in the sidebar does not change this table.")

with t_rob, guard("The robustness checks"):
    rb = rob_cached(*CACHE_ARGS)
    st.caption("The notebook's own robustness checks, run for your current settings. Each one changes a single "
               "assumption, to see whether the result survives it. " + DISCLAIMER)

    def tbl(df, cols, names, idx_name):
        t = df[[c for c in cols if c in df.columns]].copy()
        fmt = {"cagr": pct, "ann_vol": pct, "max_drawdown": pct, "alpha_ann": pct, "sharpe": num,
               "information_ratio": num, "benchmark_sharpe": num, "turnover_pa": lambda x: pct(x, 0)}
        for c in t.columns:
            t[c] = [fmt.get(c, num)(v) for v in t[c]]
        t = t.rename(columns=names)
        t.insert(0, idx_name, t.index)
        return t

    names = {"cagr": "CAGR", "ann_vol": "Volatility", "sharpe": "Sharpe", "max_drawdown": "Max drawdown",
             "alpha_ann": f"Alpha vs {bn}", "information_ratio": f"IR vs {bn}", "benchmark_sharpe": f"{bn} Sharpe",
             "turnover_pa": "Turnover p.a."}
    cols = ["cagr", "ann_vol", "sharpe", "max_drawdown", "alpha_ann", "benchmark_sharpe"]
    lag = rb["rob"].get("lag")
    if lag is not None and len(lag):
        st.markdown("##### When are trades executed?")
        st.dataframe(tbl(lag, cols, names, "Execution"), hide_index=True, width="stretch")
        st.caption("Lag 1 trades at the month-end close the signal is computed on (as in Faber 2007). The next "
                   "trading day's close is the realistic version; lag 2 waits a full month. Lag 0 uses the same "
                   "month's return and is shown only to prove the look-ahead test bites: it is not implementable.")
    ex = rb.get("extra", {})
    tl = ex.get("timing_luck")
    if tl is not None and len(tl):
        st.markdown("##### Does it matter which day of the month we rebalance?")
        st.dataframe(tbl(tl, cols, names, "Signal and trade day"), hide_index=True, width="stretch")
        base_sh = tl["sharpe"].iloc[0]
        rank = int((tl["sharpe"] > base_sh).sum()) + 1
        st.caption(f"Month-end ranks {rank} of {len(tl)} days on Sharpe; other days give {tl['sharpe'].iloc[1:].min():.2f} "
                   f"to {tl['sharpe'].iloc[1:].max():.2f}. Part of the headline result is timing luck (Hoffstein, "
                   "Sibears and Faber 2019), which is why the prospectus reports this range.")
    elif ex.get("timing_luck_skipped") is not None or tl is not None:
        st.info("The day-of-month check needs daily prices, which this data source does not include.")
    sh = ex.get("split_halves")
    if sh is not None and len(sh):
        st.markdown("##### First half against second half of the sample")
        t = sh.copy()
        st.dataframe(tbl(t.set_index(t["period"] + " · " + t["portfolio"]), ["cagr", "ann_vol", "sharpe", "max_drawdown"],
                         names, "Period · portfolio"), hide_index=True, width="stretch")
    ci = ex.get("sharpe_diff_ci")
    if ci:
        st.markdown(f"##### Is the Sharpe advantage over {bn} more than luck?")
        st.markdown(f"Sharpe difference **{ci['diff']:+.2f}**, 95% interval **{ci['ci_low']:+.2f} to {ci['ci_high']:+.2f}** "
                    f"({ci['draws']:,} block-bootstrap draws, {ci['block']}-month blocks); the difference is positive in "
                    f"{ci['share_positive']:.0%} of draws. " + ("The interval includes zero, so the advantage is not "
                    "statistically certain." if ci['ci_low'] <= 0 <= ci['ci_high'] else "The interval excludes zero."))
    cba = ex.get("cost_by_asset")
    if cba is not None and len(cba):
        st.markdown("##### Costs by fund instead of one flat rate")
        st.dataframe(tbl(cba.rename(columns={"cagr_flat": "cagr", "sharpe_flat": "sharpe"})
                     .assign(cagr_by_asset=cba["cagr_by_asset"], sharpe_by_asset=cba["sharpe_by_asset"]),
                         ["cagr", "cagr_by_asset", "sharpe", "sharpe_by_asset"],
                         {"cagr": "CAGR (flat)", "cagr_by_asset": "CAGR (by fund)", "sharpe": "Sharpe (flat)",
                          "sharpe_by_asset": "Sharpe (by fund)"}, "Portfolio"), hide_index=True, width="stretch")
        st.caption("By fund: 2 bps for the equity and bond funds, 10 bps for real estate and commodities (wider spreads).")

with t_mc, guard("The 10-year outlook"):
    haircut = st.toggle("Cautious variant: halve the historical excess return", value=False,
                        help="Published rules often work less well after publication (McLean and Pontiff 2016). "
                             "This variant cuts each portfolio's average return above cash in half before "
                             "re-sampling.")
    mc_base = mc_cached(*CACHE_ARGS)
    mc = mc_haircut_cached(*CACHE_ARGS) if haircut else mc_base
    cfgm = res.cfg
    lo, hi = ("p10", "p90") if "p10" in mc["bands"]["Strategy"] else ("p5", "p95")
    lo_n, hi_n = int(lo[1:]), int(hi[1:])
    init = mc["initial"]
    st.markdown(f"##### {init:,.0f} {ccy} over the next {cfgm['mc_years']} years: range of outcomes")
    st.caption("This shows what could happen if the next 10 years resemble the back-tested period, re-sampled in "
               f"{cfgm['mc_block']}-month blocks ({mc['n_paths']:,} paths, fixed seed). It is not a forecast: it only "
               "replays the past sample, assumes its average return persists and ignores taxes. The investment may "
               "lead to a financial loss. " + DISCLAIMER)
    st.plotly_chart(charts.fan_chart(mc["bands"], {"Strategy": LBL_S, core.BENCH_B2: core.BENCH_B2},
                                     {"Strategy": pal["strategy"], core.BENCH_B2: pal["b1"]}, pal, lo, hi, init),
                    width="stretch", config={"displayModeBar": False})
    summ = mc["summary"]
    rows = []
    for name, lbl in (("Strategy", LBL_S), (core.BENCH_B2, core.BENCH_B2)):
        sm = summ[name]
        f_lo = sm.get(lo, sm.get("p5")); f_hi = sm.get(hi, sm.get("p95"))
        rows.append({"Portfolio": lbl, f"Unfavourable ({lo_n}th pct.)": f"{f_lo:,.0f}",
                     "Median": f"{sm.get('p50', sm.get('median')):,.0f}", f"Favourable ({hi_n}th pct.)": f"{f_hi:,.0f}",
                     "Chance of ending below start": pct(sm.get("prob_below_start", sm.get("prob_loss")), 1),
                     "Chance of a fall > 20% on the way": pct(sm["prob_drawdown_over_20pct"], 1)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    hc = mc_base.get("haircut_summary")
    if hc and not haircut:
        st.caption(f"Cautious variant (half of the historical excess return, because published rules tend to work "
                   f"less well after publication): median {hc['Strategy'].get('p50', hc['Strategy'].get('median')):,.0f} for the strategy and "
                   f"{hc[core.BENCH_B2].get('p50', hc[core.BENCH_B2].get('median')):,.0f} for {core.BENCH_B2}.")
    if "prob_first_beats_second" in summ:
        st.caption(f"The strategy ends ahead of {core.BENCH_B2} in {summ['prob_first_beats_second']:.0%} of the "
                   f"paths. Bands: dark = middle 50% of paths, light = {lo_n}th to {hi_n}th percentile. "
                   f"Values in {ccy}, after the trading costs you chose.")

with t_method, guard("The method note"):
    cfg = res.cfg
    st.markdown(f"""
**Data.** Daily adjusted closes (splits and dividends reinvested) from Yahoo Finance for SPY, EFA, IEF, VNQ and DBC,
reduced to the last close of each month. Risk-free rates and FX as downloaded for this run: USD rate
{data['sources']['rf_USD']}; EUR rate {data['sources']['rf_EUR']}; EUR/USD {data['sources']['fx']}.
US-listed funds stand in for the UCITS funds an EU investor would buy, because their history is longer.
In the EUR view, USD returns are converted with r_EUR = (1 + r_USD) x S(t-1) / S(t) - 1 (S = USD per EUR);
{"the bond slice (IEF) is EUR-hedged: r_USD + (euro overnight rate - US overnight rate EFFR), a covered-interest-"
 "parity approximation, while "
 "equities, real estate and commodities stay unhedged" if (cfg.get(core.HEDGE_KEY) and cfg['base_ccy'] == 'EUR')
 else "all slices are unhedged in this setting"}.

**Rule.** At each month-end an asset is "in" if its USD price is above its simple moving average of the last
{cfg['sma_window']} month-end prices (including the current one). Holdings decided at the close of month t are held
during month t+{cfg['signal_lag']}, so every decision uses only information available at the time. Each asset has a
equal capital slice of 1/n, held either in its fund or in cash (the euro overnight rate in EUR, the T-bill rate in
USD). Slices are reset to equal size {REBAL[cfg['rebalance']].lower()}; signals switch monthly in any case.

**Benchmarks.** B1 = the same assets in static equal weights, rebalanced monthly (what the trend filter adds).
B2 = 60% equity (SPY 36%, EFA 24%) and 40% IEF, rebalanced monthly (what the client would otherwise buy).
Both pay the same trading cost on their trades.

**Costs.** {cfg['cost_bps']:.0f} bps one-way on the value of every fund trade, deducted in the month of the trade.
Turnover = half the sum of absolute weight changes including cash, per year (one-way). Breakeven costs: the cost at
which the strategy's growth rate (CAGR), or its Sharpe ratio, falls to the benchmark's, with both paying it.

**Risk class.** Indicative PRIIPs summary risk indicator (1 to 7), authors' calculation: Cornish-Fisher VaR over a
10-year holding period from daily back-tested returns of the last five years (monthly weights drifting daily), the
higher of the strategy and the unfiltered 1/n mix. Without daily data the app falls back to the last 60 monthly
returns plus one class, as the regulation requires.

**Measures.** Simple returns throughout (they add up across assets; log returns do not). Average return = monthly
mean x 12; volatility = sample standard deviation x sqrt(12); Sharpe = mean excess return / its standard
deviation x sqrt(12); beta = cov / var of monthly excess returns, **not annualised**; alpha = mean excess return
minus beta x benchmark mean excess return, x 12, with its OLS t-statistic (Newey-West in the table); information ratio
= mean of (strategy minus benchmark) / its standard deviation x sqrt(12). Growth curves are cumprod(1 + r) with an
explicit start value of 1.00.

**Same code as the notebook.** All numbers come from `fm_backtest.py` version {fb.ENGINE_VERSION}
(SHA-256 `{ENGINE_SHA[:16]}...`), the engine file the submitted notebook runs. Tests in the repository check
that both files are byte-identical and that these defaults reproduce the notebook's results.

**Limitations.** A backtest is not a forecast. US-listed proxies; no taxes and no fund fees beyond those already in
the fund prices; the 10-month rule is famous, so part of its past success may not repeat (publication bias).
""")

# ---------------------------------------------------------------- footer
st.divider()
links = [f"[Source code on GitHub]({REPO_URL})",
         f"[Backtest notebook (Colab)]({NOTEBOOK_URL})" if NOTEBOOK_URL else "Backtest notebook: submitted with the prospectus"]
st.markdown(" · ".join(links))
st.markdown(f"<div class='src'>{data_as_of}. Code version {COMMIT}, engine {fb.ENGINE_VERSION} "
            f"(SHA-256 {ENGINE_SHA[:12]}). Nova SBE · 2270 Financial Modeling · Group BP: {GROUP}. Educational "
            f"project, not investment advice. {DISCLAIMER} Data: {dl.describe(data)}.</div>", unsafe_allow_html=True)
