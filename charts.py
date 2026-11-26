"""Plotly figures in the prospectus colours (one palette that reads on light and dark)."""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

# One palette that reads on both the light and the dark theme (Streamlit's theme detection can lag a
# rerun behind a theme switch, so colours must not depend on it). Hues follow design-tokens.md; the navy
# is lifted one step so it keeps >= 3:1 contrast on the dark background too.
PALETTE = dict(muted="rgba(128,138,155,1)", strategy="#2E68A8", b1="#C08A2B", b2="#8A94A6", b3="#3F8A78",
               loss="#B4474A", ok="#2E8B62", grid="rgba(128,138,155,0.22)", paper="rgba(0,0,0,0)",
               assets=["#2E68A8", "#5B93C8", "#8DB6DA", "#3F8A78", "#C08A2B", "#D9B256"], cash="rgba(150,165,185,0.45)")
FONT = "Inter, -apple-system, Segoe UI, sans-serif"


def _layout(fig: go.Figure, p: dict, ytitle: str, height: int = 380, yfmt: str | None = None, log: bool = False):
    fig.update_layout(
        height=height, margin=dict(l=18, r=22, t=46, b=14),
        paper_bgcolor=p["paper"], plot_bgcolor=p["paper"],
        font=dict(family=FONT, size=12),
        hovermode="x unified",
        hoverlabel=dict(font=dict(family=FONT, size=12), bordercolor=p["grid"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)",
                    entrywidth=168, entrywidthmode="pixels", font=dict(size=12), itemwidth=40),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=p["grid"], linewidth=1, ticks="outside",
                     tickcolor=p["grid"], ticklen=4, tickfont=dict(color=p["muted"], size=11))
    fig.update_yaxes(title=dict(text=ytitle, font=dict(color=p["muted"], size=11), standoff=8), showgrid=True,
                     gridcolor=p["grid"], griddash="dot", zeroline=False, tickformat=yfmt,
                     tickfont=dict(color=p["muted"], size=11), type="log" if log else "linear")
    return fig


def cumulative(wealth: dict[str, pd.Series], styles: dict[str, dict], p: dict, log: bool = False) -> go.Figure:
    fig = go.Figure()
    for name, w in wealth.items():
        st = styles[name]
        fig.add_trace(go.Scatter(x=w.index, y=w.values, name=name, mode="lines",
                                 line=dict(color=st["color"], width=st.get("width", 2), dash=st.get("dash")),
                                 hovertemplate="%{y:.2f}"))
    # Factsheet-style end labels: each series' last value in its own colour, right of the line, nudged apart so
    # close values do not overlap (positions in axis units; a log axis takes log10 coordinates).
    tf = (lambda v: math.log10(v)) if log else (lambda v: v)
    lo = min(tf(w.min()) for w in wealth.values())
    hi = max(tf(w.max()) for w in wealth.values())
    gap = 0.06 * (hi - lo or 1)
    ends = sorted(((tf(w.iloc[-1]), w.iloc[-1], styles[n]["color"], w.index[-1]) for n, w in wealth.items()),
                  reverse=True)
    prev = None
    for y, v, col, x in ends:
        y = y if prev is None else min(y, prev - gap)
        prev = y
        fig.add_annotation(x=x, y=y, text=f"<b>{v:.2f}</b>", showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=col, size=11))
    fig.add_hline(y=1.0, line=dict(color=p["muted"], width=1, dash="dot"))
    fig = _layout(fig, p, "Growth of 1 (start = 1.00)", log=log)
    fig.update_layout(margin=dict(r=58))
    if log:   # labelled ticks only (as in the notebook's F1), no unlabelled minor ticks such as "7 8 9 1 2"
        vals = [v for v in (0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16) if 10 ** lo / 1.1 <= v <= 10 ** hi * 1.1]
        fig.update_yaxes(tickvals=vals, ticktext=[f"{v:g}" for v in vals], minor=dict(showgrid=False))
    return fig


def drawdowns(dd: dict[str, pd.Series], styles: dict[str, dict], p: dict, target: float, ceiling: float,
              bands: list | None = None) -> go.Figure:
    """Fall from the previous high of every portfolio (notebook F2): the strategy filled, the client's target and
    ceiling as lines, the notebook's crisis windows shaded."""
    fig = go.Figure()
    for a, b, lbl in bands or []:
        fig.add_vrect(x0=a, x1=b, fillcolor="rgba(192,138,43,0.09)", line_width=0, layer="below",
                      annotation_text=lbl, annotation_position="top left", annotation_font=dict(size=10, color=p["b1"]))
    first = next(iter(dd))
    for name, s in reversed(list(dd.items())):
        st = styles[name]
        is_s = name == first
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                                 line=dict(color=st["color"], width=2.4 if is_s else 1.4, dash=st.get("dash")),
                                 fill="tozeroy" if is_s else None, fillcolor=_rgba(st["color"], 0.16) if is_s else None,
                                 hovertemplate="%{y:.1%}"))
    for lvl, txt, col, dash in ((target, "client target", p["ok"], "dash"), (ceiling, "ceiling", p["loss"], "solid")):
        fig.add_hline(y=-lvl, line=dict(color=col, width=1, dash=dash), annotation_text=f"{txt} -{lvl:.0%}",
                      annotation_position="bottom right", annotation_font=dict(size=10, color=col))
    fig = _layout(fig, p, "Fall from previous high", height=400, yfmt=".0%")
    fig.update_layout(legend=dict(traceorder="reversed"), margin=dict(t=64))
    return fig


def weights_area(w: pd.DataFrame, names: dict[str, str], p: dict) -> go.Figure:
    fig = go.Figure()
    cols = [c for c in w.columns if c != "CASH"]
    for i, c in enumerate(cols):
        col = p["assets"][i % len(p["assets"])]
        fig.add_trace(go.Scatter(x=w.index, y=w[c], name=f"{c} · {names.get(c, c).split(' (')[0]}", stackgroup="one",
                                 mode="lines", line=dict(width=0, color=col, shape="hv"), fillcolor=col,
                                 hovertemplate="%{y:.0%}"))
    fig.add_trace(go.Scatter(x=w.index, y=w["CASH"], name="Cash", stackgroup="one", mode="lines",
                             line=dict(width=0, color=p["cash"], shape="hv"), fillcolor=p["cash"],
                             hovertemplate="%{y:.0%}"))
    fig = _layout(fig, p, "Share of portfolio held during the month", height=340, yfmt=".0%")
    fig.update_layout(legend=dict(traceorder="normal", entrywidth=190))
    fig.update_yaxes(range=[0, 1.0001], showgrid=False)
    return fig


def cost_curve(grid: pd.DataFrame, chosen: float, breakevens: dict, styles: dict[str, dict], labels: dict[str, str],
               p: dict, ytitle: str = "Final value of 1 EUR invested", yfmt: str = ".2f") -> go.Figure:
    """Notebook F5 extended to 100 bps: the final value of 1 EUR for every portfolio when all pay the same cost
    per trade (B3 is one fund and never trades, so its line is flat)."""
    fig = go.Figure()
    for k in reversed(list(grid.columns)):
        st = styles[labels[k]]
        fig.add_trace(go.Scatter(x=grid.index, y=grid[k], name=labels[k], mode="lines",
                                 line=dict(color=st["color"], width=2.6 if k == "Strategy" else 1.6, dash=st.get("dash")),
                                 hovertemplate="%{y:" + yfmt + "}"))
    fig.add_vline(x=chosen, line=dict(color=p["muted"], width=1, dash="dot"),
                  annotation_text="your setting", annotation_position="top left", annotation_font_color=p["muted"])
    for b, be in breakevens.items():   # cost at which the strategy's CAGR falls to that benchmark's (F5)
        if be is not None and be <= grid.index.max():
            col = styles[labels[b]]["color"]
            fig.add_vline(x=be, line=dict(color=col, width=1.2, dash="dash"),
                          annotation_text=f"breakeven vs {b}: {be:.0f} bps", annotation_position="bottom right",
                          annotation_font_color=col)
    fig = _layout(fig, p, ytitle, height=380, yfmt=yfmt)
    fig.update_layout(legend=dict(traceorder="reversed"), margin=dict(t=64))
    fig.update_xaxes(title=dict(text="One-way trading cost (basis points)", font=dict(color=p["muted"], size=12)))
    return fig


def annual_heatmap(annual: pd.DataFrame, labels: list[str], p: dict) -> go.Figure:
    """Calendar-year returns of every portfolio as a grid of colours: one row per year, one column per portfolio,
    green for gains and red for losses, the value in each cell (reads on a phone as well as on a desk)."""
    z = annual.to_numpy()
    lim = max(0.05, float(abs(z).max()))
    txt = [[f"{0.0 if abs(v) < 0.0005 else v:+.1%}" for v in row] for row in z]
    scale = [[0, "rgba(192,67,74,0.80)"], [0.5, "rgba(128,138,155,0.07)"], [1, "rgba(46,139,98,0.80)"]]
    fig = go.Figure(go.Heatmap(z=z, x=labels, y=[str(y) for y in annual.index], zmin=-lim, zmax=lim, colorscale=scale,
                               text=txt, texttemplate="%{text}", textfont=dict(size=12), showscale=False, xgap=3, ygap=3,
                               hovertemplate="%{y}, %{x}: %{text}<extra></extra>"))
    fig = _layout(fig, p, "", height=60 + 28 * len(annual))
    fig.update_layout(hovermode="closest", margin=dict(l=8, r=8, t=34, b=8))
    fig.update_xaxes(side="top", showline=False, ticks="", tickfont=dict(size=12, color=p["muted"]))
    fig.update_yaxes(autorange="reversed", showgrid=False, ticks="", type="category")
    return fig


def fan_chart(bands: dict, labels: dict, colors: dict, p: dict, lo: str, hi: str, initial: float) -> go.Figure:
    """Monte Carlo outcome ranges over time: outer band lo-hi, inner band p25-p75, median line."""
    fig = go.Figure()
    for name, b in bands.items():
        col = colors[name]
        x = b.index / 12.0
        rgba = _rgba(col, 0.13)
        rgba_in = _rgba(col, 0.26)
        fig.add_trace(go.Scatter(x=x, y=b[hi], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=b[lo], mode="lines", line=dict(width=0), fill="tonexty", fillcolor=rgba,
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=b["p75"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=b["p25"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor=rgba_in,
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=b["p50"], mode="lines", name=f"{labels[name]}: median",
                                 line=dict(color=col, width=2.4), hovertemplate="%{y:,.0f}"))
    fig.add_hline(y=initial, line=dict(color=p["muted"], width=1, dash="dot"))
    fig = _layout(fig, p, "Value of the investment", height=360, yfmt=",.0f")
    fig.update_xaxes(title=dict(text="Years from today", font=dict(color=p["muted"], size=12)), dtick=1)
    return fig


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def rolling_lines(roll: pd.DataFrame, roll_b: pd.DataFrame, p: dict, bench: str, bcol: str) -> go.Figure:
    """Notebook F4: rolling 36-month Sharpe ratio of the strategy and of the benchmark, and the strategy's beta
    against it (fm_lean.rolling), one panel each."""
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.14,
                        subplot_titles=("Sharpe ratio, rolling 36 months", f"Beta vs {bench}, rolling 36 months"))
    fig.add_trace(go.Scatter(x=roll_b.index, y=roll_b["sharpe"], mode="lines", name=bench,
                             line=dict(color=bcol, width=1.5), hovertemplate="%{y:.2f}"), row=1, col=1)
    fig.add_trace(go.Scatter(x=roll.index, y=roll["sharpe"], mode="lines", name="Strategy",
                             line=dict(color=p["strategy"], width=2.4), hovertemplate="%{y:.2f}"), row=1, col=1)
    fig.add_trace(go.Scatter(x=roll.index, y=roll["beta"], mode="lines", name="Beta", showlegend=False,
                             line=dict(color=p["strategy"], width=2.4), fill="tozeroy",
                             fillcolor=_rgba(p["strategy"], 0.10), hovertemplate="%{y:.2f}"), row=2, col=1)
    fig.add_hline(y=0, line=dict(color=p["muted"], width=1, dash="dot"), row=1, col=1)
    fig.add_hline(y=1, line=dict(color=bcol, width=1, dash="dot"), row=2, col=1)
    fig = _layout(fig, p, "", height=480)
    fig.update_yaxes(range=[0, max(1.15, float(roll["beta"].max()) + 0.1)], row=2, col=1)
    fig.update_annotations(font=dict(size=12, color=p["muted"]), x=0, xanchor="left")
    fig.update_layout(margin=dict(t=78), legend=dict(y=1.1))
    return fig
