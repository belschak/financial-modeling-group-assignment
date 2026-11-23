"""BP Trend-Guarded Multi-Asset: interactive backtest (Nova SBE 2270 Financial Modeling, Group BP).

Run locally:  streamlit run app.py
Every number comes from fm_lean.py, the same module the submitted notebook writes and runs.
"""
from __future__ import annotations

import math
import subprocess
import time
from contextlib import contextmanager

import pandas as pd
import streamlit as st

import charts
import core
import data_layer as dl
import fm_lean as fl

REPO_URL = "https://github.com/belschak/financial-modeling-group-assignment"
GROUP = ("Tim Fischer, David Konrad Belschak, Tom Nico H Croe, Lennart Schmülling, Fridolin Treibig, "
         "Bastian Volkery")
DISCLAIMER = "Hypothetical back-tested results. Past performance does not predict future returns."
COST_STEPS = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
LIVE_RETRY_AFTER_S = 600  # after a failed live download, use the snapshot for 10 minutes before trying again

st.set_page_config(page_title="BP Trend-Guarded Multi-Asset | Backtest", page_icon="📈", layout="wide")
# Light theme on a viewer's first visit; the menu switch (System / Light / Dark) keeps working and wins once used.
# Streamlit has no config option for this and stores "System" on its first load, so once per browser (own marker
# key) we set its theme choice (localStorage key from Streamlit 1.67 storageUtils.ts) to Light. Any later choice
# in the menu is never touched. If the key ever changes, the app simply follows the system setting.
st.html(
    """<script>
    (function () {
      try {
        var ls = window.localStorage, mark = "bp-theme-default-v1";
        if (ls.getItem(mark) !== null) return;
        ls.setItem(mark, "1");
        var key = "stActiveTheme-" + window.location.pathname + "-v2";
        var cur = ls.getItem(key);
        if (cur === null || cur === JSON.stringify("System")) {
          ls.setItem(key, JSON.stringify("Light"));
          if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
            window.location.reload();
          }
        }
      } catch (e) { /* storage blocked: keep the system theme */ }
    })();
    </script>""",
    unsafe_allow_javascript=True,
)
st.markdown(
    """
    <style>
      [data-testid="stElementContainer"]:has(> [data-testid="stHtml"] script) { display: none; }
      [data-testid="stMetricValue"], [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
      [data-testid="stMetric"] { border: 1px solid rgba(128,138,155,.28); border-radius: .4rem; padding: .7rem .9rem .5rem; }
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


@st.cache_data(ttl="5m", show_spinner=False)
def _commit() -> str:
    """Short git commit of the running code (Streamlit Cloud deploys a git checkout and hot-reloads pushes)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=str(dl.DATA_DIR.parent))
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------- state
def _defaults():
    return {k: (list(v) if k == "tickers" else v) for k, v in core.DEFAULTS.items() if k not in ("start", "end")}


for k, v in _defaults().items():
    st.session_state.setdefault(k, v)
st.session_state.setdefault("data_pref", "live")
st.session_state.setdefault("period_rev", 0)   # bumped by Reset: gives the period slider a fresh identity


def reset_defaults():
    st.session_state.update(_defaults())
    st.session_state.pop(f"period_{st.session_state['period_rev']}", None)
    st.session_state["period_rev"] += 1


# ---------------------------------------------------------------- data + runs (cached)
@st.cache_data(ttl="12h", show_spinner="Downloading prices (Yahoo Finance) and rates (ECB, FRED)...")
def live_data(sha: str) -> dict:
    return dl.load_live()  # raises on failure; failures are never cached


@st.cache_data(show_spinner=False)
def snapshot_data(file_stamp: float) -> dict:
    return dl.load_snapshot()


@st.cache_resource(show_spinner=False)
def _live_failure() -> dict:
    """Server-wide memory of the last failed download, so a throttled server is not retried on every click."""
    return {}


def get_data(pref: str) -> tuple[dict, str | None]:
    """(data, warning). Called once per page run; everything below uses exactly this data."""
    snap_ok = dl.snapshot_available()
    if pref == "snapshot":
        if not snap_ok:
            raise RuntimeError("The stored data snapshot is not part of this deployment. Choose live data.")
        return snapshot_data(dl.SNAP_CSV.stat().st_mtime), None
    fail = _live_failure()
    if not (fail.get("t") and time.time() - fail["t"] < LIVE_RETRY_AFTER_S):
        try:
            data = live_data(core.SHA)
            fail.clear()
            return data, None
        except Exception as e:  # noqa: BLE001
            fail.update(t=time.time(), err=type(e).__name__)
    if snap_ok:
        snap = snapshot_data(dl.SNAP_CSV.stat().st_mtime)
        return snap, (f"Live data unavailable, showing snapshot as of {snap['retrieved_at']}. "
                      f"({fail.get('err', 'download error')}: Yahoo Finance sometimes throttles shared cloud servers; "
                      "same sources and same code. The app tries live data again after a few minutes.)")
    raise RuntimeError("Market data could not be downloaded right now.")


# `_data` is not hashed; `stamp` identifies it in the cache key, so a result always belongs to the data shown.
@st.cache_data(show_spinner="Running the backtest...", max_entries=128)
def run_cached(ui_items: tuple, stamp: str, sha: str, _data: dict) -> dict:
    return core.run(dict(ui_items), _data)


@st.cache_data(show_spinner="Simulating 10,000 ten-year paths...", max_entries=32)
def mc_cached(ui_items: tuple, stamp: str, sha: str, haircut: bool, _data: dict) -> dict:
    return core.monte_carlo(run_cached(ui_items, stamp, sha, _data), haircut)


@st.cache_data(show_spinner=False, max_entries=32)
def costs_cached(ui_items: tuple, stamp: str, sha: str, _data: dict) -> dict:
    return core.costs(run_cached(ui_items, stamp, sha, _data), dict(ui_items)["bench"])


try:
    data, data_warning = get_data(st.session_state["data_pref"])
except Exception as e:  # noqa: BLE001
    st.error(f"{e} Please reload in a few minutes.", icon=":material/cloud_off:")
    st.stop()
last_month = dl.last_complete_month(data)
months = pd.period_range("2007-01", last_month.strftime("%Y-%m"), freq="M").strftime("%Y-%m").tolist()

# ---------------------------------------------------------------- sidebar: assumptions
with st.sidebar:
    st.markdown("### Your assumptions")
    st.caption("Change any input and every number recalculates. The defaults reproduce prospectus Table 1.")
    st.markdown("**Trend rule**")
    st.slider("Moving-average window (months)", 6, 12, key="sma",
              help="An asset is held only while its month-end price is above its average over this many months. "
                   "10 comes from Faber (2007); we did not optimise it.")
    st.radio("Signal delay (months)", [1, 2], key="lag", horizontal=True,
             help="1: the signal from the close of month t sets the holdings for month t+1. 2: act one month later.")
    st.radio("Trade at", [False, True], key="next_day",
             format_func=lambda x: "next trading day's close (realistic)" if x else "month-end close (prospectus)",
             help="The signal always uses the month-end close. Trading at that same close is Faber's standard; "
                  "the next trading day's close is what an investor can really do.")
    st.markdown("**Costs**")
    st.select_slider("Trading cost (bps per trade, one-way)", options=COST_STEPS, key="cost_bps",
                     help="Charged on every euro of ETF bought or sold (1 bp = 0.01%). 10 bps = fund level (base case), "
                          "50 bps = the lecture's all-in retail figure. Benchmarks pay the same cost on their trades.")
    # value= makes it a RANGE slider; the key changes on Reset, so the browser shows the default range again.
    PKEY = f"period_{st.session_state['period_rev']}"
    if PKEY in st.session_state and any(m not in months for m in st.session_state[PKEY]):
        del st.session_state[PKEY]
    st.select_slider("Backtest period", options=months, key=PKEY,
                     value=st.session_state.get(PKEY, (core.DEFAULTS["start"], min(core.DEFAULTS["end"], months[-1]))),
                     help="Earliest start is Jan 2007: the commodity fund (DBC) starts in Feb 2006 and the rule needs "
                          "a full moving-average window first.")
    st.markdown("**Assets in the portfolio**")
    st.pills("Assets", fl.TICKERS, selection_mode="multi", key="tickers", label_visibility="collapsed",
             format_func=lambda t: f"{t} · {core.NAMES[t]}",
             help="Each selected asset gets an equal slice (1/n). Benchmark B1 holds the same assets.")
    st.markdown("**Benchmark for alpha, beta and IR**")
    st.radio("Benchmark", list(core.BENCH), key="bench", label_visibility="collapsed",
             format_func=lambda b: core.BENCH[b] + (" (same assets)" if b == "B1" else ""),
             help="B1 holds the same assets in equal weights, so it isolates what the trend filter adds. "
                  "B2 is the 60% equity / 40% bond mix the client could buy instead.")
    with st.expander("Data source"):
        st.radio("Data", ["live", "snapshot"], key="data_pref", label_visibility="collapsed",
                 format_func=lambda s: "Live: Yahoo Finance, ECB, FRED" if s == "live" else "Stored snapshot (offline)")
        st.caption("Live data are cached for 12 hours. The snapshot only steps in if Yahoo throttles the server.")
    st.button("Reset to prospectus defaults", on_click=reset_defaults, width="stretch")

ui = {k: st.session_state[k] for k in core.DEFAULTS if k not in ("start", "end")}
ui["start"], ui["end"] = st.session_state[PKEY]
ui["tickers"] = tuple(t for t in fl.TICKERS if t in (st.session_state["tickers"] or []))
notes = []
if len(ui["tickers"]) >= 2:
    first_ok = core.earliest_start(data, ui["tickers"], ui["sma"], ui["lag"])
    if core.month_end(ui["start"]) < first_ok:
        notes.append(f"Start moved to {first_ok:%b %Y}: with a {ui['sma']}-month average and a {ui['lag']}-month "
                     "delay, the youngest fund needs that much history first.")
        ui["start"] = first_ok.strftime("%Y-%m")
if ui["next_day"] and core.month_end(ui["end"]) > dl.last_complete_month(data, next_day=True):
    ui["end"] = dl.last_complete_month(data, next_day=True).strftime("%Y-%m")
    notes.append(f"End moved to {core.month_end(ui['end']):%b %Y}: next-day trading needs the first day of the next month.")
is_default = all(ui[k] == core.DEFAULTS[k] for k in core.DEFAULTS)

# ---------------------------------------------------------------- header
st.title(core.STRATEGY)
st.markdown(
    "<p class='lede'>Five broad asset classes, an equal slice each. At every month-end an asset stays in the "
    f"portfolio only while its price is above its {ui['sma']}-month average; otherwise its slice waits in euro cash. "
    "Designed for cautious euro-area savers about 10 years from retirement.</p>", unsafe_allow_html=True)
h1, h2 = st.columns([1, 1], vertical_alignment="center")
with h1:
    if is_default:
        st.badge("Defaults: matches prospectus Table 1", icon=":material/verified:", color="green")
    else:
        st.badge("Custom assumptions: differs from prospectus", icon=":material/tune:", color="orange")
if data_warning:
    st.warning(data_warning, icon=":material/cloud_off:")
for n in notes:
    st.info(n, icon=":material/history:")
if len(ui["tickers"]) < 2:
    st.warning("Select at least two assets in the sidebar.")
    st.stop()
if (pd.Period(ui["end"], "M") - pd.Period(ui["start"], "M")).n < 23:
    st.warning("Choose a backtest period of at least 24 months.")
    st.stop()

UI_ITEMS = tuple(sorted(ui.items()))
STAMP = f"{data['origin']}|{data['retrieved_at']}"
ARGS = (UI_ITEMS, STAMP, core.SHA)
try:
    bt = run_cached(*ARGS, data)
except Exception as e:  # noqa: BLE001  (never show a traceback)
    st.error(f"The backtest cannot run with these settings ({e}). Try other settings or press Reset.",
             icon=":material/error:")
    st.stop()

T, net = bt["table"], bt["net"]
B = ui["bench"]
BL = core.BENCH[B]
pal = charts.PALETTE
LBL_S, LBL_G = "Strategy (net)", "Strategy before costs"
styles = {LBL_S: dict(color=pal["strategy"], width=2.6), LBL_G: dict(color=pal["strategy"], width=1.2, dash="dot"),
          core.BENCH["B1"]: dict(color=pal["b1"], width=2), core.BENCH["B2"]: dict(color=pal["b2"], width=2, dash="dash")}
first, last = net.index[0], net.index[-1]
with h2:
    st.markdown(f"<div class='src meta'>{first:%b %Y} to {last:%b %Y} · {len(net)} months · EUR · net of "
                f"{ui['cost_bps']} bps trading costs</div>", unsafe_allow_html=True)


def pct(x, d=1):
    if x is None or pd.isna(x):
        return "n/a"
    return f"{0.0 if abs(x) < 0.5 * 10 ** -(d + 2) else x:.{d}%}"  # no "-0.0%"


def num(x, d=2):
    if x is None or pd.isna(x):
        return "n/a"
    return f"{0.0 if abs(x) < 0.5 * 10 ** -d else x:.{d}f}"


S = T.loc["Strategy"]
st.markdown(
    f"**10,000 EUR** invested at the end of {first - pd.offsets.MonthEnd(1):%b %Y} would have grown to "
    f"**{10000 * S['final_wealth']:,.0f} EUR** by {last:%b %Y} ({B}: {10000 * T.loc[B, 'final_wealth']:,.0f} EUR). "
    f"Largest fall from a previous high: **{-S['max_drawdown']:.1%}** ({B}: {-T.loc[B, 'max_drawdown']:.1%}); "
    f"the client's target is a worst fall of at most {core.CLIENT_DD_TARGET:.0%}, with {core.CLIENT_DD_CEILING:.0%} as the "
    f"hard ceiling.")
if not ui["next_day"]:
    nd = run_cached(tuple(sorted({**ui, "next_day": True, "end": min(ui["end"], dl.last_complete_month(
        data, next_day=True).strftime("%Y-%m"))}.items())), STAMP, core.SHA, data)["table"].loc["Strategy"]
    st.markdown(f"<div class='src'>Traded at the next trading day's close instead (realistic): Sharpe ratio "
                f"{num(nd['sharpe'])}, largest fall {-nd['max_drawdown']:.1%}.</div>", unsafe_allow_html=True)
st.caption(DISCLAIMER)

HELP = {
    "ann_return": "Average monthly return x 12 (arithmetic, as the brief asks). The growth rate actually earned "
                  "(CAGR) is in the full table.",
    "ann_vol": "How much returns swing: standard deviation of monthly returns x sqrt(12).",
    "sharpe": "Return above the euro cash rate per unit of risk: mean monthly excess return / its standard deviation, "
              "x sqrt(12).",
    "alpha_ann": "Return beyond what the exposure to the benchmark explains (Jensen's alpha, OLS on monthly excess "
                 "returns), x 12. The t-statistic tells whether it is distinguishable from luck (roughly |t| > 2).",
    "ir": "Regression form (class definition, W3): alpha / volatility of the regression residuals, x sqrt(12). "
          "The tracking-error form is in the line below the cards.",
    "beta": "Sensitivity to the benchmark: covariance / variance of monthly excess returns. Not annualised.",
}

# ---------------------------------------------------------------- the six required measures
d_ret, d_vol, d_sh = (S[k] - T.loc[B, k] for k in ("ann_return", "ann_vol", "sharpe"))
c = st.columns(3) + st.columns(3)
c[0].metric("Average return p.a.", pct(S["ann_return"]), f"{d_ret * 100:+.1f} pp vs {B}", help=HELP["ann_return"])
c[1].metric("Volatility p.a.", pct(S["ann_vol"]), f"{d_vol * 100:+.1f} pp vs {B}", delta_color="inverse",
            help=HELP["ann_vol"])
c[2].metric("Sharpe ratio", num(S["sharpe"]), f"{d_sh:+.2f} vs {B}", help=HELP["sharpe"])
c[3].metric(f"Alpha p.a. vs {B}", pct(S["alpha_ann"]), f"t = {num(S['alpha_t'])}", delta_color="off",
            delta_arrow="off", help=HELP["alpha_ann"])
c[4].metric("Information ratio (regression)", num(S["information_ratio_regression"]), help=HELP["ir"])
c[5].metric(f"Beta vs {B}", num(S["beta"]), help=HELP["beta"])


def ir_reg_line(x):
    if x is None or pd.isna(x):
        return "not available for these settings"
    return ("high: a large alpha relative to the risk the benchmark does not explain" if x >= 0.5 else
            "positive but modest risk-adjusted alpha" if x > 0 else "no positive risk-adjusted alpha")


def ir_te_line(x):
    if x is None or pd.isna(x):
        return "not available for these settings"
    if abs(x) < 0.1:
        return f"the strategy's return is about the same as {B}'s"
    return (f"the strategy's return {'beats' if x > 0 else 'trails'} {B}'s"
            + (" consistently" if abs(x) >= 0.5 else " only slightly, relative to how far it deviates"))


st.markdown(
    f"<div class='src'>Information ratio in both forms. Regression (alpha / residual volatility, the class "
    f"definition): <b>{num(S['information_ratio_regression'])}</b>, {ir_reg_line(S['information_ratio_regression'])}. "
    f"Tracking error (return above {B} / volatility of that difference): <b>{num(S['information_ratio'])}</b>, "
    f"{ir_te_line(S['information_ratio'])}.</div>", unsafe_allow_html=True)


@contextmanager
def guard(view: str):
    """A failing view shows a short notice instead of a traceback; the other tabs keep working."""
    try:
        yield
    except Exception as e:  # noqa: BLE001
        st.info(f"{view} cannot be shown with these settings ({e}).", icon=":material/info:")


t_perf, t_table, t_hold, t_cost, t_mc, t_method = st.tabs(
    ["Performance", "All metrics", "Holdings", "Costs", "10-year outlook", "Method"])

with t_perf, guard("This view"):
    c1, c2 = st.columns(2)
    log = c1.toggle("Log scale", value=False, help="Equal distances on the axis = equal percentage changes.")
    show_gross = c2.toggle("Show strategy before costs", value=False)
    w = {LBL_S: fl.wealth(net["Strategy"])}
    if show_gross:
        w[LBL_G] = fl.wealth(net["Strategy gross"])
    w.update({core.BENCH[b]: fl.wealth(net[b]) for b in ("B1", "B2")})
    st.markdown("##### Growth of 1 EUR, net of costs")
    st.caption(DISCLAIMER + " The fund did not exist over this period.")
    st.plotly_chart(charts.cumulative(w, styles, pal, log=log), width="stretch", config={"displayModeBar": False})
    st.markdown("##### Drawdown: fall from the previous high")
    dd = {LBL_S: fl.drawdown(net["Strategy"]), **{core.BENCH[b]: fl.drawdown(net[b]) for b in ("B1", "B2")}}
    st.plotly_chart(charts.drawdowns(dd, styles, pal), width="stretch", config={"displayModeBar": False})
    if len(net) > 36:
        st.markdown("##### Is the edge stable over time?")
        st.plotly_chart(charts.rolling_lines(fl.rolling(net["Strategy"], net[B], bt["rf"]), pal, B), width="stretch",
                        config={"displayModeBar": False})
    years = fl.calendar_years(net)
    years = years.loc[[y for y in years.index if (net.index.year == y).sum() == 12]]
    st.markdown(f"##### Calendar-year returns: strategy vs {B}")
    st.caption(DISCLAIMER)
    st.plotly_chart(charts.annual_bars(years, ["Strategy", B], [LBL_S, BL],
                                       [pal["strategy"], pal["b1"] if B == "B1" else pal["b2"]], pal),
                    width="stretch", config={"displayModeBar": False})
    st.markdown("<div class='src'>Source: Yahoo Finance (adjusted close, dividends reinvested), ECB, FRED; group "
                "calculations. All series start at exactly 1.00 on the same date.</div>", unsafe_allow_html=True)

ROWS = [
    ("ann_return", "Average return p.a.", pct, True),
    ("ann_vol", "Volatility p.a.", pct, True),
    ("sharpe", "Sharpe ratio", num, True),
    ("alpha_ann", f"Alpha p.a. (vs {B})", pct, True),
    ("information_ratio_regression", f"Information ratio, regression (alpha / residual volatility, vs {B})", num, True),
    ("information_ratio", f"Information ratio, tracking error (vs {B})", num, True),
    ("beta", f"Beta (vs {B}, not annualised)", num, True),
    ("alpha_t", "Alpha t-statistic", num, False),
    ("cagr", "Growth rate p.a. (CAGR)", pct, False),
    ("max_drawdown", "Maximum drawdown", pct, False),
    ("months_trough_to_recovery", "Months from bottom back to the old high",
     lambda x: "not yet" if x is None or pd.isna(x) else f"{x:.0f}", False),
    ("worst_12m", "Worst 12 months", pct, False),
    ("tracking_error", f"Tracking error p.a. (vs {B})", pct, False),
]
with t_table, guard("The metrics table"):
    st.caption(DISCLAIMER)
    cols = {"Strategy": "Strategy (net)", "Strategy gross": "Before costs", "B1": "B1 Static 1/n", "B2": "B2 60/40"}
    table = pd.DataFrame({lbl: [f(T.loc[col, k]) for k, _, f, _ in ROWS] for col, lbl in cols.items()})
    table.insert(0, "Brief", ["Required" if req else "Extra" for *_, req in ROWS])
    table.insert(0, "Measure", [lbl for _, lbl, _, _ in ROWS])
    st.dataframe(table, width="stretch", hide_index=True, height=35 * (len(ROWS) + 1) + 3,
                 column_config={"Measure": st.column_config.TextColumn(width="medium", pinned=True),
                                "Brief": st.column_config.TextColumn(width="small")})
    st.caption(f"Monthly data, {first:%b %Y} to {last:%b %Y}, in EUR. Excess returns use the euro cash rate. "
               f"Relative measures are against {BL}; a benchmark against itself gives beta 1, alpha 0 (sanity check).")
    d1, d2 = st.columns(2)
    d1.download_button("Download monthly returns (CSV)", net.to_csv(), "bp_backtest_monthly_returns.csv", "text/csv",
                       width="stretch")
    d2.download_button("Download metrics (CSV)", T.to_csv(), "bp_backtest_metrics.csv", "text/csv", width="stretch")

with t_hold, guard("The holdings view"):
    held = bt["weights"].assign(CASH=1 - bt["weights"].sum(axis=1))
    st.caption(DISCLAIMER)
    st.markdown(f"##### On average {1 - held['CASH'].mean():.0%} invested and {held['CASH'].mean():.0%} in cash")
    st.plotly_chart(charts.weights_area(held, core.NAMES, pal), width="stretch", config={"displayModeBar": False})
    st.caption("Target weights at the start of each month. A slice moves fully to cash when its fund closes a month "
               "below its moving average, and back when it recovers.")

with t_cost, guard("The cost view"):
    st.caption(DISCLAIMER)
    cs = costs_cached(*ARGS, data)

    def be_fmt(v, what):
        if v is None:
            return "none", f"Even at zero cost the strategy's {what} is below the benchmark's."
        if math.isinf(v):
            return "> 2000 bps", f"The strategy's {what} stays above the benchmark's at any realistic cost."
        return f"{v:.0f} bps", f"One-way cost at which the strategy's {what} falls to the benchmark's (both pay it)."

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Turnover p.a. (one-way)", pct(cs["turnover_pa"], 0),
              help="Half of the value bought plus sold in a year, cash leg included.")
    k2.metric("Cost drag p.a.", pct(cs["cost_drag_pa"], 2), help="Growth rate lost to trading costs per year.")
    t3, h3 = be_fmt(cs["breakeven_cagr"], "growth rate (CAGR)")
    t4, h4 = be_fmt(cs["breakeven_sharpe"], "Sharpe ratio")
    k3.metric(f"Breakeven on return vs {B}", t3, help=h3)
    k4.metric(f"Breakeven on Sharpe vs {B}", t4, help=h4)
    st.markdown("##### Value of 1 EUR at the end of the sample, at different trading costs")
    be = cs["breakeven_cagr"]
    st.plotly_chart(charts.cost_curve(cs["grid"], ui["cost_bps"], be if be is not None and be <= 100 else None,
                                      (LBL_S, BL), pal, ytitle="Final value of 1 EUR invested", yfmt=".2f"),
                    width="stretch", config={"displayModeBar": False})
    st.caption(f"At {ui['cost_bps']} bps the strategy grows {'faster' if S['cagr'] > T.loc[B, 'cagr'] else 'more slowly'}"
               f" than {B} ({pct(S['cagr'])} vs {pct(T.loc[B, 'cagr'])} a year). "
               + (f"Risk-adjusted (Sharpe) it stays ahead up to {t4} per trade." if cs["breakeven_sharpe"]
                  else "Risk-adjusted (Sharpe) it is behind even before costs."))

with t_mc, guard("The 10-year outlook"):
    haircut = st.toggle("Cautious variant: halve the strategy's historical return above cash", value=False,
                        help="Published rules often work less well after publication (McLean and Pontiff 2016).")
    mc = mc_cached(*ARGS, haircut, data)
    B2L = core.BENCH["B2"]
    st.markdown(f"##### {mc['initial']:,.0f} EUR over the next {mc['months'] // 12} years: range of outcomes")
    st.caption(f"Each of {mc['n_sim']:,} paths draws {mc['months']} months at random from the back-tested history "
               "(the same months for both portfolios, fixed seed, as in Lecture 5.3). It is not a forecast: it assumes "
               "the past sample is representative and ignores taxes. The investment may lead to a financial loss. "
               + DISCLAIMER)
    st.plotly_chart(charts.fan_chart(mc["bands"], {"Strategy": LBL_S, B2L: B2L},
                                     {"Strategy": pal["strategy"], B2L: pal["b1"]}, pal, "p10", "p90", mc["initial"]),
                    width="stretch", config={"displayModeBar": False})
    st.dataframe(pd.DataFrame([{"Portfolio": lbl, "Unfavourable (10th pct.)": f"{sm['p10']:,.0f}",
                                "Median": f"{sm['p50']:,.0f}", "Favourable (90th pct.)": f"{sm['p90']:,.0f}",
                                "Chance of ending below start": pct(sm["prob_below_start"]),
                                "Chance of a fall > 20% on the way": pct(sm["prob_drawdown_over_20pct"])}
                               for name, lbl in (("Strategy", LBL_S), (B2L, B2L)) for sm in [mc["summary"][name]]]),
                 hide_index=True, width="stretch")
    st.caption(f"The strategy ends ahead of {B2L} in {mc['summary']['prob_first_beats_second']:.0%} of the paths. "
               "Bands: dark = middle 50% of paths, light = 10th to 90th percentile. Values in EUR, after the trading "
               "costs you chose.")

with t_method, guard("The method note"):
    st.markdown(f"""
**Data.** Daily adjusted closes (dividends reinvested) from Yahoo Finance for SPY, EFA, IEF, VNQ and DBC, taken on the
last trading day of each month; the euro cash rate from the ECB (EONIA to September 2019, then EUR STR); the US
overnight rate (EFFR) and EUR/USD (DEXUSEU) from FRED. US-listed funds stand in for the UCITS funds an EU investor would
buy, because their history is longer. USD returns are converted with r_EUR = (1 + r_USD) x S(t-1) / S(t) - 1
(S = USD per EUR); the bond slice (IEF) is EUR-hedged: r_USD + euro cash rate - EFFR.

**Rule.** At each month-end an asset is "in" if its USD price is above its simple moving average of the last
{ui['sma']} month-end prices. Holdings decided at the close of month t are held during month t+{ui['lag']}
(`signal.shift(lag)`), so every decision uses only information available at the time. Each asset has an equal
slice of 1/n, held either in its fund or in euro cash. With "next trading day's close" the trades (and the returns of
that month) use the first trading day of the following month instead of the month-end close.

**Benchmarks.** B1 = the same assets in static equal weights (what the trend filter adds). B2 = 60% equity (SPY 36%,
EFA 24%) and 40% IEF (what the client would otherwise buy). Both rebalance monthly and pay the same trading cost.

**Costs.** {ui['cost_bps']} bps one-way on every euro of ETF traded back to target each month (weights drift
within the month; the cash leg is free). Breakeven: the cost at which the strategy's CAGR, or its Sharpe ratio, falls
to the benchmark's, with both paying it.

**Measures.** Simple monthly returns. Average return = mean x 12; volatility = standard deviation x sqrt(12);
Sharpe = mean excess return / its standard deviation x sqrt(12); beta = cov / var of monthly excess returns,
**not annualised**; alpha = OLS intercept x 12, with its t-statistic; information ratio in two forms: regression =
alpha / standard deviation of the residuals x sqrt(12) (class definition), and tracking error = mean of (strategy
minus benchmark) / its standard deviation x sqrt(12). Growth curves are cumprod(1 + r) with a start value of 1.00.

**Same code as the notebook.** All numbers come from `fm_lean.py` version {fl.VERSION} (SHA-256
`{core.SHA[:16]}...`), the module the submitted notebook writes with `%%writefile` and runs. Tests in the repository
check that both files are byte-identical and that these defaults reproduce the notebook's results.

**Limitations.** A backtest is not a forecast. US-listed proxies; no taxes and no fund fees beyond those already in the
fund prices; the 10-month rule is famous, so part of its past success may not repeat (publication bias).
""")

# ---------------------------------------------------------------- footer
st.divider()
st.markdown(f"[Source code on GitHub]({REPO_URL}) · Backtest notebook: submitted with the prospectus")
origin = "live download" if data["origin"] == "live" else "stored snapshot"
st.markdown(f"<div class='src'>Data as of {data['retrieved_at']} ({origin}), latest complete month {last_month:%b %Y}; {dl.SOURCES}. Code version {_commit()}, "
            f"fm_lean {fl.VERSION} (SHA-256 {core.SHA[:12]}). Nova SBE · 2270 Financial Modeling · Group BP: {GROUP}. "
            f"Educational project, not investment advice. {DISCLAIMER}</div>", unsafe_allow_html=True)
