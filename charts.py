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
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
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
        fig.add_trace(go.Scatter(x=w.index, y=w[c], name=f"{names.get(c, c)} ({c})", stackgroup="one", mode="lines",
                                 line=dict(width=0.4, color=p["assets"][i % len(p["assets"])]),
                                 hovertemplate="%{y:.0%}"))
    fig.add_trace(go.Scatter(x=w.index, y=w["CASH"], name="Cash (risk-free rate)", stackgroup="one", mode="lines",
                             line=dict(width=0.4, color=p["cash"]), hovertemplate="%{y:.0%}"))
    fig = _layout(fig, p, "Share of portfolio at start of month", height=340, yfmt=".0%")
    fig.update_yaxes(range=[0, 1])
    return fig


def cost_curve(grid: pd.DataFrame, chosen: float, breakeven: float | None, labels: tuple[str, str], p: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=grid.index, y=grid["strategy"], name=labels[0], mode="lines+markers",
                             line=dict(color=p["strategy"], width=2), marker=dict(size=5), hovertemplate="%{y:.2%}"))
    fig.add_trace(go.Scatter(x=grid.index, y=grid["benchmark"], name=labels[1], mode="lines",
                             line=dict(color=p["b1"], width=2, dash="dash"), hovertemplate="%{y:.2%}"))
    fig.add_vline(x=chosen, line=dict(color=p["muted"], width=1, dash="dot"),
                  annotation_text="your setting", annotation_position="top left", annotation_font_color=p["muted"])
    if breakeven is not None:
        fig.add_vline(x=breakeven, line=dict(color=p["loss"], width=1),
                      annotation_text=f"breakeven {breakeven:.0f} bps", annotation_position="top right",
                      annotation_font_color=p["loss"])
    fig = _layout(fig, p, "Growth rate p.a. (CAGR), net of costs", height=320, yfmt=".1%")
    fig.update_xaxes(title=dict(text="One-way trading cost (basis points)", font=dict(color=p["muted"], size=12)))
    return fig
