"""Trend-Guarded Multi-Asset: interactive backtest (Nova SBE 2270 Financial Modeling, Group BP).

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
import glass
import replay

REPO_URL = "https://github.com/belschak/financial-modeling-group-assignment"
TEAM = [("Tim Fischer", "78818"), ("Tom Nico H Croe", "78544"), ("David Konrad Belschak", "78842"),
        ("Lennart Schmülling", "79898"), ("Bastian Volkery", "80448"), ("Fridolin Treibig", "78467")]  # = prospectus cover
GROUP = ", ".join(f"{name} ({no})" for name, no in TEAM)
DISCLAIMER = "Hypothetical back-tested results. Past performance does not predict future returns."
COST_STEPS = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
LIVE_RETRY_AFTER_S = 600  # after a failed live download, use the snapshot for 10 minutes before trying again

st.set_page_config(page_title="Trend-Guarded Multi-Asset | Backtest", page_icon=":material/stacked_line_chart:",
                   layout="wide")
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
# Count-up: when a headline number or one of the six measures appears or changes, it counts from its previous value to
# the new one. React's text is never touched: the real value stays in the DOM (hidden while counting) and a CSS
# pseudo-element shows the tween, so a number can never be left stale. Off for prefers-reduced-motion.
st.html(
    """<script>
    (function () {
      if (window.__bpCountUp) return; window.__bpCountUp = true;
      if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      var prev = {}, queued = false;
      function key(el) {
        var m = el.closest('[data-testid="stMetric"]');
        if (m) { var l = m.querySelector('[data-testid="stMetricLabel"]'); return "m:" + (l ? l.textContent : ""); }
        return "h:" + (el.getAttribute("data-k") || "");
      }
      function parse(t) {
        var m = t.match(/^([^0-9-]*)(-?[0-9,]*[.]?[0-9]+)(.*)$/);
        if (!m) return null;
        return { pre: m[1], v: parseFloat(m[2].replace(/,/g, "")), dec: (m[2].split(".")[1] || "").length,
                 comma: m[2].indexOf(",") >= 0, suf: m[3] };
      }
      function fmt(p, v) {
        return p.pre + v.toLocaleString("en-US", { minimumFractionDigits: p.dec, maximumFractionDigits: p.dec,
                                                   useGrouping: p.comma }) + p.suf;
      }
      function animate(el) {
        var t = el.textContent.trim();
        if (el.__bpShown === t) return;
        el.__bpShown = t;
        var k = key(el), p = parse(t), before = prev[k];
        prev[k] = t;
        if (!p) { el.removeAttribute("data-cu"); return; }
        var q = before === undefined ? { v: 0 } : (parse(before) || { v: p.v }), from = q.v;
        if (from === p.v) { el.removeAttribute("data-cu"); return; }
        var t0 = performance.now(), dur = before === undefined ? 1400 : 700, id = (el.__bpId || 0) + 1;
        el.__bpId = id;
        // hard stop: even if animation frames are paused (background tab), the real value shows after `dur`
        setTimeout(function () { if (el.__bpId === id) el.removeAttribute("data-cu"); }, dur + 250);
        (function step(now) {
          if (el.__bpId !== id) return;
          var x = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - x, 3);
          if (x < 1) { el.setAttribute("data-cu", fmt(p, from + (p.v - from) * e)); requestAnimationFrame(step); }
          else el.removeAttribute("data-cu");
        })(t0);
      }
      function scan() {
        queued = false;
        document.querySelectorAll('.cu-n, [data-testid="stMetricValue"] > div').forEach(animate);
      }
      new MutationObserver(function () { if (!queued) { queued = true; requestAnimationFrame(scan); } })
        .observe(document.body, { subtree: true, childList: true, characterData: true });
      scan();
    })();
    </script>""",
    unsafe_allow_javascript=True,
)
# Factsheet look. Streamlit exposes no theme variables to CSS, so every neutral is mixed from the text colour
# (currentColor): the same rules read correctly on the light and the dark theme, with no rerun lag.
st.markdown(
    """
    <style>
      [data-testid="stElementContainer"]:has(> [data-testid="stHtml"] script) { display: none; }
      .stApp {
        --ink2: color-mix(in srgb, currentColor 72%, transparent);
        --ink3: color-mix(in srgb, currentColor 55%, transparent);
        --rule: color-mix(in srgb, currentColor 13%, transparent);
        --rule2: color-mix(in srgb, currentColor 24%, transparent);
        --tint: color-mix(in srgb, currentColor 3.5%, transparent);
        --acc: #2E68A8; --ochre: #C08A2B; --loss: #B4474A; --ok: #2E8B62;
        --serif: 'Source Serif 4', Georgia, serif;
      }
      [data-testid="stDecoration"] { display: none; }
      .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 78rem; }
      [data-testid="stMetricValue"], [data-testid="stDataFrame"], .num { font-variant-numeric: lining-nums tabular-nums; }

      /* masthead */
      .rule-top { height: 3px; background: linear-gradient(90deg, var(--acc) 0 6rem, var(--rule) 6rem); margin-bottom: 1rem; }
      .eyebrow { font-size: .7rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--ink3);
                 display: flex; flex-wrap: wrap; gap: .35rem 1.1rem; }
      .eyebrow b { color: var(--acc); font-weight: 600; }
      .fund { font-family: var(--serif); font-weight: 600; font-size: clamp(1.9rem, 1.2rem + 2.2vw, 2.9rem);
              line-height: 1.08; letter-spacing: -.012em; margin: .55rem 0 .7rem; }
      .nw { white-space: nowrap; }
      .lede { font-size: 1.02rem; line-height: 1.6; max-width: 40rem; color: var(--ink2); margin: 0 0 1rem; }
      .badge { display: inline-flex; align-items: center; gap: .45rem; font-size: .78rem; font-weight: 500;
               padding: .3rem .7rem .3rem .55rem; border-radius: 99px; border: 1px solid var(--rule2); }
      .badge i { width: .55rem; height: .55rem; border-radius: 50%; display: inline-block; }
      .badge.ok { background: color-mix(in srgb, var(--ok) 10%, transparent); border-color: color-mix(in srgb, var(--ok) 45%, transparent); }
      .badge.ok i { background: var(--ok); }
      .badge.cu { background: color-mix(in srgb, var(--ochre) 12%, transparent); border-color: color-mix(in srgb, var(--ochre) 50%, transparent); }
      .badge.cu i { background: var(--ochre); }
      .facts { border-top: 2px solid currentColor; font-size: .82rem; }
      .facts .fh { font-size: .68rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--ink3);
                   padding: .55rem 0 .3rem; }
      .facts dl { display: grid; grid-template-columns: auto 1fr; margin: 0; }
      .facts dt, .facts dd { padding: .42rem 0; border-top: 1px solid var(--rule); margin: 0; }
      .facts dt { color: var(--ink3); padding-right: 1rem; }
      .facts dd { text-align: right; font-weight: 500; }

      /* headline: growth of 10,000 EUR and the drawdown gauge */
      .hero { display: grid; grid-template-columns: 1fr 1.35fr; border-top: 1px solid var(--rule2);
              border-bottom: 1px solid var(--rule2); margin: 1.1rem 0 .5rem; }
      .hero > div { padding: 1.15rem 1.4rem 1.2rem 0; }
      .hero > div + div { padding-left: 1.6rem; border-left: 1px solid var(--rule); padding-right: 0; }
      .k { font-size: .68rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--ink3); }
      .big { font-family: var(--serif); font-weight: 600; font-size: 2.7rem; line-height: 1.1; margin: .35rem 0 .2rem;
             font-variant-numeric: lining-nums tabular-nums; }
      .big small { font-family: inherit; font-size: 1.05rem; color: var(--ink3); margin-left: .3rem; font-weight: 600; }
      .cmp { font-size: .88rem; color: var(--ink2); }
      .cmp b { font-weight: 600; color: currentColor; }
      .hint { font-size: .76rem; color: var(--ink3); margin-top: .5rem; line-height: 1.45; }
      .dd { margin-top: .75rem; }
      .dd-row { display: grid; grid-template-columns: 6.2rem 1fr 3.4rem; align-items: center; gap: .7rem; margin: .45rem 0; }
      .dd-l { font-size: .8rem; color: var(--ink2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .dd-v { font-size: .9rem; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
      .dd-t { position: relative; height: .7rem; background: var(--tint); border-radius: 2px; }
      .dd-t > .bar { position: absolute; inset: 0 auto 0 0; border-radius: 2px; }
      .dd-t > .tk { position: absolute; top: -.25rem; bottom: -.25rem; width: 0; border-left: 1.5px dashed var(--ok); }
      .dd-t > .tk.c { border-left: 1.5px solid var(--loss); }
      .dd-ax { position: relative; height: 1rem; font-size: .68rem; color: var(--ink3); }
      .dd-ax span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
      .dd-ax span.c { color: var(--loss); transform: none; padding-left: .3rem; }
      .dd-ax span.t { color: var(--ok); transform: translateX(-100%); padding-right: .3rem; }
      .after { font-size: .8rem; color: var(--ink2); line-height: 1.5; margin: .35rem 0 0; }

      /* the six required measures: two ruled groups, factsheet "key figures" */
      .grp-h { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; border-bottom: 2px solid var(--acc);
               padding-bottom: .4rem; margin-top: 1.6rem; }
      .grp-h span:first-child { font-size: .72rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; }
      .grp-h span + span { font-size: .74rem; color: var(--ink3); }
      .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] { gap: 0; flex-wrap: nowrap; }
      .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
               min-width: 0; border-bottom: 1px solid var(--rule); }
      .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] + [data-testid="stColumn"] {
               border-left: 1px solid var(--rule); }
      .st-key-kpis [data-testid="stMetric"] { padding: .85rem .9rem .8rem; }
      .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child [data-testid="stMetric"] { padding-left: 0; }
      [data-testid="stMetricLabel"] p { font-size: .78rem; color: var(--ink2); }
      .st-key-kpis [data-testid="stMetricLabel"] { min-height: 2.3em; align-items: flex-start; }
      [data-testid="stMetricLabel"] div, [data-testid="stMetricLabel"] p { white-space: normal !important;
               overflow: visible !important; text-overflow: clip !important; }
      .st-key-kpis [data-testid="stMetricValue"] > div { font-size: 2.05rem; font-weight: 500; letter-spacing: -.01em; }
      [data-testid="stMetricDelta"] { font-size: .76rem; }
      .st-key-kpis_cost [data-testid="stColumn"] { border-top: 1px solid var(--rule2); border-bottom: 1px solid var(--rule); }
      .st-key-kpis_cost [data-testid="stColumn"] + [data-testid="stColumn"] { border-left: 1px solid var(--rule); }
      .st-key-kpis_cost [data-testid="stHorizontalBlock"] { gap: 0; }
      .st-key-kpis_cost [data-testid="stMetric"] { padding: .8rem .9rem .7rem; }
      .st-key-kpis_cost [data-testid="stColumn"]:first-child [data-testid="stMetric"] { padding-left: 0; }
      .st-key-kpis_cost [data-testid="stMetricValue"] > div { font-size: 1.7rem; font-weight: 500; }
      .foot-n { font-size: .78rem; color: var(--ink3); line-height: 1.55; margin-top: .7rem; max-width: 62rem; }
      .foot-n b { color: var(--ink2); }

      /* sections */
      [data-testid="stTabs"] { margin-top: 1.4rem; }
      [data-testid="stTabs"] [role="tablist"] { gap: 1.5rem; border-bottom: 1px solid var(--rule2); }
      [data-testid="stTabs"] button[role="tab"] p { font-size: .74rem; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; }
      [data-testid="stTabs"] button[role="tab"][aria-selected="false"] p { color: var(--ink3); }
      .ch { margin: 1.6rem 0 .1rem; }
      .ch-t { font-family: var(--serif); font-size: 1.22rem; font-weight: 600; line-height: 1.3; }
      .ch-s { font-size: .8rem; color: var(--ink3); margin-top: .2rem; line-height: 1.45; }
      .src { font-size: .74rem; color: var(--ink3); line-height: 1.5; }
      .src.line { border-top: 1px solid var(--rule); padding-top: .45rem; margin-top: -.2rem; }

      /* sidebar */
      [data-testid="stSidebar"] .sb-e { font-size: .66rem; font-weight: 600; letter-spacing: .16em; text-transform: uppercase; color: var(--acc); }
      [data-testid="stSidebar"] .sb-t { font-family: var(--serif); font-size: 1.45rem; font-weight: 600; margin: .1rem 0 .35rem; }
      [data-testid="stSidebar"] .sb-s { font-size: .78rem; color: var(--ink3); line-height: 1.5; }
      [data-testid="stSidebar"] .sb-g { font-size: .68rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
               color: var(--ink2); border-top: 1px solid var(--rule2); padding-top: .8rem; margin-top: .6rem; }

      /* important information */
      .ii { margin-top: 3rem; border-top: 2px solid currentColor; padding-top: .8rem; }
      .ii-g { display: grid; grid-template-columns: 1.1fr 1fr; gap: 1rem 2.4rem; margin-top: .55rem; }
      .ii p { font-size: .76rem; line-height: 1.6; color: var(--ink3); margin: 0 0 .5rem; }
      .ii p b { color: var(--ink2); font-weight: 600; }
      .ii a { color: var(--acc); }

      /* ---------- motion layer: every moving part carries data or eases the eye; all off for reduced motion */
      .block-container { position: relative; }
      .block-container > * { position: relative; z-index: 1; }
      .block-container::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 36rem; z-index: 0;
        pointer-events: none;
        background:
          radial-gradient(26rem 15rem at 18% 22%, rgba(46,104,168,.17), transparent 70%),
          radial-gradient(22rem 13rem at 82% 12%, rgba(192,138,43,.13), transparent 70%),
          radial-gradient(30rem 16rem at 55% 75%, rgba(91,147,200,.12), transparent 70%);
        background-size: 160% 160%; background-position: 0% 0%;
        animation: drift 28s ease-in-out infinite alternate;
        mask-image: linear-gradient(to bottom, #000 40%, transparent); -webkit-mask-image: linear-gradient(to bottom, #000 40%, transparent); }
      .block-container::after { content: ""; position: absolute; inset: 0 0 auto 0; height: 30rem; z-index: 0;
        pointer-events: none; opacity: .5;
        background-image: linear-gradient(var(--rule) 1px, transparent 1px), linear-gradient(90deg, var(--rule) 1px, transparent 1px);
        background-size: 3rem 3rem; animation: gridpan 60s linear infinite;
        mask-image: radial-gradient(60% 70% at 70% 0%, #000, transparent 75%);
        -webkit-mask-image: radial-gradient(60% 70% at 70% 0%, #000, transparent 75%); }
      @keyframes drift { 0% { background-position: 0% 0%; } 50% { background-position: 60% 40%; } 100% { background-position: 100% 10%; } }
      @keyframes gridpan { to { background-position: 3rem 3rem, 3rem 3rem; } }
      @keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
      @keyframes grow { from { transform: scaleX(0); } }
      @keyframes draw { to { stroke-dashoffset: 0; } }
      @keyframes fadein { from { opacity: 0; } }
      @keyframes ping { 0% { transform: scale(1); opacity: .55; } 80%, 100% { transform: scale(3.2); opacity: 0; } }
      @keyframes tape { to { transform: translateX(-50%); } }
      .eyebrow { animation: rise .7s cubic-bezier(.2,.7,.2,1) both; }
      .fund { animation: rise .8s cubic-bezier(.2,.7,.2,1) .06s both; }
      .lede { animation: rise .8s cubic-bezier(.2,.7,.2,1) .12s both; }
      .badge { animation: rise .8s cubic-bezier(.2,.7,.2,1) .18s both; }
      .facts { animation: rise .9s cubic-bezier(.2,.7,.2,1) .15s both; }
      .facts dt, .facts dd { transition: background .2s; }
      .tape { animation: fadein 1s .3s both; }
      .hero { animation: rise .9s cubic-bezier(.2,.7,.2,1) .2s both; }
      .grp-h { animation: rise .8s cubic-bezier(.2,.7,.2,1) .3s both; }
      .dd-t > .bar { transform-origin: left; animation: grow 1.3s cubic-bezier(.2,.7,.2,1) .45s both; }
      .live { display: inline-flex; align-items: center; gap: .45rem; }
      .live i { position: relative; width: .45rem; height: .45rem; border-radius: 50%; background: var(--ok); display: inline-block; }
      .live i::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: var(--ok); animation: ping 2.4s cubic-bezier(0,0,.2,1) infinite; }
      .live.snap i, .live.snap i::after { background: var(--ochre); }
      .live.snap i::after { animation: none; }
      /* sparkline of the real growth path in the headline */
      .spark { position: relative; height: 4.2rem; margin: .9rem 0 .2rem; }
      .spark svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
      .spark path { fill: none; vector-effect: non-scaling-stroke; stroke-linecap: round; stroke-linejoin: round;
                    stroke-dasharray: 1; stroke-dashoffset: 1; animation: draw 2.2s cubic-bezier(.45,.05,.2,1) .35s forwards; }
      .spark path.s { stroke-width: 2.2; }
      .spark path.b { stroke-width: 1.3; stroke-opacity: .85; animation-delay: .5s; }
      .spark path.area { stroke: none; stroke-dasharray: none; animation: fadein 1.6s 1.4s both; }
      .spark .dot { position: absolute; width: .5rem; height: .5rem; margin: -.25rem 0 0 -.25rem; border-radius: 50%;
                    animation: fadein .4s 2.4s both; }
      .spark .dot::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: inherit;
                           animation: ping 2.4s cubic-bezier(0,0,.2,1) 2.6s infinite; }
      /* ticker of calendar-year returns */
      .tape { position: relative; overflow: hidden; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
              margin: 1.5rem 0 0; padding: .5rem 0; font-size: .76rem; white-space: nowrap;
              mask-image: linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent);
              -webkit-mask-image: linear-gradient(90deg, transparent, #000 6%, #000 94%, transparent); }
      .tape-in { display: inline-flex; animation: tape 80s linear infinite; }
      .tape:hover .tape-in { animation-play-state: paused; }
      .tape span { padding: 0 1.4rem; border-right: 1px solid var(--rule); color: var(--ink3); }
      .tape span b { color: currentColor; font-weight: 600; margin-right: .5rem; }
      .tape .up { color: var(--ok); } .tape .dn { color: var(--loss); }
      .tape em { font-style: normal; font-variant-numeric: tabular-nums; margin-left: .25rem; }
      /* count-up: the real number stays in the DOM; while counting it is hidden and a pseudo-element shows the tween */
      [data-cu] { position: relative; }
      [data-cu]::after { content: attr(data-cu); position: absolute; left: 0; top: 0; -webkit-text-fill-color: currentColor; }
      [data-cu] { -webkit-text-fill-color: transparent; }
      .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { transition: background .25s; }
      .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:hover { background: var(--tint); }
      @media (prefers-reduced-motion: reduce) {
        .block-container::before, .block-container::after, .eyebrow, .fund, .lede, .badge, .facts, .tape, .hero, .grp-h,
        .dd-t > .bar, .live i::after, .spark path, .spark .dot, .spark .dot::after, .tape-in { animation: none !important; }
        .spark path { stroke-dashoffset: 0; }
        .tape { white-space: normal; } .tape-in { flex-wrap: wrap; } .tape-in > span:nth-child(n+100) { display: none; }
      }

      @media (max-width: 640px) {
        .block-container { padding-top: 1.4rem; }
        .hero { grid-template-columns: 1fr; }
        .hero > div { padding: 1rem 0; }
        .hero > div + div { padding-left: 0; border-left: 0; border-top: 1px solid var(--rule); }
        .big { font-size: 2.3rem; }
        .ii-g { grid-template-columns: 1fr; }
        .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                 width: 33.33% !important; flex: 1 1 0 !important; }
        .st-key-kpis [data-testid="stMetric"] { padding: .7rem .5rem .6rem; }
        .st-key-kpis [data-testid="stMetricValue"] > div { font-size: 1.5rem; }
        .st-key-kpis [data-testid="stMetricLabel"] { min-height: 3.5em; }
        .st-key-kpis [data-testid="stMetricDelta"] div { white-space: normal !important; overflow: visible !important; }
        .st-key-kpis > [data-testid="stHorizontalBlock"] { gap: 0 !important; }
        .grp-h { margin-top: 1.2rem; }
        .eyebrow span:nth-child(3), .eyebrow span:nth-child(4) { display: none; }
        [data-testid="stTabs"] [role="tablist"] { gap: 1rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


html(glass.CSS)
html(glass.STAGE)
st.html(glass.JS, unsafe_allow_javascript=True)


def chart_head(title: str, sub: str | None = None):
    html(f"<div class='ch'><div class='ch-t'>{title}</div>" + (f"<div class='ch-s'>{sub}</div>" if sub else "") + "</div>")


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
months = pd.period_range(core.FIRST_MONTH, last_month.strftime("%Y-%m"), freq="M").strftime("%Y-%m").tolist()

# ---------------------------------------------------------------- sidebar: assumptions
with st.sidebar:
    html("<div class='sb-e'>Model inputs</div><div class='sb-t'>Your assumptions</div>"
         "<div class='sb-s'>Change any input and every number recalculates. The defaults reproduce prospectus "
         "Table 1.</div><div class='sb-g'>Trend rule</div>")
    st.slider("Moving-average window (months)", 6, 12, key="sma",
              help="A sleeve is held only while its month-end price is above its average over this many months. "
                   "10 comes from Faber (2007); we did not optimise it.")
    st.radio("Signal delay (months)", [1, 2], key="lag", horizontal=True,
             help="1: the signal from the close of month t sets the holdings for month t+1. 2: act one month later.")
    st.radio("Trade at", [False, True], key="next_day",
             format_func=lambda x: "next trading day's close (realistic)" if x else "month-end close (prospectus)",
             help="The signal always uses the month-end close. Trading at that same close is Faber's standard; "
                  "the next trading day's close is what an investor can really do.")
    html("<div class='sb-g'>Costs and period</div>")
    st.select_slider("Trading cost (bps per trade, one-way)", options=COST_STEPS, key="cost_bps",
                     help="Charged on every euro of ETF bought or sold (1 bp = 0.01%). 10 bps = fund level (base case), "
                          "50 bps = the lecture's all-in retail figure. Benchmarks pay the same cost on their trades.")
    # value= makes it a RANGE slider; the key changes on Reset, so the browser shows the default range again.
    PKEY = f"period_{st.session_state['period_rev']}"
    if PKEY in st.session_state and any(m not in months for m in st.session_state[PKEY]):
        del st.session_state[PKEY]
    st.select_slider("Backtest period", options=months, key=PKEY,
                     value=st.session_state.get(PKEY, (core.DEFAULTS["start"], min(core.DEFAULTS["end"], months[-1]))),
                     help="Earliest start is Jan 2005, as in the notebook. Before their own first prices, DBC (Feb 2006) "
                          "and GLD (Nov 2004) are chained to their index (S&P GSCI, gold futures), as disclosed in the "
                          "prospectus.")
    html("<div class='sb-g'>Sleeves in the portfolio</div>")
    st.pills("Assets", fl.TICKERS, selection_mode="multi", key="tickers", label_visibility="collapsed",
             format_func=lambda t: f"{t} · {core.NAMES[t]} · {fl.WEIGHTS[t]:.0%}",
             help="Target weights: 20% each for SPY, EFA, IEF and XLU, 10% each for DBC and GLD. Deselect a sleeve and "
                  "the others keep their proportions, scaled up to 100%. B1 always holds the same mix.")
    html("<div class='sb-g'>Benchmark for alpha, beta and IR</div>")
    st.radio("Benchmark", list(core.BENCH), key="bench", label_visibility="collapsed",
             format_func=lambda b: core.BENCH[b],
             help="B1 holds the same sleeves, always invested: it isolates what the trend filter adds. B2 is the classic "
                  "60/40 the client could buy instead. B3 is one world-equity fund (iShares Core MSCI World UCITS, EUR).")
    with st.expander("Data source"):
        st.radio("Data", ["live", "snapshot"], key="data_pref", label_visibility="collapsed",
                 format_func=lambda s: "Live: Yahoo Finance, ECB, FRED" if s == "live" else "Stored snapshot (offline)")
        st.caption("Live data are cached for 12 hours. The snapshot only steps in if Yahoo throttles the server.")
    st.button("Reset to prospectus defaults", on_click=reset_defaults, width="stretch", type="primary",
              icon=":material/restart_alt:")

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
    notes.append(f"End moved to {core.month_end(ui['end']):%b %Y}: trading one day after the month-end signal needs the first trading day of the next month.")
is_default = all(ui[k] == core.DEFAULTS[k] for k in core.DEFAULTS)
WTS = core.weights(ui["tickers"]) if ui["tickers"] else {}

# ---------------------------------------------------------------- masthead
LIVE = data["origin"] == "live"
status = ("<span class='st ok'><i></i>Defaults: matches prospectus Table 1</span>" if is_default else
          "<span class='st cu'><i></i>Custom assumptions: differs from prospectus</span>")
if len(WTS) == len(fl.TICKERS):
    SLEEVES = ("Six asset classes in fixed slices: US equity, developed ex-US equity, US Treasuries (hedged to EUR) and "
               "US utilities 20% each, commodities and gold 10% each.")
else:
    SLEEVES = (f"{len(WTS)} asset classes in fixed slices: "
               + ", ".join(f"{core.NAMES[t].lower().replace('us ', 'US ')} {w:.0%}" for t, w in WTS.items()) + ".")
MAST = ("<div class='mh-ctx'><span>Hypothetical fund</span><span>Multi-asset trend following</span><span>EUR</span></div>"
        f"<div class='fund'>{core.STRATEGY.replace('Multi-Asset', '<span class=nw>Multi-Asset</span>')}</div>"
        f"<div class='lede'>{SLEEVES} At every month-end a slice stays invested only while its price is above its "
        f"{ui['sma']}-month average; otherwise it waits in euro cash. Built for cautious euro-area savers about 10 years "
        f"from retirement who cannot sit through a fall of more than {core.CLIENT_DD_CEILING:.0%}.</div>"
        f"<div class='mh-meta'>{status}<span class='st live{'' if LIVE else ' snap'}'><i></i>"
        f"{'Live market data' if LIVE else 'Stored snapshot'}</span></div>")
# The stage (follows the theme): masthead now, completed with the crash-protection view once the backtest has run.
stage_slot = st.empty()
stage_slot.markdown(f"<section class='stage'><div class='stg-in'><div class='stg-l'>{MAST}</div></div></section>",
                    unsafe_allow_html=True)
if data_warning:
    st.warning(data_warning, icon=":material/cloud_off:")
for n in notes:
    st.info(n, icon=":material/history:")
if len(ui["tickers"]) < 2:
    st.warning("Select at least two sleeves in the sidebar.")
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
LBL = {"Strategy": LBL_S, **core.BENCH}
PCOL = {"Strategy": pal["strategy"], "B1": pal["b1"], "B2": pal["b2"], "B3": pal["b3"]}
styles = {LBL_S: dict(color=pal["strategy"], width=2.6), LBL_G: dict(color=pal["strategy"], width=1.2, dash="dot"),
          core.BENCH["B1"]: dict(color=pal["b1"], width=2), core.BENCH["B2"]: dict(color=pal["b2"], width=2, dash="dash"),
          core.BENCH["B3"]: dict(color=pal["b3"], width=1.8)}
CV = {"Strategy": "var(--c-s)", "B1": "var(--c-b1)", "B2": "var(--c-b2)", "B3": "var(--c-b3)"}   # theme-aware CSS colours
BCOL = CV[B]
first, last = net.index[0], net.index[-1]
trade_at = "next trading day's close" if ui["next_day"] else "month-end close"
facts = [("Backtest period", f"{first:%b %Y} to {last:%b %Y}"), ("Observations", f"{len(net)} months"),
         ("Trend rule", f"{ui['sma']}-month average, lag {ui['lag']}"), ("Trades at", trade_at),
         ("Trading cost", f"{ui['cost_bps']} bps one-way"),
         ("Sleeves", " · ".join(f"{t} {w * 100:.0f}" for t, w in WTS.items())),
         ("Benchmark", BL), ("Rebalancing", "Monthly, back to target weights")]
SPEC = ("<div class='spec' aria-label='Key facts'>"
        + "".join(f"<div><span>{a}</span><b>{b}</b></div>" for a, b in facts) + "</div>")


def pct(x, d=1):
    if x is None or pd.isna(x):
        return "n/a"
    return f"{0.0 if abs(x) < 0.5 * 10 ** -(d + 2) else x:.{d}%}"  # no "-0.0%"


def num(x, d=2):
    if x is None or pd.isna(x):
        return "n/a"
    return f"{0.0 if abs(x) < 0.5 * 10 ** -d else x:.{d}f}"


def spct(x, d=1):
    """Signed percentage, '+4.6%' / '-23.7%' (no '-0.0%')."""
    return f"{0.0 if abs(x) < 0.5 * 10 ** -(d + 2) else x:+.{d}%}"


S = T.loc["Strategy"]
# ---------------------------------------------------------------- the stage: crash protection first
DD = {k: -T.loc[k, "max_drawdown"] for k in core.PORTS}
scale = max(0.4, math.ceil((max(*DD.values(), core.CLIENT_DD_CEILING) + 0.02) * 10) / 10)


def at(x):
    """Position on the drawdown gauge (0 to `scale`), as a CSS percentage."""
    return f"{min(max(x, 0), scale) / scale * 100:.2f}%"


ticks = (f"<i class='tk' style='left:{at(core.CLIENT_DD_TARGET)}'></i>"
         f"<i class='tk c' style='left:{at(core.CLIENT_DD_CEILING)}'></i>")


def dd_row(label, v, color):
    return (f"<div class='dd-row'><span class='dd-l'>{label}</span><div class='dd-t'><div class='bar' style='width:"
            f"{at(v)};background:{color}'></div>{ticks}</div><span class='dd-v'>-{v:.1%}</span></div>")


GAUGE = ("<div class='dd'>" + "".join(dd_row(core.SHORT[k], DD[k], CV[k]) for k in core.PORTS)
         + "<div class='dd-row'><span></span><div class='dd-ax'>"
         f"<span class='t' style='left:{at(core.CLIENT_DD_TARGET)}'>target {core.CLIENT_DD_TARGET:.0%}</span>"
         f"<span class='c' style='left:{at(core.CLIENT_DD_CEILING)}'>ceiling {core.CLIENT_DD_CEILING:.0%}</span>"
         "</div><span></span></div></div>")
CARD = {"Strategy": "Strategy", "B1": "B1 mix", "B2": "B2 60/40", "B3": "B3 World"}
UW_SHORT = {"Financial crisis": "Financial crisis", "Euro crisis": "Euro crisis", "Covid crash": "Covid",
            "2022 inflation shock": "2022"}


def underwater() -> str:
    """Every portfolio's fall from its previous high, month by month (fl.drawdown of the net returns), as a full-width
    lane on the stage. The SVG is stretched to the lane; all text is HTML on top, so nothing is ever distorted."""
    dds = {k: fl.drawdown(net[k]) for k in core.PORTS}
    idx = dds["Strategy"].index
    n = len(idx)
    floor = min(min(float(v.min()) for v in dds.values()), -core.CLIENT_DD_CEILING) * 1.08
    H = 200.0
    y = lambda v: H * v / floor                                   # 0 at the top, the floor at the bottom
    x = lambda i: 1000.0 * i / (n - 1)
    pth = lambda s: "M" + " L".join(f"{x(i):.1f} {y(v):.1f}" for i, v in enumerate(s.to_numpy()))
    fy = lambda v: f"calc(1.3rem + {y(v) / H:.4f} * (100% - 2.7rem))"
    fx = lambda i: f"calc(2.6rem + {x(i) / 1000:.4f} * (100% - 2.6rem))"
    svg, lab = [], []
    for name, a, b in core.CRISES:
        i0, i1 = idx.get_indexer([core.month_end(a), core.month_end(b)])
        if i0 < 0 or i1 < 0:
            continue
        svg.append(f"<rect class='band' x='{x(i0 - 1):.1f}' y='0' width='{max(x(i1) - x(i0 - 1), 4):.1f}' height='{H:.0f}'/>")
        lab.append(f"<span class='uw-c' style='left:{fx((i0 + i1) / 2)}'>{UW_SHORT[name]}</span>")
    step = 0.1 if floor > -0.6 else 0.2
    g = 0.0
    while g >= floor:
        svg.append(f"<line class='gl' x1='0' x2='1000' y1='{y(g):.1f}' y2='{y(g):.1f}'/>")
        lab.append(f"<span class='uw-y' style='top:{fy(g)}'>{g:.0%}</span>")
        g = round(g - step, 6)
    svg.append(f"<line class='tl' x1='0' x2='1000' y1='{y(-core.CLIENT_DD_TARGET):.1f}' y2='{y(-core.CLIENT_DD_TARGET):.1f}'/>"
               f"<line class='cl' x1='0' x2='1000' y1='{y(-core.CLIENT_DD_CEILING):.1f}' y2='{y(-core.CLIENT_DD_CEILING):.1f}'/>")
    lab.append(f"<span class='uw-r t' style='top:{fy(-core.CLIENT_DD_TARGET)}'>client target -{core.CLIENT_DD_TARGET:.0%}</span>"
               f"<span class='uw-r c' style='top:{fy(-core.CLIENT_DD_CEILING)}'>ceiling -{core.CLIENT_DD_CEILING:.0%}</span>")
    for k in ("B3", "B2", "B1"):
        svg.append(f"<path class='ln b' d='{pth(dds[k])}' style='stroke:{CV[k]}'/>")
    ps = pth(dds["Strategy"])
    svg.append(f"<path class='ar' d='{ps} L1000 0 L0 0 Z'/><path class='ln s' d='{ps}'/>")
    years = sorted({d.year for d in idx[1:]})
    every = 4 if len(years) > 12 else 2 if len(years) > 6 else 1
    for yr in years[::every]:
        i = idx.get_indexer([pd.Timestamp(f"{yr}-01-31")])[0]
        if i >= 0:
            lab.append(f"<span class='uw-x' style='left:{fx(i)}'>{yr}</span>")
    leg = "".join(f"<span><i style='background:{CV[k]}'></i>{core.SHORT[k]} {-DD[k]:.1%}</span>" for k in core.PORTS)
    return ("<div class='uw'><div class='uw-h'><span class='k'>Fall from the previous high, month by month, net of costs"
            f"</span><div class='uw-leg'>{leg}</div></div><div class='uw-p' role='img' aria-label='Drawdown of the strategy "
            f"and the three benchmarks, {first:%b %Y} to {last:%b %Y}'>"
            f"<svg viewBox='0 0 1000 {H:.0f}' preserveAspectRatio='none' aria-hidden='true'>{''.join(svg)}</svg>"
            f"{''.join(lab)}</div></div>")


held_last = bt["weights"].loc[net.index[-1]]
chips = "".join(
    f"<span class='chip {'in' if held_last.get(t, 0) > 0 else 'out'}' style='--d:{i}'><i></i><b>{t}</b>"
    f"<small>{core.NAMES[t]}</small><em>{'held' if held_last.get(t, 0) > 0 else 'in cash'}</em></span>"
    for i, t in enumerate(ui["tickers"]))
stage_slot.markdown(
    "<section class='stage'><div class='stg-grid' aria-hidden='true'></div>"
    "<div class='stg-orb' aria-hidden='true'></div><div class='stg-in'><div class='stg-l'>" + MAST + "</div>"
    f"<div class='stg-r'><div class='k'>Worst fall from a previous high, {first:%b %Y} to {last:%b %Y}</div>"
    f"<div class='mega'><span class='cu-n' data-k='hero'>-{DD['Strategy'] * 100:.1f}%</span><small>Strategy, net</small></div>"
    + GAUGE +
    f"<div class='hint'>The client's target is a worst fall of at most {core.CLIENT_DD_TARGET:.0%}, with "
    f"{core.CLIENT_DD_CEILING:.0%} as the hard ceiling. 10,000 EUR became {10000 * S['final_wealth']:,.0f} EUR "
    f"(B1 {10000 * T.loc['B1', 'final_wealth']:,.0f}, B2 {10000 * T.loc['B2', 'final_wealth']:,.0f}, "
    f"B3 {10000 * T.loc['B3', 'final_wealth']:,.0f}).</div>"
    f"<div class='k chips-k'>Holdings in {last:%b %Y}</div><div class='chips'>{chips}</div>"
    "</div></div>" + underwater() + SPEC + "</section>", unsafe_allow_html=True)

if not ui["next_day"]:
    nd = run_cached(tuple(sorted({**ui, "next_day": True, "end": min(ui["end"], dl.last_complete_month(
        data, next_day=True).strftime("%Y-%m"))}.items())), STAMP, core.SHA, data)["table"].loc["Strategy"]
    html(f"<div class='after'>Traded at the next trading day's close instead (realistic): Sharpe ratio "
         f"{num(nd['sharpe'])}, largest fall {-nd['max_drawdown']:.1%}. <span class='src'>{DISCLAIMER}</span></div>")
else:
    html(f"<div class='after'><span class='src'>{DISCLAIMER}</span></div>")


def sec_head(k: str, title: str, sub: str):
    html(f"<div class='sec-h ch'><div class='k'>{k}</div><div class='ch-t'>{title}</div><div class='ch-s'>{sub}</div></div>")


def dv_rows(vals: dict, lo: float, hi: float, labels: dict) -> str:
    """Diverging bars around zero, one per portfolio, on a shared scale lo..hi."""
    span = (hi - lo) or 1
    z = -lo / span
    out = []
    for k, v in vals.items():
        left, width = z + min(v, 0) / span, abs(v) / span
        out.append(f"<div><span>{labels[k]}</span><i style='--z:{z * 100:.1f}%'><u style='left:{left * 100:.2f}%;"
                   f"width:{width * 100:.2f}%;background:{CV[k]};--o:{'right' if v < 0 else 'left'}'></u></i>"
                   f"<b class='{'pos' if v >= 0 else 'neg'}'>{spct(v)}</b></div>")
    return "<div class='dv'>" + "".join(out) + "</div>"


# ---------------------------------------------------------------- four crises (notebook section 7, same windows)
CR = core.crises(bt)
if len(CR):
    vals = CR[list(core.PORTS)].astype(float)
    lo, hi = min(float(vals.min().min()), 0.0), max(float(vals.max().max()), 0.0)
    sec_head("Crash protection", "How it held up in the crises",
             "Total return from the first to the last month of each window, net of costs: the same windows as the "
             "notebook's crisis table.")
    cards = ""
    for name, r in CR.iterrows():
        v = float(r["Strategy"])
        cards += (f"<div class='crc'><div class='cn'>{name}</div><div class='cd'>{core.month_end(r['start']):%b %Y} to "
                  f"{core.month_end(r['end']):%b %Y}</div><div class='cv {'pos' if v >= 0 else 'neg'}'>{spct(v)}</div>"
                  "<div class='cs'>Strategy over the window</div>"
                  + dv_rows({k: float(r[k]) for k in core.PORTS}, lo, hi, CARD) + "</div>")
    html(f"<div class='crg'>{cards}</div>")

# ---------------------------------------------------------------- the price: long bull markets (notebook section 8)
BU = core.bull_markets(bt)
WHOLE = "Whole period"
opts = list(BU.index) + [WHOLE]
sec_head("The price of protection", "Where it lags: long bull markets",
         "The rule re-enters a sleeve only after its price is back above its average, so in steady rallies it trails "
         "the always-invested portfolios. Compound return a year over each window, net of costs (the notebook's "
         "bull-market table).")
if st.session_state.get("bull_win") not in opts:
    st.session_state["bull_win"] = opts[0]
with st.container(key="bull"):
    win = st.segmented_control("Window", opts, key="bull_win", label_visibility="collapsed",
                               format_func=lambda o: o if o == WHOLE else f"{BU.loc[o, 'start'][:4]}-{BU.loc[o, 'end'][:4]}: "
                               + ("crisis low to Covid" if BU.loc[o, "start"] == "2009-03" else "rally")) or opts[0]
    if win == WHOLE:
        a, b = f"{first:%Y-%m}", f"{last:%Y-%m}"
    else:
        a, b = BU.loc[win, "start"], BU.loc[win, "end"]
    xw = net.loc[a:b]
    cg = {k: float((1 + xw[k]).prod() ** (12 / len(xw)) - 1) for k in core.PORTS}
    wf = {k: float(fl.drawdown(xw[k]).min()) for k in core.PORTS}
    lead = max(("B1", "B2", "B3"), key=lambda k: cg[k])
    gap = cg[lead] - cg["Strategy"]
    verdict = (f"The strategy grew <b>{pct(cg['Strategy'])}</b> a year, {gap * 100:.1f} percentage points a year less "
               f"than {core.SHORT[lead]} ({pct(cg[lead])})." if gap > 0 else
               f"The strategy grew <b>{pct(cg['Strategy'])}</b> a year, ahead of all three benchmarks.")
    c1, c2 = st.columns([1, 1.75], gap="medium")
    with c1:
        html(f"<div class='blc'><div class='cn'>{win if win != WHOLE else 'Whole backtest'}</div>"
             f"<div class='cd ch-s'>{core.month_end(a):%b %Y} to {core.month_end(b):%b %Y}, {len(xw)} months</div>"
             f"<div class='cv'>{pct(cg['Strategy'])}<small>a year</small></div>"
             f"<div class='cs'>{verdict} What it bought: a worst fall of {pct(wf['Strategy'])} against "
             f"{pct(wf['B3'])} for the MSCI World over the same months.</div>"
             + dv_rows(cg, 0.0, max(max(cg.values()), 0.0), core.SHORT) + "</div>")
    with c2:
        wb = {LBL[k]: fl.wealth(xw[k]) for k in core.PORTS}
        fig = charts.cumulative(wb, styles, pal)
        fig.update_layout(height=340, margin=dict(t=40))
        fig.update_yaxes(title=dict(text=f"Growth of 1 from {core.month_end(a) - pd.offsets.MonthEnd(1):%b %Y}"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

HELP = {
    "ann_return": "Average monthly return x 12 (arithmetic, as the brief asks). The growth rate actually earned "
                  "(CAGR) is in the full table.",
    "ann_vol": "How much returns swing: standard deviation of monthly returns x sqrt(12).",
    "sharpe": "Return above the euro cash rate per unit of risk: mean monthly excess return / its standard deviation, "
              "x sqrt(12).",
    "alpha_ann": "Return beyond what the exposure to the benchmark explains (Jensen's alpha, OLS on monthly excess "
                 "returns), x 12. The t-statistic tells whether it is distinguishable from luck (roughly |t| > 2).",
    "ir": "Regression form (class definition, W3): alpha / volatility of the regression residuals, x sqrt(12). "
          "The tracking-error form is in the note below the figures.",
    "beta": "Sensitivity to the benchmark: covariance / variance of monthly excess returns. Not annualised.",
}

# ---------------------------------------------------------------- the six required measures: a bento of glass cards
# Each card: the measure (st.metric, the number of record) plus a small picture of the same fm_lean output.
d_ret, d_vol, d_sh = (S[k] - T.loc[B, k] for k in ("ann_return", "ann_vol", "sharpe"))
ROLL = fl.rolling(net["Strategy"], net[B], bt["rf"]) if len(net) > 36 else pd.DataFrame()


def _pts(vals, w=1000.0, top=10.0, bot=290.0, lo=None, hi=None):
    lo = min(vals) if lo is None else lo
    hi = max(vals) if hi is None else hi
    n = len(vals)
    return [(w * i / max(n - 1, 1), bot - (bot - top) * (v - lo) / ((hi - lo) or 1)) for i, v in enumerate(vals)]


def _d(pts):
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)


WS, WB = fl.wealth(net["Strategy"]).to_numpy(), fl.wealth(net[B]).to_numpy()
W_LO, W_HI = min(WS.min(), WB.min()), max(WS.max(), WB.max())


def _mv(inner: str, cls: str = "", vb: str = "0 0 200 56", par: str = "none") -> str:
    return f"<svg class='mv {cls}' viewBox='{vb}' preserveAspectRatio='{par}' aria-hidden='true'>{inner}</svg>"


def _cap(text: str) -> str:
    return f"<div class='mcap'>{text}</div>"


def mini_growth() -> str:
    ps, pb = (_pts(w, w=200, top=4, bot=54, lo=W_LO, hi=W_HI) for w in (WS, WB))
    return (_mv(f"<path class='ar' d='{_d(ps)} L200 56 L0 56 Z'/><path class='ln b' pathLength='1' d='{_d(pb)}' "
                f"style='stroke:{BCOL}'/><path class='ln s' pathLength='1' d='{_d(ps)}'/>", "g")
            + _cap(f"Growth path, strategy vs {B}, {first:%Y} to {last:%Y}"))


def mini_vol() -> str:
    vs, vb = S["ann_vol"], T.loc[B, "ann_vol"]
    mx = max(vs, vb) or 1
    return ("<div class='mbars'>"
            f"<div><span>Strategy</span><i><u style='width:{vs / mx * 100:.1f}%;background:var(--c-s)'></u></i>"
            f"<b>{pct(vs)}</b></div>"
            f"<div><span>{B}</span><i><u style='width:{vb / mx * 100:.1f}%;background:{BCOL}'></u></i>"
            f"<b>{pct(vb)}</b></div></div>" + _cap("Swing of returns, strategy vs benchmark"))


def mini_sharpe() -> str:
    if ROLL.empty:
        return _cap("The rolling view needs more than 36 months.")
    v = ROLL["sharpe"].to_numpy()
    lo, hi = min(v.min(), 0), max(v.max(), 0)
    pts = _pts(v, w=200, top=4, bot=52, lo=lo, hi=hi)
    z = 52 - 48 * (0 - lo) / ((hi - lo) or 1)
    ex, ey = pts[-1]
    return ("<div class='mvw'>" + _mv(f"<line class='zl' x1='0' x2='200' y1='{z:.1f}' y2='{z:.1f}'/>"
                                      f"<path class='ln s' pathLength='1' d='{_d(pts)}'/>")
            + f"<i class='mdot' style='left:{ex / 2:.1f}%;top:{ey / 56 * 100:.1f}%'></i></div>"
            + _cap(f"Rolling 36-month Sharpe, latest {num(v[-1])}"))


def _arc_pt(f: float, r: float = 80) -> tuple[float, float]:
    return 100 - r * math.cos(math.pi * f), 92 - r * math.sin(math.pi * f)


def _arc(frac: float, tick: float, tick_lbl: str, lo_lbl: str, hi_lbl: str, needle: bool) -> str:
    frac = min(max(frac, 0), 1)
    trk = "M20 92 A80 80 0 0 1 180 92"
    inner = (f"<path class='trk' d='{trk}'/><path class='val{' soft' if needle else ''}' pathLength='100' d='{trk}' "
             f"style='--o:{100 - frac * 100:.1f}'/>")
    (x1, y1), (x2, y2), (tx, ty) = _arc_pt(tick, 70), _arc_pt(tick, 90), _arc_pt(tick, 104)
    inner += (f"<line class='tk' x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}'/>"
              f"<text class='tl' x='{tx:.1f}' y='{ty + 3:.1f}' text-anchor='middle'>{tick_lbl}</text>")
    if needle:
        inner += (f"<g class='ndl' style='--a:{-90 + 180 * frac:.1f}deg'><line x1='100' y1='92' x2='100' y2='28'/>"
                  "<circle cx='100' cy='92' r='5'/></g>")
    inner += (f"<text class='tl' x='20' y='108' text-anchor='middle'>{lo_lbl}</text>"
              f"<text class='tl' x='180' y='108' text-anchor='middle'>{hi_lbl}</text>")
    return _mv(inner, "arc", "-8 -4 216 118", "xMidYMid meet")


def mini_alpha() -> str:
    t = S["alpha_t"]
    if t is None or pd.isna(t):
        return _cap("t-statistic not available for these settings")
    top = max(4.0, abs(t) + 0.5)
    return (f"<div class='tg'><i><u style='width:{min(abs(t), top) / top * 100:.1f}%'></u>"
            f"<s style='left:{2 / top * 100:.1f}%'></s></i><div><span>0</span>"
            f"<span style='left:{2 / top * 100:.1f}%'>|t| = 2</span><span>{top:.0f}</span></div></div>"
            + _cap(f"|t| = {abs(t):.2f}: {'above' if abs(t) > 2 else 'below'} the usual |t| = 2 line for luck"))


def mini_ir() -> str:
    x = S["information_ratio_regression"]
    if x is None or pd.isna(x):
        return _cap("not available for these settings")
    return _arc(x, 0.5, "0.5", "0", "1", False) + _cap("Scale 0 to 1; 0.5 and above counts as high")


def mini_beta() -> str:
    x = S["beta"]
    if x is None or pd.isna(x):
        return _cap("not available for these settings")
    return (_arc(x / 1.5, 1 / 1.5, "1.0", "0", "1.5", True)
            + _cap(f"At 1.0 it would move one for one with {B}; at {num(x)} it moves {num(x)} per 1.00 of "
                   f"{B}'s excess return"))


sec_head("The six measures of the brief", f"How the strategy compares with {BL}",
         "Each card: the measure, and a small picture of the same result. Change the benchmark in the sidebar.")
with st.container(key="bento"):
    html("<div class='grp-h'><span>Risk and return</span><span>monthly data, annualised</span></div>")
    c = st.columns([1.55, 1, 1], gap="small")
    with c[0]:
        st.metric("Average return p.a.", pct(S["ann_return"]), f"{d_ret * 100:+.1f} pp vs {B}", help=HELP["ann_return"])
        html(mini_growth())
    with c[1]:
        st.metric("Volatility p.a.", pct(S["ann_vol"]), f"{d_vol * 100:+.1f} pp vs {B}", delta_color="inverse",
                  help=HELP["ann_vol"])
        html(mini_vol())
    with c[2]:
        st.metric("Sharpe ratio", num(S["sharpe"]), f"{d_sh:+.2f} vs {B}", help=HELP["sharpe"])
        html(mini_sharpe())
    html(f"<div class='grp-h'><span>Relative to the benchmark</span><span>{BL}</span></div>")
    c = st.columns([1, 1, 1.55], gap="small")
    with c[0]:
        st.metric(f"Alpha p.a. vs {B}", pct(S["alpha_ann"]), f"t = {num(S['alpha_t'])}", delta_color="off",
                  delta_arrow="off", help=HELP["alpha_ann"])
        html(mini_alpha())
    with c[1]:
        st.metric("Information ratio (regression)", num(S["information_ratio_regression"]), help=HELP["ir"])
        html(mini_ir())
    with c[2]:
        st.metric(f"Beta vs {B}", num(S["beta"]), help=HELP["beta"])
        html(mini_beta())


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


html(f"<div class='foot-n'>Information ratio in both forms. Regression (alpha / residual volatility, the class "
     f"definition): <b>{num(S['information_ratio_regression'])}</b>, {ir_reg_line(S['information_ratio_regression'])}. "
     f"Tracking error (return above {B} / volatility of that difference): <b>{num(S['information_ratio'])}</b>, "
     f"{ir_te_line(S['information_ratio'])}. Beta is not annualised.</div>")

SRC = "Source: Yahoo Finance (adjusted close, dividends reinvested), ECB, FRED; group calculations."


def source(text: str):
    html(f"<div class='src line'>{text}</div>")


# ---------------------------------------------------------------- backtest replay (display only, fm_lean outputs)
html(replay.CSS)
sec_head("Backtest replay", "Watch the rule work, month by month",
         f"Press play, pick a crisis or drag the timeline. Each month the lights show which sleeves closed above their "
         f"{ui['sma']}-month average and are held; the others wait in euro cash. The ring shows each sleeve at its "
         f"target weight. Same backtest as every number on this page.")
try:
    html(replay.root(replay.payload(
        bt, data, ui["tickers"], core.NAMES, ui["sma"], ui["lag"], B, BL,
        dict(strategy="var(--c-s)", bench=BCOL, ochre="var(--ochre)", loss="var(--loss)",
             assets=[f"var(--a{i})" for i in range(1, 7)]))))
    st.html(replay.script(), unsafe_allow_javascript=True)
except Exception as e:  # noqa: BLE001  (the replay is optional; the page keeps working)
    st.info(f"The replay cannot be shown with these settings ({e}).", icon=":material/info:")
source(f"{SRC} Value of 10,000 EUR net of costs; lights = holdings of each month (decided {ui['lag']} month(s) before at "
       f"the month-end close). {DISCLAIMER}")


@contextmanager
def guard(view: str):
    """A failing view shows a short notice instead of a traceback; the other tabs keep working."""
    try:
        yield
    except Exception as e:  # noqa: BLE001
        st.info(f"{view} cannot be shown with these settings ({e}).", icon=":material/info:")


sec_head("In depth", "Every view of the backtest",
         "The prospectus keeps a few charts; the full set lives here, all from the same run as the numbers above.")
(t_grow, t_fall, t_roll, t_year, t_table, t_hold, t_cost, t_mc, t_method) = st.tabs(
    ["Growth", "Falls", "Risk over time", "Calendar years", "All metrics", "Holdings", "Costs", "10-year outlook",
     "Method"])
CFG = {"displayModeBar": False}
with t_grow, guard("This view"):
    chart_head("Growth of 1 EUR, net of costs",
               f"Strategy and the three benchmarks from the same start value of 1.00, {first:%b %Y} to {last:%b %Y}. "
               "The fund did not exist over this period.")
    c1, c2, _ = st.columns([1, 1.4, 2])
    log = c1.toggle("Log scale", value=True, help="Equal distances on the axis = equal percentage changes.")
    show_gross = c2.toggle("Show strategy before costs", value=False)
    w = {LBL_S: fl.wealth(net["Strategy"])}
    if show_gross:
        w[LBL_G] = fl.wealth(net["Strategy gross"])
    w.update({core.BENCH[b]: fl.wealth(net[b]) for b in ("B1", "B2", "B3")})
    st.plotly_chart(charts.cumulative(w, styles, pal, log=log), width="stretch", config=CFG)
    source(f"{SRC} All series start at exactly 1.00 on the same date. The lines end close together; the difference is "
           f"in the path, see Falls. {DISCLAIMER}")

with t_fall, guard("This view"):
    chart_head("Falls from the previous high",
               f"How far each portfolio stood below its own earlier peak, {first:%b %Y} to {last:%b %Y}. Shaded: the "
               "notebook's crisis windows.")
    dd = {LBL[k]: fl.drawdown(net[k]) for k in core.PORTS}
    bands = [(core.month_end(a) - pd.offsets.MonthEnd(1), core.month_end(b), UW_SHORT[n]) for n, a, b in core.CRISES
             if core.month_end(a) >= first and core.month_end(b) <= last]
    st.plotly_chart(charts.drawdowns(dd, styles, pal, core.CLIENT_DD_TARGET, core.CLIENT_DD_CEILING, bands),
                    width="stretch", config=CFG)
    rec = lambda k: (T.loc[k, "recovery"] or "not yet")
    st.dataframe(pd.DataFrame([{"Portfolio": LBL[k], "Worst fall": pct(T.loc[k, "max_drawdown"]),
                                "From peak": T.loc[k, "peak"], "To bottom": T.loc[k, "trough"],
                                "Back at the old high": rec(k),
                                "Months to recover": "not yet" if pd.isna(T.loc[k, "months_trough_to_recovery"])
                                else f"{T.loc[k, 'months_trough_to_recovery']:.0f}",
                                "Worst 12 months": pct(T.loc[k, "worst_12m"]), "Worst month": pct(T.loc[k, "worst_month"])}
                               for k in core.PORTS]), hide_index=True, width="stretch")
    source(f"{SRC} {DISCLAIMER}")

with t_roll, guard("This view"):
    if len(net) > 36:
        rv = core.rolling_view(bt, B)
        chart_head("Is the edge stable over time?",
                   f"Sharpe ratio of the strategy and of {B} over rolling 36-month windows, and the strategy's beta "
                   f"against {B}. The strategy's Sharpe ratio was above {B}'s in {rv['share_above']:.0%} of all windows; "
                   f"its beta stayed between {rv['beta_min']:.2f} and {rv['beta_max']:.2f}.")
        st.plotly_chart(charts.rolling_lines(rv["strategy"], rv["bench"], pal, B, PCOL[B]), width="stretch", config=CFG)
        source(f"{SRC} Past data only: each point uses the 36 months up to that month. {DISCLAIMER}")
    else:
        st.info("The rolling view needs a backtest period of more than 36 months.", icon=":material/info:")

with t_year, guard("This view"):
    years = fl.calendar_years(net[list(core.PORTS)])
    years = years.loc[[y for y in years.index if (net.index.year == y).sum() == 12]]
    if len(years):
        ahead = int((years["Strategy"] > years[B]).sum())
        chart_head("Calendar-year returns, net of costs",
                   f"Complete calendar years only. The strategy beat {B} in {ahead} of {len(years)} years; its worst "
                   f"year was {spct(years['Strategy'].min())} ({years['Strategy'].idxmin()}), {B}'s "
                   f"{spct(years[B].min())} ({years[B].idxmin()}).")
        st.plotly_chart(charts.annual_heatmap(years, [core.SHORT[k] for k in core.PORTS], pal), width="stretch",
                        config=CFG)
        source(f"{SRC} {DISCLAIMER}")
    else:
        st.info("No complete calendar year in the chosen period.", icon=":material/info:")

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
    ("final_wealth", "Value of 1 EUR at the end", num, False),
    ("max_drawdown", "Maximum drawdown", pct, False),
    ("months_trough_to_recovery", "Months from bottom back to the old high",
     lambda x: "not yet" if x is None or pd.isna(x) else f"{x:.0f}", False),
    ("worst_12m", "Worst 12 months", pct, False),
    ("tracking_error", f"Tracking error p.a. (vs {B})", pct, False),
]
with t_table, guard("The metrics table"):
    chart_head("All measures, five columns",
               f"Monthly data, {first:%b %Y} to {last:%b %Y}, in EUR. Excess returns use the euro cash rate. Relative "
               f"measures are against {BL}; a benchmark against itself gives beta 1, alpha 0 (sanity check).")
    cols = {"Strategy": "Strategy (net)", "Strategy gross": "Before costs", "B1": "B1 Same mix", "B2": "B2 60/40",
            "B3": "B3 MSCI World"}
    table = pd.DataFrame({lbl: [f(T.loc[col, k]) for k, _, f, _ in ROWS] for col, lbl in cols.items()})
    table.insert(0, "Brief", ["Required" if req else "Extra" for *_, req in ROWS])
    table.insert(0, "Measure", [lbl for _, lbl, _, _ in ROWS])
    st.dataframe(table, width="stretch", hide_index=True, height=35 * (len(ROWS) + 1) + 3,
                 column_config={"Measure": st.column_config.TextColumn(width="medium", pinned=True),
                                "Brief": st.column_config.TextColumn(width="small")})
    source(DISCLAIMER)
    d1, d2, _ = st.columns([1, 1, 1.2])
    d1.download_button("Monthly returns (CSV)", net.to_csv(), "bp_backtest_monthly_returns.csv", "text/csv",
                       width="stretch", icon=":material/download:")
    d2.download_button("Metrics (CSV)", T.to_csv(), "bp_backtest_metrics.csv", "text/csv", width="stretch",
                       icon=":material/download:")

with t_hold, guard("The holdings view"):
    held = bt["weights"].assign(CASH=1 - bt["weights"].sum(axis=1))
    chart_head(f"On average {1 - held['CASH'].mean():.0%} invested and {held['CASH'].mean():.0%} in cash",
               "Target weights at the start of each month. A sleeve moves fully to cash when its fund closes a month "
               "below its moving average, and back when it recovers.")
    st.plotly_chart(charts.weights_area(held, core.NAMES, pal), width="stretch", config=CFG)
    sw = (bt["signal"].diff().abs() > 0).sum()
    yrs_n = len(net) / 12
    st.dataframe(pd.DataFrame([{"Sleeve": f"{t} · {core.NAMES[t]}", "Target weight": f"{WTS[t]:.0%}",
                                "Months invested": f"{(bt['weights'][t] > 0).mean():.0%}",
                                "Switches a year": f"{sw[t] / yrs_n:.1f}"} for t in ui["tickers"]]),
                 hide_index=True, width="stretch")
    source(f"{SRC} {DISCLAIMER}")

with t_cost, guard("The cost view"):
    cs = costs_cached(*ARGS, data)

    def be_fmt(v, what):
        if v is None:
            return "none", f"Even at zero cost the strategy's {what} is below the benchmark's."
        if math.isinf(v):
            return "> 2000 bps", f"The strategy's {what} stays above the benchmark's at any realistic cost."
        return f"{v:.0f} bps", f"One-way cost at which the strategy's {what} falls to the benchmark's (both pay it)."

    chart_head("What trading costs take away",
               f"Turnover and cost drag at {ui['cost_bps']} bps, and the cost at which the edge over {B} disappears.")
    with st.container(key="kpis_cost"):
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Turnover p.a. (one-way)", pct(cs["turnover_pa"], 0),
                  help=f"Half of the value bought plus sold in a year, cash leg included. {B}: {pct(cs['bench_turnover_pa'], 0)}.")
        k2.metric("Cost drag p.a.", pct(cs["cost_drag_pa"], 2), help="Growth rate lost to trading costs per year.")
        t3, h3 = be_fmt(cs["breakeven_cagr"], "growth rate (CAGR)")
        t4, h4 = be_fmt(cs["breakeven_sharpe"], "Sharpe ratio")
        k3.metric(f"Breakeven on return vs {B}", t3, help=h3)
        k4.metric(f"Breakeven on Sharpe vs {B}", t4, help=h4)
    chart_head("Value of 1 EUR at the end of the sample, at different trading costs",
               f"Every portfolio pays the same cost per trade. At {ui['cost_bps']} bps the strategy grows "
               f"{'faster' if S['cagr'] > T.loc[B, 'cagr'] else 'more slowly'} than {B} ({pct(S['cagr'])} vs "
               f"{pct(T.loc[B, 'cagr'])} a year). "
               + (f"Risk-adjusted (Sharpe) it stays ahead up to {t4} per trade." if cs["breakeven_sharpe"]
                  else "Risk-adjusted (Sharpe) it is behind even before costs."))
    st.plotly_chart(charts.cost_curve(cs["grid"], ui["cost_bps"], {b: cs["breakeven"][b]["cagr"] for b in ("B1", "B2", "B3")},
                                      styles, LBL, pal), width="stretch", config=CFG)
    c1, c2 = st.columns([1, 1.35], gap="medium")
    with c1:
        chart_head("Breakeven cost against each benchmark", "One-way cost per trade at which the edge is gone.")
        st.dataframe(pd.DataFrame([{"Benchmark": core.BENCH[b], "On return (CAGR)": be_fmt(cs["breakeven"][b]["cagr"], "")[0],
                                    "On Sharpe": be_fmt(cs["breakeven"][b]["sharpe"], "")[0]} for b in ("B1", "B2", "B3")]),
                     hide_index=True, width="stretch")
    with c2:
        chart_head(f"Strategy vs {B} at four cost levels", "50 bps = the lecture's all-in retail figure.")
        ct = cs["table"]
        st.dataframe(pd.DataFrame([{"Cost (bps)": f"{c}", "CAGR": pct(r["cagr"], 2), "Sharpe": num(r["sharpe"]),
                                    "Worst fall": pct(r["max_drawdown"]), f"{B} CAGR": pct(r["benchmark_cagr"], 2),
                                    f"{B} Sharpe": num(r["benchmark_sharpe"])} for c, r in ct.iterrows()]),
                     hide_index=True, width="stretch")
    source(f"Group calculations. Benchmarks pay the same cost on their trades; B3 is one fund and never trades. {DISCLAIMER}")

with t_mc, guard("The 10-year outlook"):
    mc_slot = st.container()
    c1, c2 = st.columns([1.4, 1])
    haircut = c1.toggle("Cautious variant: halve the strategy's historical return above cash", value=False,
                        help="Published rules often work less well after publication (McLean and Pontiff 2016).")
    vs = c2.segmented_control("Compare with", ["B2", "B3"], default="B2", format_func=lambda b: core.SHORT[b],
                              key="mc_vs") or "B2"
    mc = mc_cached(*ARGS, haircut, data)
    VL = core.MC_COLS[vs]
    with mc_slot:
        chart_head(f"{mc['initial']:,.0f} EUR over the next {mc['months'] // 12} years: range of outcomes",
                   f"Each of {mc['n_sim']:,} paths draws {mc['months']} months at random from the back-tested history "
                   "(the same months for every portfolio, fixed seed, as in Lecture 5.3). It is not a forecast: it "
                   "assumes the past sample is representative and ignores taxes. The investment may lead to a "
                   "financial loss.")
    st.plotly_chart(charts.fan_chart({"Strategy": mc["bands"]["Strategy"], VL: mc["bands"][VL]},
                                     {"Strategy": LBL_S, VL: VL}, {"Strategy": pal["strategy"], VL: PCOL[vs]}, pal,
                                     "p10", "p90", mc["initial"]), width="stretch", config=CFG)
    st.dataframe(pd.DataFrame([{"Portfolio": lbl if lbl != "Strategy" else LBL_S,
                                "Unfavourable (10th pct.)": f"{sm['p10']:,.0f}",
                                "Median": f"{sm['p50']:,.0f}", "Favourable (90th pct.)": f"{sm['p90']:,.0f}",
                                "Chance of ending below start": pct(sm["prob_below_start"]),
                                "Chance of a fall > 20% on the way": pct(sm["prob_drawdown_over_20pct"])}
                               for lbl in mc["columns"] for sm in [mc["summary"][lbl]]]),
                 hide_index=True, width="stretch")
    source(f"The strategy ends ahead of {core.BENCH['B2']} in {mc['summary']['prob_first_beats_second']:.0%} of the "
           "paths. Bands: dark = middle 50% of paths, light = 10th to 90th percentile. Values in EUR, after the trading "
           f"costs you chose. {DISCLAIMER}")

with t_method, guard("The method note"):
    st.markdown(f"""
**Data.** Daily adjusted closes (dividends reinvested) from Yahoo Finance for SPY, EFA, IEF, XLU, DBC and GLD, taken on
the last trading day of each month; the euro cash rate from the ECB (EONIA to September 2019, then EUR STR); the US
overnight rate (EFFR) and EUR/USD (DEXUSEU) from FRED. US-listed funds stand in for the UCITS funds an EU investor would
buy, because their history is longer. Before their own first prices, DBC (Feb 2006) and GLD (Nov 2004) are chained to
their index (S&P GSCI, gold futures) at the fund's first price. USD returns are converted with
r_EUR = (1 + r_USD) x S(t-1) / S(t) - 1 (S = USD per EUR); the bond sleeve (IEF) is EUR-hedged: r_USD + euro cash
rate - EFFR. The equity sleeves stay unhedged (hedging them lowered the Sharpe ratio in the notebook).

**Rule.** At each month-end a sleeve is "in" if its USD price is above its simple moving average of the last
{ui['sma']} month-end prices. Holdings decided at the close of month t are held during month t+{ui['lag']}
(`signal.shift(lag) * weights`), so every decision uses only information available at the time. Target weights: SPY,
EFA, IEF and XLU 20% each, DBC and GLD 10% each; a sleeve is held at its target weight or fully in euro cash. With
"next trading day's close" the trades (and the returns of that month) use the first trading day of the following month.

**Benchmarks.** B1 = the same six sleeves at the same weights, always invested (what the trend filter adds). B2 = 60%
equity (SPY 36%, EFA 24%) and 40% IEF (the classic mix the client could buy instead). B3 = the MSCI World: the iShares
Core MSCI World UCITS ETF in EUR from Nov 2009; before that the MSCI World price index plus the ETF's measured average gap
to it. All rebalance monthly and pay the same trading cost.

**Costs.** {ui['cost_bps']} bps one-way on every euro of ETF traded back to target each month (weights drift
within the month; the cash leg is free). Breakeven: the cost at which the strategy's CAGR, or its Sharpe ratio, falls
to the benchmark's, with both paying it.

**Measures.** Simple monthly returns. Average return = mean x 12; volatility = standard deviation x sqrt(12);
Sharpe = mean excess return / its standard deviation x sqrt(12); beta = cov / var of monthly excess returns,
**not annualised**; alpha = OLS intercept x 12, with its t-statistic; information ratio in two forms: regression =
alpha / standard deviation of the residuals x sqrt(12) (class definition), and tracking error = mean of (strategy
minus benchmark) / its standard deviation x sqrt(12). Growth curves are cumprod(1 + r) with a start value of 1.00.
Crisis windows: total return from the first to the last month; bull-market windows: compound return a year.

**Same code as the notebook.** All numbers come from `fm_lean.py` version {fl.VERSION} (SHA-256
`{core.SHA[:16]}...`), the module the notebook writes with `%%writefile` and runs. Tests in the repository
check that both files are byte-identical and that these defaults reproduce the notebook's results.

**Limitations.** A backtest is not a forecast. US-listed proxies and index stand-ins before launch; no taxes and no fund
fees beyond those already in the fund prices; the 10-month rule is famous, so part of its past success may not repeat
(publication bias). In long bull markets the strategy trails the always-invested portfolios.
""")

# ---------------------------------------------------------------- important information (footer)
origin = "live download" if data["origin"] == "live" else "stored snapshot"
html(
    "<div class='ii'><div class='k'>Important information</div><div class='ii-g'><div>"
    f"<p><b>{DISCLAIMER}</b> The fund is hypothetical and did not exist over this period. Educational project, not "
    "investment advice. The investment may lead to a financial loss.</p>"
    f"<p><b>Nova SBE · 2270 Financial Modeling · Group BP:</b> {GROUP}.</p></div><div>"
    f"<p><b>Data.</b> As of {data['retrieved_at']} ({origin}), latest complete month {last_month:%b %Y}; "
    f"{dl.SOURCES}.</p>"
    f"<p><b>Version.</b> Code version {_commit()}, fm_lean {fl.VERSION} (SHA-256 {core.SHA[:12]}), the notebook's own "
    f"module. <a href='{REPO_URL}' target='_blank'>Source code on GitHub</a> · Backtest notebook: submitted with the "
    "prospectus.</p></div></div></div>")
