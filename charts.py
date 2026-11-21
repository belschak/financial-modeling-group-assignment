"""Plotly figures in the shared design tokens (see design-tokens.md), light and dark variants."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# One palette that reads on both the light and the dark theme (Streamlit's theme detection can lag a
# rerun behind a theme switch, so colours must not depend on it). Hues follow design-tokens.md; the navy
# is lifted one step so it keeps >= 3:1 contrast on the dark background too.
PALETTE = dict(muted="rgba(128,138,155,1)", strategy="#2E68A8", b1="#C08A2B", b2="#8A94A6",
               loss="#B4474A", grid="rgba(128,138,155,0.22)", paper="rgba(0,0,0,0)",
               assets=["#2E68A8", "#5B93C8", "#8DB6DA", "#C08A2B", "#8C6D46"], cash="rgba(150,165,185,0.45)")
PALETTES = {"light": PALETTE, "dark": PALETTE}
FONT = "Inter, -apple-system, Segoe UI, sans-serif"


def _layout(fig: go.Figure, p: dict, ytitle: str, height: int = 380, yfmt: str | None = None, log: bool = False):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=44, b=8),
        paper_bgcolor=p["paper"], plot_bgcolor=p["paper"],
        font=dict(family=FONT, size=13),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)",
                    entrywidth=168, entrywidthmode="pixels", font=dict(size=12)),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=p["grid"], ticks="outside", tickcolor=p["grid"])
    fig.update_yaxes(title=dict(text=ytitle, font=dict(color=p["muted"], size=12)), showgrid=True, gridcolor=p["grid"],
                     zeroline=False, tickformat=yfmt, type="log" if log else "linear")
    return fig


def cumulative(wealth: dict[str, pd.Series], styles: dict[str, dict], p: dict, log: bool = False) -> go.Figure:
    fig = go.Figure()
    for name, w in wealth.items():
        st = styles[name]
        fig.add_trace(go.Scatter(x=w.index, y=w.values, name=name, mode="lines",
                                 line=dict(color=st["color"], width=st.get("width", 2), dash=st.get("dash")),
                                 hovertemplate="%{y:.2f}"))
    fig.add_hline(y=1.0, line=dict(color=p["muted"], width=1, dash="dot"))
    return _layout(fig, p, "Growth of 1 (start = 1.00)", log=log)


def drawdowns(dd: dict[str, pd.Series], styles: dict[str, dict], p: dict) -> go.Figure:
    fig = go.Figure()
    for i, (name, s) in enumerate(dd.items()):
        st = styles[name]
        fill = dict(fill="tozeroy", fillcolor="rgba(180,71,74,0.20)") if i == 0 else {}
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                                 line=dict(color=p["loss"] if i == 0 else st["color"], width=1.6 if i == 0 else 1.3,
                                           dash=None if i == 0 else st.get("dash")),
                                 hovertemplate="%{y:.1%}", **fill))
    return _layout(fig, p, "Fall from previous high", height=280, yfmt=".0%")


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


def cost_curve(grid: pd.DataFrame, chosen: float, breakeven: float | None, labels: tuple[str, str], p: dict,
               ytitle: str = "Growth rate p.a. (CAGR), net of costs", yfmt: str = ".1%") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=grid.index, y=grid["strategy"], name=labels[0], mode="lines+markers",
                             line=dict(color=p["strategy"], width=2), marker=dict(size=5), hovertemplate="%{y:" + yfmt + "}"))
    fig.add_trace(go.Scatter(x=grid.index, y=grid["benchmark"], name=labels[1], mode="lines",
                             line=dict(color=p["b1"], width=2, dash="dash"), hovertemplate="%{y:" + yfmt + "}"))
    fig.add_vline(x=chosen, line=dict(color=p["muted"], width=1, dash="dot"),
                  annotation_text="your setting", annotation_position="bottom left", annotation_font_color=p["muted"])
    if breakeven is not None:
        fig.add_vline(x=breakeven, line=dict(color=p["loss"], width=1),
                      annotation_text=f"breakeven {breakeven:.0f} bps", annotation_position="bottom right",
                      annotation_font_color=p["loss"])
    fig = _layout(fig, p, ytitle, height=320, yfmt=yfmt)
    fig.update_xaxes(title=dict(text="One-way trading cost (basis points)", font=dict(color=p["muted"], size=12)))
    return fig


def annual_bars(annual: pd.DataFrame, cols: list[str], labels: list[str], colors: list[str], p: dict) -> go.Figure:
    """Calendar-year returns, strategy next to the benchmark (PRIIPs style: x-axis at 0%, a label on every bar)."""
    fig = go.Figure()
    for c, lbl, col in zip(cols, labels, colors):
        fig.add_trace(go.Bar(x=annual.index.astype(str), y=annual[c], name=lbl, marker_color=col,
                             text=[f"{v:.1%}" for v in annual[c]], textposition="outside", textangle=-90,
                             textfont=dict(size=10), cliponaxis=False, hovertemplate="%{y:.1%}"))
    fig = _layout(fig, p, "Calendar-year return, net of costs", height=360, yfmt=".0%")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.05, hovermode="x unified")
    fig.update_yaxes(zeroline=True, zerolinecolor=p["muted"], zerolinewidth=1)
    fig.update_xaxes(type="category", showline=False, ticks="")
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
