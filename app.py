"""BP Trend-Guarded Multi-Asset: interactive backtest (Nova SBE 2270 Financial Modeling, Group BP).

Run locally:  streamlit run app.py
Every number comes from fm_backtest.py, the same engine file the submitted notebook runs.
"""
from __future__ import annotations

import io
import math

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
REBAL = {"M": "Monthly", "Q": "Quarterly", "A": "Annually", "none": "Never (only on signal switches)"}

# ---------------------------------------------------------------- state
for k, v in core.DEFAULTS.items():
    if k not in ("start", "end"):
        st.session_state.setdefault(k, list(v) if k == "tickers" else v)
st.session_state.setdefault("data_pref", "live")


def reset_defaults():
    for k, v in core.DEFAULTS.items():
        if k not in ("start", "end"):
            st.session_state[k] = list(v) if k == "tickers" else v
    st.session_state.pop("period", None)  # the slider falls back to its default range


# ---------------------------------------------------------------- data + runs (cached)
@st.cache_data(ttl=6 * 3600, show_spinner="Downloading prices (Yahoo Finance) and rates (FRED, ECB)...")
def live_data() -> dict:
    return dl.load_live()  # raises on failure, and failures are never cached


@st.cache_data(show_spinner=False)
def snapshot_data() -> dict:
    return dl.load_snapshot()


def get_data(pref: str) -> tuple[dict, str | None]:
    """Returns (data, warning). Live first; on failure the stored snapshot, with a visible warning."""
    if pref == "snapshot":
        return snapshot_data(), None
    try:
        return live_data(), None
    except Exception as e:  # noqa: BLE001
        if dl.snapshot_available():
            return snapshot_data(), (
                f"The live download failed just now ({type(e).__name__}). Yahoo Finance often limits requests from "
                "cloud servers, so the app is showing the stored data snapshot (same sources, same code). "
                "Reload in a few minutes for live data.")
        raise


@st.cache_data(show_spinner="Running the backtest...", max_entries=128)
def run_cached(ui_items: tuple, pref: str, data_stamp: str, engine_sha: str) -> core.Result:
    # engine_sha is part of the cache key: a new engine version never reuses old results.
    data, _ = get_data(pref)
    ui = dict(ui_items)
    ui["tickers"] = list(ui["tickers"])
    return core.run(ui, data)


# ---------------------------------------------------------------- load data first (sidebar needs the date range)
try:
    data, data_warning = get_data(st.session_state["data_pref"])
except Exception as e:  # noqa: BLE001
    st.error("Market data could not be downloaded right now and no stored snapshot is available. "
             f"Please reload in a few minutes. Details: {e}")
    st.stop()
last_month = dl.last_complete_month(data, list(core.ASSET_NAMES))
months = pd.period_range("2007-01", last_month.strftime("%Y-%m"), freq="M").strftime("%Y-%m").tolist()

# ---------------------------------------------------------------- sidebar: assumptions
with st.sidebar:
    st.markdown("### Your assumptions")
    st.caption("Change any input and every number recalculates. The defaults reproduce the prospectus and the notebook.")

    st.markdown("**Trend rule**")
    st.slider("Moving-average window (months)", 3, 24, key="sma_months",
              help="An asset is held only while its month-end price is above its average price over this many "
                   "months. 10 comes from Faber (2007); we did not optimise it.")
    st.radio("Signal delay (months)", [1, 2], key="signal_lag", horizontal=True,
             help="1: the signal from the close of month t sets the holdings for month t+1. 2: act one month "
                  "later, a fully safe version with zero look-ahead risk.")
    st.selectbox("Rebalance back to target", list(REBAL), format_func=REBAL.get, key="rebalance",
                 help="Between these dates the holdings drift with the markets. A signal switch always triggers "
                      "a trade back to target at that month-end.")

    st.markdown("**Costs**")
    st.slider("Trading cost (bps per trade, one-way)", 0, 100, step=1, key="cost_bps",
              help="Charged on every euro bought or sold (1 bp = 0.01%). 10 bps is a typical all-in cost of an "
                   "ETF trade at an EU online broker. Benchmarks pay the same cost on their trades.")

    st.markdown("**Investor**")
    st.radio("Base currency", ["EUR", "USD"], key="base_ccy", horizontal=True,
             help="EUR: US-listed fund returns converted to euro without currency hedging; cash earns the euro "
                  "3-month rate. USD: no conversion; cash earns the US 3-month T-bill rate. Trade signals always "
                  "use each fund's own USD price.")
    # value= makes it a RANGE slider (without it Streamlit treats it as single-value and resets the range).
    default_period = (core.DEFAULTS["start"], min(core.DEFAULTS["end"], months[-1]))
    if "period" in st.session_state and any(m not in months for m in st.session_state["period"]):
        del st.session_state["period"]
    st.select_slider("Backtest period", options=months, key="period",
                     value=st.session_state.get("period", default_period),
                     help="Earliest start is Jan 2007: the commodity fund (DBC) starts in Feb 2006 and the rule needs "
                          "a full moving-average window first. Jan 2007 is also after the rule was published.")

    st.markdown("**Assets in the portfolio**")
    st.pills("Assets", list(core.ASSET_NAMES), selection_mode="multi", key="tickers",
             format_func=lambda t: f"{t} · {core.ASSET_NAMES[t].split(' (')[0]}", label_visibility="collapsed",
             help="Each selected asset gets an equal slice (1/n). Benchmark B1 holds the same assets.")

    st.markdown("**Benchmark for alpha, beta and IR**")
    st.radio("Benchmark", [core.BENCH_B1, core.BENCH_B2], key="primary_benchmark", label_visibility="collapsed",
             format_func=lambda b: {core.BENCH_B1: "B1 Static 1/n (same assets)",
                                    core.BENCH_B2: "B2 Classic 60/40"}[b],
             help="B1 holds the same assets in equal weights, rebalanced monthly, so it isolates what the trend "
                  "filter adds. B2 is the 60% equity / 40% bond mix the client could buy instead.")

    with st.expander("Data source"):
        st.radio("Data", ["live", "snapshot"], key="data_pref", label_visibility="collapsed",
                 format_func=lambda s: "Live: Yahoo Finance, FRED, ECB" if s == "live" else "Stored snapshot (offline)")
        st.caption("Live data are cached for 6 hours. The snapshot only steps in if Yahoo blocks the server.")

    st.button("Reset to prospectus defaults", on_click=reset_defaults, width="stretch")

ui = {k: st.session_state[k] for k in core.DEFAULTS if k not in ("start", "end")}
ui["start"], ui["end"] = st.session_state["period"]
ui["tickers"] = tuple(t for t in core.ASSET_NAMES if t in (st.session_state["tickers"] or []))
is_default = all(ui[k] == core.DEFAULTS[k] for k in core.DEFAULTS)

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
        st.badge("Defaults = prospectus", icon=":material/verified:", color="green")
    else:
        st.badge("Custom assumptions: numbers differ from the prospectus", icon=":material/tune:", color="orange")
if data_warning:
    st.warning(data_warning, icon=":material/cloud_off:")

if len(ui["tickers"]) < 2:
    st.warning("Select at least two assets in the sidebar.")
    st.stop()
if (pd.Period(ui["end"], "M") - pd.Period(ui["start"], "M")).n < 23:
    st.warning("Choose a backtest period of at least 24 months.")
    st.stop()

try:
    res = run_cached(tuple(sorted(ui.items())), st.session_state["data_pref"],
                     f"{data['origin']}|{data['retrieved_at']}", ENGINE_SHA)
except ValueError as e:
    msg = f"The backtest cannot run with these settings: {e}"
    if "Not enough history" in str(e):
        youngest = max(data["prices_usd"][t].first_valid_index() for t in ui["tickers"])
        earliest = youngest + pd.offsets.MonthEnd(int(ui["sma_months"]) - 1 + int(ui["signal_lag"]))
        msg = (f"With a {ui['sma_months']}-month average and a {ui['signal_lag']}-month delay, the youngest selected "
               f"fund needs history until {earliest:%b %Y} before the first decision. Move the start of the backtest "
               f"period to {earliest:%Y-%m} or later, or shorten the window.")
    st.error(msg, icon=":material/history:")
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

st.markdown(
    f"**10,000 {ccy}** invested at the end of {first - pd.offsets.MonthEnd(1):%b %Y} would have grown to "
    f"**{10000 * w_s.iloc[-1]:,.0f} {ccy}** by {last:%b %Y} ({bn}: {10000 * w_b.iloc[-1]:,.0f} {ccy}). "
    f"Largest fall from a previous high: **{-M.loc['max_drawdown', S]:.1%}** ({bn}: {-M.loc['max_drawdown', P]:.1%})."
)


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
t_perf, t_table, t_hold, t_cost, t_method = st.tabs(["Performance", "All metrics", "Holdings", "Costs", "Method"])

with t_perf:
    c1, c2 = st.columns(2)
    log = c1.toggle("Log scale", value=False, help="Equal distances on the axis = equal percentage changes.")
    show_gross = c2.toggle("Show strategy before costs", value=False)
    wealth = {LBL_S: w_s}
    if show_gross:
        wealth[LBL_G] = core.wealth(res.strat_gross)
    for b in (core.BENCH_B1, core.BENCH_B2):
        wealth[b] = core.wealth(res.bench_net[b])
    st.markdown(f"##### Growth of 1 {ccy}, net of costs")
    st.caption("Past performance does not predict future returns. Hypothetical back-tested results, not the "
               "performance of a real fund.")
    st.plotly_chart(charts.cumulative(wealth, styles, pal, log=log), width="stretch", config={"displayModeBar": False})
    st.markdown("##### Drawdown: fall from the previous high")
    dd = {LBL_S: core.drawdown(res.strat_net)}
    dd.update({b: core.drawdown(res.bench_net[b]) for b in (core.BENCH_B1, core.BENCH_B2)})
    st.plotly_chart(charts.drawdowns(dd, styles, pal), width="stretch", config={"displayModeBar": False})
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
with t_table:
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

with t_hold:
    cash = res.held[core.CASH]
    st.markdown(f"##### On average {1 - cash.mean():.0%} invested and {cash.mean():.0%} in cash")
    st.plotly_chart(charts.weights_area(res.held, core.ASSET_NAMES, pal), width="stretch",
                    config={"displayModeBar": False})
    st.caption("Weights held during each month, after trading at its start. A slice moves fully to cash when its fund "
               "closes a month below its moving average, and back when it recovers.")

with t_cost:
    tv = res.turnover
    k1, k2, k3 = st.columns(3)
    k1.metric("Turnover p.a. (one-way)", pct(tv["turnover_pa"], 0),
              help="Half of the value bought plus sold in a year, as a share of the portfolio (the usual fund "
                   "definition).")
    k2.metric("Cost drag p.a.", pct(tv["cost_drag_pa"], 2), help="Growth rate lost to trading costs per year.")
    be = res.breakeven_bps
    if be is None:
        be_txt, be_help = "none", "Even at zero cost the strategy grows more slowly than the benchmark in this setting."
    elif math.isinf(be):
        be_txt, be_help = "> 2000 bps", "Stays ahead of the benchmark at any realistic cost."
    else:
        be_txt, be_help = f"{be:.0f} bps", ("One-way cost at which the strategy's growth rate falls to the "
                                            "benchmark's (both pay the same cost).")
    k3.metric(f"Breakeven cost vs {bn}", be_txt, help=be_help)
    st.markdown("##### Growth rate at different trading costs")
    grid = res.cost_grid[["Strategy", P]].rename(columns={"Strategy": "strategy", P: "benchmark"})
    be_plot = be if (be is not None and not math.isinf(be) and be <= 100) else None
    st.plotly_chart(charts.cost_curve(grid, ui["cost_bps"], be_plot, (LBL_S, P), pal), width="stretch",
                    config={"displayModeBar": False})
    st.caption("The return edge over the same assets held statically is thin and cost-sensitive; the risk edge "
               "(volatility, drawdown) holds at every cost level shown.")

with t_method:
    cfg = res.cfg
    st.markdown(f"""
**Data.** Daily adjusted closes (splits and dividends reinvested) from Yahoo Finance for SPY, EFA, IEF, VNQ and DBC,
reduced to the last close of each month. Risk-free rates and FX as downloaded for this run: USD rate
{data['sources']['rf_USD']}; EUR rate {data['sources']['rf_EUR']}; EUR/USD {data['sources']['fx']}.
US-listed funds stand in for the UCITS funds an EU investor would buy, because their history is longer.

**Rule.** At each month-end an asset is "in" if its USD price is above its simple moving average of the last
{cfg['sma_months']} month-end prices (including the current one). Holdings decided at the close of month t are held
during month t+{cfg['signal_lag']}, so every decision uses only information available at the time. Each asset has a
target of 1/n; a slice that is "out" earns the risk-free rate. Holdings drift between rebalancing dates
({REBAL[cfg['rebalance']].lower()}); a signal switch always triggers a trade.

**Benchmarks.** B1 = the same assets in static equal weights, rebalanced monthly (what the trend filter adds).
B2 = 60% equity (SPY 36%, EFA 24%) and 40% IEF, rebalanced monthly (what the client would otherwise buy).
Both pay the same trading cost on their trades.

**Costs.** {cfg['cost_bps']:.0f} bps one-way on the value of every fund trade, deducted in the month of the trade.

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
st.markdown(f"<div class='src'>Nova SBE · 2270 Financial Modeling · Group BP: {GROUP}. Educational project, not "
            f"investment advice. Data: {dl.describe(data)}.</div>", unsafe_allow_html=True)
