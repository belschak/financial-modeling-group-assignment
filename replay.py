"""Backtest replay: the strategy's mechanism, month by month, as one interactive panel (vanilla JS + SVG).

Display only. Every value comes from fm_lean outputs the page already computed: wealth and drawdown of the net
returns, the weights the backtest held, and the month-end prices with their moving average (the rule's own input,
`price.rolling(sma).mean()` as in fm_lean.backtest). Nothing here feeds a number of record.
"""
from __future__ import annotations

import html
import json
import re

import pandas as pd

import fm_lean as fl

# Crisis presets (month the replay stops at). Shown only if inside the chosen period.
# The notebook's crisis windows (section 7): the replay starts a little before and stops at the last month.
PRESETS = [("2007-11", "2009-02", "Financial crisis"), ("2011-05", "2011-09", "Euro crisis 2011"),
           ("2020-02", "2020-03", "Covid 2020"), ("2022-01", "2022-12", "2022 inflation shock")]


def _clean(s: pd.Series) -> list:
    return [None if pd.isna(v) else round(float(v), 4) for v in s]


def payload(bt: dict, data: dict, tickers: tuple, names: dict, sma: int, lag: int, bench: str, bench_label: str,
            colors: dict) -> dict:
    net = bt["net"]
    ws, wb = fl.wealth(net["Strategy"]), fl.wealth(net[bench])
    dds, ddb = fl.drawdown(net["Strategy"]), fl.drawdown(net[bench])
    tick = list(tickers)
    held = (bt["weights"][tick].loc[net.index] > 0).astype(int)
    target = bt["weights"][tick].max()                    # each sleeve's target weight (it is 0 or this)
    px = data["px"][tick]
    avg = px.rolling(sma).mean()
    pos = px.index.get_indexer(net.index) - lag          # decision month of each held month
    lo = max(0, int(pos.min()) - 23)
    hi = int(pos.max()) + 1
    pxs, avs = px.iloc[lo:hi], avg.iloc[lo:hi]
    dates = [f"{d:%Y-%m}" for d in ws.index]
    presets = []
    for a, b, label in PRESETS:
        if a in dates and b in dates:
            presets.append(dict(a=dates.index(a), b=dates.index(b), label=label))
    r4 = lambda s: [round(float(v), 4) for v in s]
    return dict(
        n=len(dates) - 1, dates=dates, bench=bench, benchLabel=bench_label, sma=sma, lag=lag,
        s=[round(float(v) * 10000, 1) for v in ws], b=[round(float(v) * 10000, 1) for v in wb],
        dds=r4(dds), ddb=r4(ddb), tickers=tick, names=[names[t] for t in tick],
        held=held.to_numpy().tolist(), w=[round(float(target[t]), 6) for t in tick],
        pxDates=[f"{d:%Y-%m}" for d in pxs.index], dec=[int(p - lo) for p in pos],
        px={t: _clean(pxs[t]) for t in tick}, avg={t: _clean(avs[t]) for t in tick},
        presets=presets, colors=colors, target=0.10, ceiling=0.20,
    )


def root(p: dict) -> str:
    """The panel, with this run's data as an attribute (Streamlit rewrites it on every rerun)."""
    return ("<div class='rp-root rp-panel stage-dark' aria-label='Backtest replay' data-j='"
            + html.escape(json.dumps(p, separators=(",", ":")), quote=True)
            + "'><div class='rp-wait'>Loading the replay...</div></div>")


def script() -> str:
    # Static: Streamlit runs an st.html script once, when it mounts. The sanitiser (DOMPurify) drops a script whose
    # text looks like markup, so every "<" that starts a tag inside a JS string is written as the escape \x3c
    # (comparison operators in the code are always followed by a space).
    return "<script>" + re.sub(r"<(?=[/\w!])", lambda m: "\\x3c", JS) + "</script>"


CSS = """
<style>
  .rp-root { --rpH: 340px; position: relative; margin: .8rem 0 .6rem; min-height: 520px; padding: .6rem 1.5rem 1.4rem; }
  .rp-root > * { position: relative; z-index: 3; }
  .rp-wait { font-size: .8rem; color: var(--ink3); padding: 2rem 0; }
  .rp-bar { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem 1rem; padding: .8rem 0 .9rem; border-bottom: 1px solid var(--g-line, var(--rule)); }
  .rp-play { display: inline-flex; align-items: center; gap: .5rem; font: inherit; font-size: .86rem; font-weight: 600;
             color: #fff; background: linear-gradient(180deg, #3B78BC, var(--acc)); border: 0; border-radius: 99px;
             padding: .5rem 1.05rem .5rem .8rem; cursor: pointer; box-shadow: 0 6px 18px -8px rgba(46,104,168,.8);
             transition: transform .18s cubic-bezier(.2,.7,.2,1), box-shadow .2s; }
  .rp-play:hover { transform: translateY(-1px); box-shadow: 0 10px 24px -10px rgba(46,104,168,.95); }
  .rp-play:active { transform: scale(.97); }
  .rp-play svg { width: .95rem; height: .95rem; fill: currentColor; }
  .rp-seg { display: inline-flex; gap: 2px; padding: 3px; border-radius: 99px; background: color-mix(in srgb, currentColor 6%, transparent);
             box-shadow: inset 0 1px 2px rgba(0,0,0,.06); }
  .rp-seg button, .rp-pill { font: inherit; font-size: .74rem; color: var(--ink2); background: transparent; border: 0;
             padding: .36rem .75rem; cursor: pointer; transition: background .25s, color .25s, box-shadow .25s; border-radius: 99px; }
  .rp-seg button.on { background: var(--g-thumb, #fff); color: currentColor; font-weight: 600;
             box-shadow: 0 1px 2px rgba(20,32,56,.14), 0 4px 12px -6px rgba(20,32,56,.35), inset 0 1px 0 var(--g-edge, #fff); }
  .rp-pills { display: flex; flex-wrap: wrap; gap: .4rem; }
  .rp-pill { border: 1px solid var(--g-line, var(--rule2)); border-radius: 99px; background: var(--g-fill2, transparent);
             backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); box-shadow: inset 0 1px 0 var(--g-edge, transparent); }
  .rp-pill:hover, .rp-seg button:hover { background: var(--tint); color: currentColor; }
  .rp-pill.on { border-color: color-mix(in srgb, var(--ochre) 60%, transparent); background: color-mix(in srgb, var(--ochre) 16%, transparent);
             color: currentColor; font-weight: 600; box-shadow: 0 0 0 3px color-mix(in srgb, var(--ochre) 14%, transparent), inset 0 1px 0 var(--g-edge, transparent); }
  .rp-date { margin-left: auto; text-align: right; line-height: 1; }
  .rp-date small { display: block; font-size: .62rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--ink3); margin-bottom: .25rem; }
  .rp-date b { font-family: var(--serif); font-size: 1.9rem; font-weight: 600; font-variant-numeric: tabular-nums lining-nums; letter-spacing: -.01em; }
  .rp-tl { position: relative; height: 34px; margin: .9rem 0 .2rem; cursor: pointer; touch-action: none; outline: none; }
  .rp-tl svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
  .rp-tl:focus-visible { box-shadow: 0 0 0 2px var(--acc); border-radius: 3px; }
  .rp-knob { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: currentColor; pointer-events: none; }
  .rp-knob::after { content: ""; position: absolute; left: 50%; bottom: -5px; width: 11px; height: 11px; margin-left: -5.5px;
             border-radius: 50%; background: var(--acc); box-shadow: 0 0 0 3px color-mix(in srgb, var(--acc) 25%, transparent); }
  .rp-tlx { display: flex; justify-content: space-between; font-size: .66rem; color: var(--ink3); margin-bottom: .3rem; }
  .rp-grid { display: grid; grid-template-columns: minmax(0, 1fr) 17.5rem; gap: 1.6rem; margin-top: .6rem; }
  .rp-main { position: relative; min-width: 0; }
  .rp-leg { display: flex; flex-wrap: wrap; gap: .3rem 1.2rem; font-size: .74rem; color: var(--ink2); margin-bottom: .2rem; }
  .rp-leg i { display: inline-block; width: 1.1rem; height: 0; border-top: 2.5px solid; vertical-align: middle; margin-right: .4rem; }
  .rp-g, .rp-u { display: block; width: 100%; overflow: visible; }
  .rp-g { height: var(--rpH); }
  .rp-u { height: 92px; }
  .rp-k { font-size: .64rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--ink3); }
  .rp-main .rp-k { margin: .6rem 0 .1rem; }
  .rp-ax text { font-size: 10.5px; fill: currentColor; fill-opacity: .55; font-variant-numeric: tabular-nums; }
  .rp-ax line { stroke: currentColor; stroke-opacity: .12; stroke-dasharray: 2 3; }
  .rp-band rect { fill: var(--ochre); fill-opacity: .07; }
  .rp-band text { font-size: 9.5px; fill: var(--ochre); font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
  .rp-ln { fill: none; stroke-linejoin: round; stroke-linecap: round; }
  .rp-cur { stroke: currentColor; stroke-opacity: .35; stroke-width: 1; }
  .rp-lbl { font-size: 11.5px; font-weight: 700; font-variant-numeric: tabular-nums; paint-order: stroke; stroke-width: 4px;
             stroke-linejoin: round; }
  .rp-ping { transform-box: fill-box; transform-origin: center; animation: rpPing 1.8s cubic-bezier(0,0,.2,1) infinite; }
  @keyframes rpPing { 0% { transform: scale(1); opacity: .5; } 80%, 100% { transform: scale(3.4); opacity: 0; } }
  .rp-call { position: absolute; left: 3.4rem; top: 2rem; max-width: 19rem; padding: .7rem .85rem; border-radius: 18px;
             background: color-mix(in srgb, var(--rpBg, #fff) 72%, transparent); border: 1px solid var(--g-line, var(--rule2));
             backdrop-filter: blur(20px) saturate(180%); -webkit-backdrop-filter: blur(20px) saturate(180%); font-size: .8rem; line-height: 1.45;
             box-shadow: 0 14px 34px -18px rgba(0,0,0,.45); pointer-events: none;
             opacity: 0; transform: translateY(6px) scale(.98); transition: opacity .35s, transform .45s cubic-bezier(.2,.7,.2,1); }
  .rp-call.on { opacity: 1; transform: none; }
  .rp-call.right { left: auto; right: 4.8rem; }
  .rp-call b { display: block; font-size: .8rem; font-weight: 650; color: var(--ochre); margin-bottom: .2rem; }
  .rp-side { min-width: 0; }
  .rp-ring { position: relative; width: 12.5rem; height: 12.5rem; margin: .2rem auto .6rem; }
  .rp-ring svg { width: 100%; height: 100%; overflow: visible; }
  .rp-ring path { transition: fill-opacity .45s, stroke-opacity .45s, transform .5s cubic-bezier(.2,.7,.2,1); transform-origin: 100px 100px; }
  .rp-ring path.off { fill-opacity: .0; stroke-opacity: .55; transform: scale(.93); }
  .rp-ring path.on { fill-opacity: .92; stroke-opacity: 0; }
  .rp-ring text { font-size: 10px; font-weight: 700; letter-spacing: .04em; pointer-events: none; transition: fill .45s, fill-opacity .45s; }
  .rp-ring text.on { fill: #fff; } .rp-ring text.off { fill: currentColor; fill-opacity: .45; }
  .rp-rc { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; }
  .rp-rc b { font-family: var(--serif); font-size: 2.3rem; font-weight: 600; line-height: 1; font-variant-numeric: tabular-nums lining-nums; }
  .rp-rc span { font-size: .8rem; color: var(--ink3); margin-top: .25rem; }
  .rp-st { display: grid; grid-template-columns: 1fr auto auto; gap: 0 .8rem; font-size: .78rem; margin: 0; }
  .rp-st > * { padding: .4rem 0; border-top: 1px solid var(--g-line, var(--rule)); }
  .rp-st .h { font-size: .62rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--ink3); border-top: 0; }
  .rp-st .l { color: var(--ink3); }
  .rp-st .v { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .rp-st .neg { color: var(--loss); }
  .rp-st .warn { color: var(--loss); }
  .rp-feed { margin-top: .9rem; }
  .rp-feed ol { list-style: none; margin: .3rem 0 0; padding: 0; font-size: .76rem; }
  .rp-feed li { margin: 0 !important; display: grid; grid-template-columns: 4.3rem 1fr auto; gap: .5rem; padding: .34rem 0; border-top: 1px solid var(--g-line, var(--rule)); color: var(--ink2); }
  .rp-feed li.new { animation: rpIn .6s cubic-bezier(.2,.7,.2,1); }
  .rp-feed li em { font-style: normal; font-weight: 600; }
  .rp-feed li em.in { color: var(--ok); } .rp-feed li em.out { color: var(--ochre); }
  .rp-feed .none { color: var(--ink3); border-top: 1px solid var(--rule); padding: .3rem 0; }
  @keyframes rpIn { from { opacity: 0; transform: translateX(-8px); background: color-mix(in srgb, var(--acc) 14%, transparent); } }
  .rp-board { display: grid; grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr)); gap: .7rem; margin-top: 1.3rem; }
  .rp-tile { position: relative; border-radius: 20px !important; padding: .8rem .9rem .75rem; overflow: hidden;
             transition: border-color .4s, background .4s, transform .25s cubic-bezier(.2,.7,.2,1), box-shadow .25s; }
  .rp-tile:hover { transform: translateY(-2px); box-shadow: 0 12px 28px -20px rgba(0,0,0,.5); }
  .rp-tile::before { content: ""; position: absolute; left: 0; right: 0; top: 0; height: 60%; pointer-events: none; z-index: -1; opacity: .5;
             transition: background .5s; }
  .rp-tile.in::before { background: radial-gradient(80% 100% at 85% 0%, color-mix(in srgb, var(--ok) 22%, transparent), transparent 70%); }
  .rp-tile.out::before { background: radial-gradient(80% 100% at 85% 0%, color-mix(in srgb, var(--ochre) 20%, transparent), transparent 70%); }
  .rp-tile.flip { animation: rpFlip .7s cubic-bezier(.2,.7,.2,1); }
  @keyframes rpFlip { 0% { transform: scale(1); } 30% { transform: scale(1.035); box-shadow: 0 0 0 4px color-mix(in srgb, var(--acc) 30%, transparent); } 100% { transform: scale(1); } }
  .rp-th > div { min-width: 0; }
  .rp-th { display: flex; align-items: center; justify-content: space-between; gap: .4rem; }
  .rp-th b { font-size: .9rem; letter-spacing: .02em; }
  .rp-th small { display: block; font-size: .66rem; color: var(--ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .rp-lt { white-space: nowrap; flex: none; display: inline-flex; align-items: center; gap: .38rem; font-size: .72rem; font-weight: 600;
           padding: .2rem .55rem .2rem .45rem; border-radius: 99px; background: color-mix(in srgb, currentColor 9%, transparent); }
  .rp-lt i { width: .55rem; height: .55rem; border-radius: 50%; display: inline-block; }
  .rp-tile.in .rp-lt { color: var(--ok); } .rp-tile.in .rp-lt i { background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 22%, transparent), 0 0 10px var(--ok); }
  .rp-tile.out .rp-lt { color: var(--ochre); } .rp-tile.out .rp-lt i { background: var(--ochre); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ochre) 22%, transparent); }
  .rp-tile svg { display: block; width: 100%; height: 46px; margin: .45rem 0 .3rem; overflow: visible; }
  .rp-tile .px { fill: none; stroke-width: 1.7; vector-effect: non-scaling-stroke; }
  .rp-tile .av { fill: none; stroke: currentColor; stroke-opacity: .45; stroke-width: 1.2; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
  .rp-tile .gap { stroke: none; }
  .rp-tile p { margin: 0; font-size: .7rem; color: var(--ink3); line-height: 1.35; }
  .rp-tile p b { color: currentColor; font-weight: 600; }
  @media (max-width: 900px) { .rp-grid { grid-template-columns: 1fr; } .rp-side { display: grid; grid-template-columns: 11rem 1fr; gap: 1rem; align-items: start; }
    .rp-ring { width: 11rem; height: 11rem; margin: 0; } .rp-feed { grid-column: 1 / -1; } }
  @media (max-width: 640px) { .rp-root { --rpH: 220px; padding: .4rem .9rem 1rem; } .rp-date { margin-left: 0; text-align: left; order: -1; width: 100%; }
    .rp-date b { font-size: 1.6rem; } .rp-tlx { flex-wrap: wrap; } .rp-tlx span:nth-child(2) { order: 3; width: 100%; margin-top: .2rem; } .rp-side { grid-template-columns: 1fr; } .rp-ring { margin: 0 auto; }
    .rp-board { grid-template-columns: repeat(2, minmax(0, 1fr)); } .rp-call, .rp-call.right { left: 2.6rem; right: .3rem; top: 1.4rem; max-width: none; } }
  @media (prefers-reduced-motion: reduce) { .rp-ping, .rp-tile.flip, .rp-feed li.new { animation: none !important; }
    .rp-ring path, .rp-call, .rp-tile { transition: none !important; } }
</style>
"""

JS = r"""
(function () {
  var D = null, J = null, N = 0, C = {}, NT = 0, EV = [];
  var G = window.__bpRP || (window.__bpRP = { tok: 0, auto: false });
  if (G.stop) G.stop();
  var tok = ++G.tok, alive = function () { return G.tok === tok; };
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  function lab(ym) { return MON[+ym.slice(5, 7) - 1] + " " + ym.slice(0, 4); }
  function eur(v) { return Math.round(v).toLocaleString("en-US"); }
  function pc(v, d) { d = d === undefined ? 1 : d; var x = v * 100; if (Math.abs(x) < 0.5 * Math.pow(10, -d)) x = 0; return x.toFixed(d) + "%"; }
  var NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, parent) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
  // signal changes (held index k -> replay point k+1)
  // The data ride on the root element (data-j, rewritten by Streamlit on every rerun); this script runs once and
  // rebuilds whenever they change, so the replay can never show an earlier run's numbers.
  function setData(j) {
    J = j; D = JSON.parse(j); N = D.n; C = D.colors; NT = D.tickers.length; EV = [];
    var tw = D.w.reduce(function (a, b) { return a + b; }, 0) || 1; D.w = D.w.map(function (x) { return x / tw; });
    for (var k = 1; k < D.held.length; k++) for (var q = 0; q < NT; q++)
      if (D.held[k][q] !== D.held[k - 1][q]) EV.push({ i: k + 1, j: q, on: D.held[k][q] === 1 });
  }
  function heldAt(i) { return D.held[Math.max(i, 1) - 1]; }
  function share(h) { var s = 0; for (var q = 0; q < NT; q++) s += h[q] * D.w[q]; return s; }   // weight invested
  var S = { i: N, playing: false, speed: 1, acc: 0, last: 0, raf: 0, target: null, preset: null, callT: 0, root: null };
  var R = {}, io = null, ro = null, lastW = -1, lastEvTop = -1, prevHeld = null;

  function TPL() { return "<div class='rp-bar'>" +
      "<button class='rp-play' data-r='play' type='button'><svg viewBox='0 0 16 16' data-r='ico'></svg><span data-r='pt'>Play</span></button>" +
      "<div class='rp-seg' role='group' aria-label='Speed'><button type='button' data-s='0.5'>0.5x</button><button type='button' data-s='1' class='on'>1x</button><button type='button' data-s='2'>2x</button><button type='button' data-s='4'>4x</button></div>" +
      "<div class='rp-pills' data-r='pills'></div>" +
      "<div class='rp-date'><small>Month shown</small><b data-r='date'></b></div>" +
    "</div>" +
    "<div class='rp-tl' data-r='tl' role='slider' tabindex='0' aria-label='Month of the replay'><svg data-r='tls'></svg><div class='rp-knob' data-r='knob'></div></div>" +
    "<div class='rp-tlx'><span data-r='t0'></span><span>Bars: share of the portfolio invested each month (rest in euro cash). Drag, or use the arrow keys.</span><span data-r='t1'></span></div>" +
    "<div class='rp-grid'><div class='rp-main'>" +
      "<div class='rp-leg'><span><i style='border-color:" + C.strategy + "'></i>Strategy (net)</span><span><i style='border-color:" + C.bench + "'></i>" + D.benchLabel + "</span><span>Value of 10,000 EUR</span></div>" +
      "<svg class='rp-g' data-r='g'></svg>" +
      "<div class='rp-k'>Fall from previous high</div><svg class='rp-u' data-r='u'></svg>" +
      "<div class='rp-call' data-r='call'></div>" +
    "</div><div class='rp-side'>" +
      "<div class='rp-ring'><svg viewBox='0 0 200 200' data-r='ring'></svg><div class='rp-rc'><b data-r='inv'></b><span>invested</span></div></div>" +
      "<div><div class='rp-st' data-r='st'></div></div>" +
      "<div class='rp-feed'><div class='rp-k'>Latest signal changes</div><ol data-r='feed'></ol></div>" +
    "</div></div>" +
    "<div class='rp-board' data-r='board'></div>"; }

  function build(root) {
    pause(true); S.i = N; S.target = null; S.preset = null; S.geo = null;
    S.root = root; root.__bp = tok; root.innerHTML = TPL(); lastW = -1; lastEvTop = -1; prevHeld = null;
    root.querySelectorAll("[data-r]").forEach(function (e) { R[e.getAttribute("data-r")] = e; });
    // presets
    D.presets.forEach(function (p, k) {
      var b = document.createElement("button"); b.type = "button"; b.className = "rp-pill"; b.textContent = p.label;
      b.onclick = function () { jump(k); }; R.pills.appendChild(b);
    });
    var full = document.createElement("button"); full.type = "button"; full.className = "rp-pill"; full.textContent = "Full period";
    full.onclick = function () { clearPreset(); S.i = 0; S.target = null; play(true); }; R.pills.appendChild(full);
    R.play.onclick = function () { S.playing ? pause() : play(); };
    root.querySelectorAll(".rp-seg button").forEach(function (b) {
      b.onclick = function () { S.speed = +b.getAttribute("data-s");
        root.querySelectorAll(".rp-seg button").forEach(function (x) { x.classList.toggle("on", x === b); }); };
    });
    R.t0.textContent = lab(D.dates[0]); R.t1.textContent = lab(D.dates[N]);
    // timeline: drag / click / keys
    var drag = false;
    function fromX(e, box) { var r = box.getBoundingClientRect(); return Math.round(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * N); }
    R.tl.addEventListener("pointerdown", function (e) { drag = true; R.tl.setPointerCapture(e.pointerId); pause(); clearPreset(); set(fromX(e, R.tl)); });
    R.tl.addEventListener("pointermove", function (e) { if (drag) set(fromX(e, R.tl)); });
    R.tl.addEventListener("pointerup", function () { drag = false; });
    R.tl.addEventListener("keydown", function (e) {
      var m = { ArrowLeft: -1, ArrowRight: 1, ArrowDown: -1, ArrowUp: 1, PageDown: -12, PageUp: 12 }[e.key];
      if (m) { pause(); set(S.i + m); e.preventDefault(); }
      else if (e.key === "Home") { pause(); set(0); e.preventDefault(); }
      else if (e.key === "End") { pause(); set(N); e.preventDefault(); }
      else if (e.key === " ") { S.playing ? pause() : play(); e.preventDefault(); }
    });
    // hover on the chart scrubs while paused
    function chartScrub(svg) {
      svg.addEventListener("pointermove", function (e) {
        if (S.playing || !S.geo) return;
        var r = svg.getBoundingClientRect(), x = e.clientX - r.left, g = S.geo;
        set(Math.round(Math.min(1, Math.max(0, (x - g.l) / (g.w))) * N), true);
      });
      svg.addEventListener("pointerleave", function () { if (!S.playing && S.hoverFrom !== undefined) { set(S.hoverFrom); S.hoverFrom = undefined; } });
    }
    chartScrub(R.g); chartScrub(R.u);
    buildBoard(); buildRing();
    if (ro) ro.disconnect();
    if (window.ResizeObserver) { ro = new ResizeObserver(function () { if (alive()) draw(); }); ro.observe(root); }
    icon(); draw();
    if (io) io.disconnect();
    if (!G.auto && !reduce && window.IntersectionObserver) {
      io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting && !G.auto && alive()) { G.auto = true; io.disconnect(); S.i = 0; play(true); } });
      }, { threshold: 0.35 });
      io.observe(root);
    }
  }

  function icon() {
    R.ico.innerHTML = S.playing ? "<rect x='3' y='2' width='3.6' height='12' rx='1'/><rect x='9.4' y='2' width='3.6' height='12' rx='1'/>"
                                : "<path d='M4 2.2v11.6c0 .6.7 1 1.2.6l8.4-5.8c.4-.3.4-.9 0-1.2L5.2 1.6C4.7 1.2 4 1.6 4 2.2z'/>";
    R.pt.textContent = S.playing ? "Pause" : (S.i >= N ? "Replay" : "Play");
    R.play.setAttribute("aria-label", R.pt.textContent);
  }
  function play(keep) {
    if (!keep && S.i >= N) S.i = 0;
    if (!keep) clearPreset();
    S.playing = true; S.acc = 0; S.last = performance.now(); icon();
    cancelAnimationFrame(S.raf); S.raf = requestAnimationFrame(tick);
  }
  function pause(quiet) { S.playing = false; cancelAnimationFrame(S.raf); if (!quiet) icon(); }
  function tick(now) {
    if (!alive() || !S.playing) return;
    var dt = Math.min(0.1, (now - S.last) / 1000); S.last = now;
    var rate = S.target !== null ? 26 : 16 * S.speed;     // months per second
    if (reduce) rate = 1e9;
    S.acc += dt * rate;
    var step = Math.floor(S.acc);
    if (step > 0) {
      S.acc -= step;
      var to = Math.min(N, S.i + step);
      if (S.target !== null && to >= S.target) { to = S.target; }
      set(to);
      if (S.target !== null && S.i >= S.target) { var p = S.preset; S.target = null; pause(); showCall(p, true); return; }
      if (S.i >= N) { pause(); return; }
    }
    S.raf = requestAnimationFrame(tick);
  }
  function jump(k) {
    var p = D.presets[k]; clearPreset(); S.preset = k;
    S.root.querySelectorAll(".rp-pill")[k].classList.add("on");
    S.i = Math.max(0, p.a - 10); S.target = p.b; set(S.i); play(true);
  }
  function clearPreset() {
    S.preset = null; if (S.root) S.root.querySelectorAll(".rp-pill.on").forEach(function (b) { b.classList.remove("on"); });
    hideCall();
  }
  function set(i, hover) {
    i = Math.max(0, Math.min(N, i | 0));
    if (hover) { if (S.hoverFrom === undefined) S.hoverFrom = S.i; } else S.hoverFrom = undefined;
    S.i = i; update(); icon();
    if (S.playing) D.presets.forEach(function (p, k) { if (i === p.b && S.target === null) showCall(k, false); });
  }

  // ---------- call-out (data of the month shown)
  function showCall(k, stay) {
    var p = D.presets[k], i = p.b, h = heldAt(i), cash = 1 - share(h);
    var worstS = Math.min.apply(null, D.dds.slice(0, i + 1)), worstB = Math.min.apply(null, D.ddb.slice(0, i + 1));
    R.call.innerHTML = "<b>" + p.label + " &middot; " + lab(D.dates[i]) + "</b>" + Math.round(cash * 100) + "% of the portfolio waiting in euro cash. Fall from the previous high: strategy <strong>" + pc(D.dds[i]) + "</strong>, " +
      D.bench + " <strong>" + pc(D.ddb[i]) + "</strong>.";
    var right = S.geo && S.geo.X(i) < S.geo.l + S.geo.w * 0.55;
    R.call.classList.toggle("right", !!right);
    R.call.classList.add("on"); clearTimeout(S.callT);
    if (!stay) S.callT = setTimeout(hideCall, 2600);
  }
  function hideCall() { if (R.call) R.call.classList.remove("on"); clearTimeout(S.callT); }

  // ---------- geometry
  function nice(lo, hi, n) {
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / n))), f = span / n / step;
    step *= f > 5 ? 10 : f > 2 ? 5 : f > 1 ? 2 : 1;
    var out = []; for (var v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10)); return out;
  }
  function layout() {
    var W = R.g.clientWidth, H = R.g.clientHeight, small = W < 520;
    if (W < 60 || H < 60) { lastW = -1; return false; }
    var l = small ? 40 : 52, r = small ? 58 : 74, t = 12, b = 22, w = W - l - r, h = H - t - b;
    var all = D.s.concat(D.b), lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var ylo = Math.min(lo * 0.96, 10000 * 0.96), yhi = hi * 1.03;
    var X = function (k) { return l + w * k / N; }, Y = function (v) { return t + h * (1 - (v - ylo) / (yhi - ylo)); };
    S.geo = { l: l, w: w, X: X, Y: Y };
    var g = R.g; g.innerHTML = "";
    var ax = el("g", { "class": "rp-ax" }, g), bands = el("g", { "class": "rp-band" }, g);
    D.presets.forEach(function (p) {
      el("rect", { x: X(p.a), y: t, width: Math.max(2, X(p.b) - X(p.a)), height: h }, bands);
    });
    nice(ylo, yhi, small ? 3 : 5).forEach(function (v) {
      el("line", { x1: l, x2: l + w, y1: Y(v), y2: Y(v) }, ax);
      var tx = el("text", { x: l - 8, y: Y(v) + 3.5, "text-anchor": "end" }, ax); tx.textContent = v >= 1000 ? (v / 1000) + "k" : v;
    });
    var y0 = +D.dates[0].slice(0, 4), y1 = +D.dates[N].slice(0, 4), every = Math.max(1, Math.ceil((y1 - y0) / (w / 64)));
    D.dates.forEach(function (d, k) {
      var yr = +d.slice(0, 4);
      if (d.slice(5) === "01" && (yr - y0) % every === 0) { var tx = el("text", { x: X(k), y: H - 4, "text-anchor": "middle" }, ax); tx.textContent = yr; }
    });
    el("line", { x1: l, x2: l + w, y1: Y(10000), y2: Y(10000), style: "stroke-dasharray:1 3;stroke-opacity:.4" }, ax);
    var dfs = el("defs", {}, g), gid = "rpGrad" + tok;
    var lg = el("linearGradient", { id: gid, x1: 0, x2: 0, y1: 0, y2: 1 }, dfs);
    el("stop", { offset: "0", "stop-color": C.strategy, "stop-opacity": ".26" }, lg);
    el("stop", { offset: "1", "stop-color": C.strategy, "stop-opacity": "0" }, lg);
    R.area = el("path", { fill: "url(#" + gid + ")" }, g);
    R.lb = el("path", { "class": "rp-ln", stroke: C.bench, "stroke-width": 2, "stroke-opacity": .9 }, g);
    R.ls = el("path", { "class": "rp-ln rp-glow", stroke: C.strategy, "stroke-width": 2.8 }, g);
    R.cur = el("line", { "class": "rp-cur", y1: t, y2: t + h }, g);
    R.pb = el("circle", { r: 4, fill: C.bench }, g);
    R.pp = el("circle", { r: 5, fill: C.strategy, "class": "rp-ping" }, g);
    R.ps = el("circle", { r: 5, fill: C.strategy, stroke: "var(--rpBg)", "stroke-width": 2 }, g);
    R.ts = el("text", { "class": "rp-lbl", fill: C.strategy, stroke: "var(--rpBg)" }, g);
    R.tb = el("text", { "class": "rp-lbl", fill: C.bench, stroke: "var(--rpBg)" }, g);
    // underwater chart
    var u = R.u, UH = u.clientHeight, ut = 4, uh = UH - ut - 4;
    var dmin = Math.min(Math.min.apply(null, D.dds), Math.min.apply(null, D.ddb), -D.ceiling) * 1.08;
    var UY = function (v) { return ut + uh * (v / dmin); };
    S.geo.UY = UY; u.innerHTML = "";
    var uax = el("g", { "class": "rp-ax" }, u);
    [0, -D.target, -D.ceiling].forEach(function (v, q) {
      el("line", { x1: l, x2: l + w, y1: UY(v), y2: UY(v), style: q === 1 ? "stroke:var(--ok);stroke-opacity:.9;stroke-dasharray:4 3" : q === 2 ? "stroke:var(--loss);stroke-opacity:.9;stroke-dasharray:none" : "" }, uax);
      var tx = el("text", { x: l - 8, y: UY(v) + 3.5, "text-anchor": "end" }, uax); tx.textContent = pc(v, 0);
    });
    if (!small) {
      var tt = el("text", { x: l + w + 6, y: UY(-D.target) + 3.5, style: "fill:var(--ok);fill-opacity:1" }, uax); tt.textContent = "target";
      var tc = el("text", { x: l + w + 6, y: UY(-D.ceiling) + 3.5, style: "fill:var(--loss);fill-opacity:1" }, uax); tc.textContent = "ceiling";
    }
    R.ua = el("path", { fill: C.loss, "fill-opacity": .22 }, u);
    R.ub = el("path", { "class": "rp-ln", stroke: C.bench, "stroke-width": 1.4 }, u);
    R.us = el("path", { "class": "rp-ln", stroke: C.loss, "stroke-width": 1.8 }, u);
    R.uc = el("line", { "class": "rp-cur", y1: ut, y2: ut + uh }, u);
    // timeline bars
    var tl = R.tls, TW = R.tl.clientWidth, TH = R.tl.clientHeight; tl.innerHTML = "";
    var cid = "rpClip" + tok, cdef = el("defs", {}, tl), cp = el("clipPath", { id: cid }, cdef);
    R.clip = el("rect", { x: 0, y: 0, height: TH, width: TW }, cp);
    var base = el("g", { fill: "currentColor", "fill-opacity": .14 }, tl), past = el("g", { fill: C.strategy, "clip-path": "url(#" + cid + ")" }, tl);
    var bw = TW / (N + 1);
    for (var k2 = 0; k2 <= N; k2++) {
      var hh = share(heldAt(k2)), bh = Math.max(2, (TH - 4) * hh);
      var at = { x: k2 * bw, y: TH - bh, width: Math.max(0.6, bw - (bw > 3 ? 1 : 0.25)), height: bh };
      el("rect", at, base); el("rect", at, past);
    }
    D.presets.forEach(function (p) { el("rect", { x: p.a * bw, y: TH + 3, width: Math.max(3, (p.b - p.a + 1) * bw), height: 2.5, fill: C.ochre }, tl); });
    S.tlw = TW; S.bw = bw; return true;
  }
  function path(arr, i, X, Y) { var s = ""; for (var k = 0; k <= i; k++) s += (k ? "L" : "M") + X(k).toFixed(1) + " " + Y(arr[k]).toFixed(1); return s; }

  function draw() {
    if (!S.root || !R.g) return;
    var bg = getComputedStyle(S.root.closest(".stApp") || document.body).backgroundColor;
    var sb = getComputedStyle(S.root).getPropertyValue("--stage-bg").trim();
    S.root.style.setProperty("--rpBg", sb || (bg && bg !== "rgba(0, 0, 0, 0)" ? bg : "#fff"));
    if (R.g.clientWidth !== lastW) { lastW = R.g.clientWidth; if (!layout()) return; }
    update();
  }

  function update() {
    if (!S.geo) return;
    var i = S.i, g = S.geo, X = g.X, Y = g.Y;
    R.date.textContent = lab(D.dates[i]);
    R.tl.setAttribute("aria-valuemin", 0); R.tl.setAttribute("aria-valuemax", N); R.tl.setAttribute("aria-valuenow", i);
    R.tl.setAttribute("aria-valuetext", lab(D.dates[i]));
    R.knob.style.left = ((i + 0.5) * S.bw / S.tlw * 100) + "%";
    R.clip.setAttribute("width", (i + 1) * S.bw);
    var ps = path(D.s, i, X, Y);
    R.ls.setAttribute("d", ps); R.lb.setAttribute("d", path(D.b, i, X, Y));
    var ybase = R.g.clientHeight - 22;
    R.area.setAttribute("d", ps + "L" + X(i).toFixed(1) + " " + ybase + "L" + X(0) + " " + ybase + "Z");
    var cx = X(i), sy = Y(D.s[i]), by = Y(D.b[i]);
    ["x1", "x2"].forEach(function (a) { R.cur.setAttribute(a, cx); R.uc.setAttribute(a, cx); });
    R.ps.setAttribute("cx", cx); R.ps.setAttribute("cy", sy); R.pp.setAttribute("cx", cx); R.pp.setAttribute("cy", sy);
    R.pb.setAttribute("cx", cx); R.pb.setAttribute("cy", by);
    var ly = [sy, by]; if (Math.abs(ly[0] - ly[1]) < 15) { var mid = (ly[0] + ly[1]) / 2, up = ly[0] <= ly[1] ? -1 : 1; ly[0] = mid + up * 7.5; ly[1] = mid - up * 7.5; }
    var tx = cx + 9, anchor = "start";
    if (cx > g.l + g.w - 4 + 60) { tx = cx - 9; anchor = "end"; }
    R.ts.setAttribute("x", tx); R.ts.setAttribute("y", ly[0] + 4); R.ts.setAttribute("text-anchor", anchor); R.ts.textContent = eur(D.s[i]);
    R.tb.setAttribute("x", tx); R.tb.setAttribute("y", ly[1] + 4); R.tb.setAttribute("text-anchor", anchor); R.tb.textContent = eur(D.b[i]);
    var UY = g.UY, us = path(D.dds, i, X, UY);
    R.us.setAttribute("d", us); R.ub.setAttribute("d", path(D.ddb, i, X, UY));
    R.ua.setAttribute("d", us + "L" + X(i).toFixed(1) + " " + UY(0) + "L" + X(0) + " " + UY(0) + "Z");
    // ring + board
    var h = heldAt(i);
    R.inv.textContent = Math.round(share(h) * 100) + "%";
    R.slices.forEach(function (p, j) { p.setAttribute("class", h[j] ? "on" : "off"); R.rl[j].setAttribute("class", h[j] ? "on" : "off"); });
    var dec = D.dec[Math.max(i, 1) - 1];
    R.tiles.forEach(function (T, j) {
      var on = !!h[j], was = prevHeld ? !!prevHeld[j] : on;
      T.root.className = "rp-tile " + (on ? "in" : "out") + (on !== was && S.playing && !reduce ? " flip" : "");
      if (on !== was && S.playing && !reduce) { (function (r) { setTimeout(function () { r.classList.remove("flip"); }, 720); })(T.root); }
      T.st.textContent = on ? "Invested" : "In cash";
      var tk = D.tickers[j], px = D.px[tk], av = D.avg[tk], a = Math.max(0, dec - 23), pp = "", aa = "";
      while (a < dec && px[a] === null) a++;
      var vals = []; for (var q = a; q <= dec; q++) { if (px[q] !== null) vals.push(px[q]); if (av[q] !== null) vals.push(av[q]); }
      var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), sp = (hi - lo) || 1;
      var xx = function (q) { return (q - a) / Math.max(1, dec - a) * 200; }, yy = function (v) { return 44 - 42 * (v - lo) / sp; };
      for (var q2 = a; q2 <= dec; q2++) { if (px[q2] === null) continue; pp += (pp ? "L" : "M") + xx(q2).toFixed(1) + " " + yy(px[q2]).toFixed(1);
        if (av[q2] !== null) aa += (aa ? "L" : "M") + xx(q2).toFixed(1) + " " + yy(av[q2]).toFixed(1); }
      T.px.setAttribute("d", pp); T.px.setAttribute("stroke", on ? "var(--ok)" : "var(--ochre)"); T.av.setAttribute("d", aa);
      var rel = px[dec] / av[dec] - 1;
      T.p.innerHTML = "Price <b>" + pc(Math.abs(rel)) + (rel >= 0 ? " above" : " below") + "</b> its " + D.sma + "-month average at the " + lab(D.pxDates[dec]) + " close";
    });
    prevHeld = h.slice();
    // stats
    var worstS = 0, worstB = 0; for (var k = 0; k <= i; k++) { if (D.dds[k] < worstS) worstS = D.dds[k]; if (D.ddb[k] < worstB) worstB = D.ddb[k]; }
    function cls(v) { return v < -D.ceiling ? " warn" : v < -0.0005 ? " neg" : ""; }
    R.st.innerHTML = "<span class='h'></span><span class='h v'>Strategy</span><span class='h v'>" + D.bench + "</span>" +
      "<span class='l'>Value of 10,000 EUR</span><span class='v'>" + eur(D.s[i]) + "</span><span class='v'>" + eur(D.b[i]) + "</span>" +
      "<span class='l'>Fall from high now</span><span class='v" + cls(D.dds[i]) + "'>" + pc(D.dds[i]) + "</span><span class='v" + cls(D.ddb[i]) + "'>" + pc(D.ddb[i]) + "</span>" +
      "<span class='l'>Worst fall so far</span><span class='v" + cls(worstS) + "'>" + pc(worstS) + "</span><span class='v" + cls(worstB) + "'>" + pc(worstB) + "</span>" +
      "<span class='l'>Months replayed</span><span class='v'>" + i + "</span><span class='v'>of " + N + "</span>";
    // feed
    var shown = EV.filter(function (e) { return e.i <= i; }).slice(-4).reverse();
    var top = shown.length ? shown[0].i * 100 + shown[0].j : -1;
    R.feed.innerHTML = shown.length ? shown.map(function (e, q) {
      return "<li" + (q === 0 && top !== lastEvTop && S.playing ? " class='new'" : "") + "><span>" + lab(D.dates[e.i]) + "</span><span>" +
        D.tickers[e.j] + " &middot; " + D.names[e.j] + "</span><em class='" + (e.on ? "in" : "out") + "'>" + (e.on ? "back in" : "to cash") + "</em></li>";
    }).join("") : "<li class='none'>No change yet: every slice as at the start.</li>";
    lastEvTop = top;
  }

  function buildRing() {
    R.rl = []; var svg = R.ring, cx = 100, cy = 100, ro2 = 96, ri = 66, gap = NT > 1 ? 0.045 : 0; R.slices = [];
    for (var j = 0, cum = 0; j < NT; j++) {
      var a0 = -Math.PI / 2 + cum * 2 * Math.PI + gap; cum += D.w[j];
      var a1 = -Math.PI / 2 + cum * 2 * Math.PI - gap, big = a1 - a0 > Math.PI ? 1 : 0;
      var p = function (r, a) { return (cx + r * Math.cos(a)).toFixed(2) + " " + (cy + r * Math.sin(a)).toFixed(2); };
      var d = "M" + p(ro2, a0) + "A" + ro2 + " " + ro2 + " 0 " + big + " 1 " + p(ro2, a1) + "L" + p(ri, a1) + "A" + ri + " " + ri + " 0 " + big + " 0 " + p(ri, a0) + "Z";
      var s = el("path", { d: d, fill: C.assets[j % C.assets.length], stroke: "currentColor", "stroke-width": 1, "stroke-dasharray": "3 3" }, svg);
      var tt = el("title", {}, s); tt.textContent = D.tickers[j] + " · " + D.names[j];
      var am = (a0 + a1) / 2, lt = el("text", { x: cx + 81 * Math.cos(am), y: cy + 81 * Math.sin(am) + 3.5, "text-anchor": "middle",
        "class": "on" }, svg);
      lt.textContent = D.tickers[j]; R.slices.push(s); R.rl = R.rl || []; R.rl.push(lt);
    }
  }
  function buildBoard() {
    R.board.innerHTML = ""; R.tiles = [];
    D.tickers.forEach(function (tk, j) {
      var t = document.createElement("div"); t.className = "rp-tile in";
      t.innerHTML = "<div class='rp-th'><div><b>" + tk + "</b><small>" + D.names[j] + "</small></div><span class='rp-lt'><i></i><span></span></span></div>" +
        "<svg viewBox='0 0 200 46' preserveAspectRatio='none'><path class='av'></path><path class='px'></path></svg><p></p>";
      R.board.appendChild(t);
      R.tiles.push({ root: t, st: t.querySelector(".rp-lt span"), px: t.querySelector(".px"), av: t.querySelector(".av"), p: t.querySelector("p") });
    });
  }

  var wd = setInterval(function () {
    if (!alive()) { clearInterval(wd); return; }
    var r = document.querySelector(".rp-root"), j = r && r.getAttribute("data-j");
    if (!r || !j) return;
    if (j !== J) { setData(j); build(r); }
    else if (r.__bp !== tok || !r.querySelector(".rp-bar")) build(r);
  }, 250);
  G.stop = function () { clearInterval(wd); cancelAnimationFrame(S.raf); S.playing = false; if (io) io.disconnect(); if (ro) ro.disconnect(); clearTimeout(S.callT); };
  var r0 = document.querySelector(".rp-root"), j0 = r0 && r0.getAttribute("data-j"); if (j0) { setData(j0); build(r0); }
})();
"""
