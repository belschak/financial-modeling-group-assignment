"""Liquid-glass layer: translucent panels over a slow aurora, edge light that follows the pointer, iOS-style controls.

Pure presentation (CSS + a small script); it changes no number. Loaded after the base factsheet styles, so these
rules win. Streamlit exposes no theme variables, so a tiny script reads the app background once in a while and sets
data-bp-theme on <html>; the light values are the fallback if the script never runs.
"""

CSS = """
<style>
  :root, .stApp {
    --serif: "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, system-ui, sans-serif;
    --g-fill: rgba(255,255,255,.62); --g-fill2: rgba(255,255,255,.40); --g-edge: rgba(255,255,255,.95);
    --g-line: rgba(20,32,56,.09); --g-spec: rgba(255,255,255,.75); --g-thumb: rgba(255,255,255,.96);
    --g-shadow: 0 1px 2px rgba(20,32,56,.05), 0 10px 30px -14px rgba(20,32,56,.22), 0 34px 70px -40px rgba(46,104,168,.35);
    --aur-a: .30; --r-xl: 26px; --r-lg: 20px; --r-md: 14px;
  }
  html[data-bp-theme="dark"], html[data-bp-theme="dark"] .stApp {
    --g-fill: rgba(255,255,255,.075); --g-fill2: rgba(255,255,255,.035); --g-edge: rgba(255,255,255,.20);
    --g-line: rgba(255,255,255,.09); --g-spec: rgba(255,255,255,.16); --g-thumb: rgba(255,255,255,.16);
    --g-shadow: 0 1px 2px rgba(0,0,0,.3), 0 14px 36px -16px rgba(0,0,0,.65), 0 40px 80px -40px rgba(46,104,168,.45);
    --aur-a: .22;
  }

  /* aurora: the light the glass refracts. Fixed behind everything, drifting very slowly */
  [data-testid="stAppViewContainer"]::before {
    content: ""; position: fixed; inset: -18%; z-index: 0; pointer-events: none; filter: blur(60px) saturate(130%);
    opacity: var(--aur-a);
    background:
      radial-gradient(38% 34% at 16% 18%, #3A7BD5 0%, transparent 70%),
      radial-gradient(30% 30% at 84% 10%, #E0A43C 0%, transparent 70%),
      radial-gradient(36% 40% at 72% 70%, #5FB3C9 0%, transparent 72%),
      radial-gradient(34% 34% at 22% 86%, #7D6BD6 0%, transparent 70%);
    animation: aurora 42s ease-in-out infinite alternate;
  }
  @keyframes aurora { 0% { transform: translate3d(0,0,0) rotate(0deg) scale(1); }
    50% { transform: translate3d(3%, -2%, 0) rotate(8deg) scale(1.06); }
    100% { transform: translate3d(-3%, 3%, 0) rotate(-6deg) scale(1.02); } }
  [data-testid="stMain"], [data-testid="stSidebar"], [data-testid="stHeader"] { position: relative; z-index: 1; }
  [data-testid="stHeader"] { background: transparent; }
  .block-container::before, .block-container::after, .rule-top { display: none !important; }

  /* type: one clean display face, sentence-case labels (no tracked caps) */
  .fund { font-weight: 650; letter-spacing: -.035em; font-size: clamp(2.1rem, 1.3rem + 2.6vw, 3.4rem); line-height: 1.02; }
  .big, .ch-t, .rp-date b, .rp-rc b, .rp-h .ch-t { letter-spacing: -.03em; font-weight: 650; }
  .big { font-size: 3.4rem; }
  .ch-t { font-size: 1.35rem; }
  .eyebrow, .k, .facts .fh, .grp-h span:first-child, .rp-k, .rp-date small, .rp-st .h, [data-testid="stSidebar"] .sb-e,
  [data-testid="stSidebar"] .sb-g {
    text-transform: none !important; letter-spacing: -.005em !important; font-weight: 550 !important; font-size: .8rem !important; }
  .eyebrow { gap: .4rem; }
  .eyebrow > span { padding: .28rem .7rem; border-radius: 99px; background: var(--g-fill2); border: 1px solid var(--g-line);
                    backdrop-filter: blur(14px) saturate(160%); -webkit-backdrop-filter: blur(14px) saturate(160%); color: var(--ink2); }
  .eyebrow > span b { color: var(--acc); }
  .st-key-kpis [data-testid="stMetricValue"] > div { font-family: var(--serif); font-weight: 600; letter-spacing: -.035em; font-size: 2.3rem; }
  [data-testid="stMetricLabel"] p { font-weight: 500; }

  /* glass surfaces */
  .facts, .hero, .rp-panel, .ii, .st-key-kpis [data-testid="stColumn"]:has([data-testid="stHorizontalBlock"]),
  [data-testid="stPlotlyChart"], [data-testid="stDataFrame"], .st-key-kpis_cost, .rp-tile, .tape {
    position: relative; isolation: isolate;
    background: linear-gradient(165deg, var(--g-fill), var(--g-fill2)) !important;
    backdrop-filter: blur(24px) saturate(180%); -webkit-backdrop-filter: blur(24px) saturate(180%);
    border: 1px solid var(--g-line) !important; border-radius: var(--r-xl);
    box-shadow: inset 0 1px 0 var(--g-edge), inset 0 -1px 0 rgba(255,255,255,.06), var(--g-shadow);
  }
  /* specular highlight that follows the pointer (--mx/--my set by script) */
  .facts::after, .hero::after, .rp-panel::after, .ii::after, .st-key-kpis [data-testid="stColumn"]:has([data-testid="stHorizontalBlock"])::after,
  .rp-tile::after, .st-key-kpis_cost::after {
    content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; z-index: 2;
    background: radial-gradient(420px circle at var(--mx, 30%) var(--my, -20%), var(--g-spec), transparent 42%);
    mix-blend-mode: soft-light; opacity: .0; transition: opacity .5s;
  }
  .facts:hover::after, .hero:hover::after, .rp-panel:hover::after, .ii:hover::after, .rp-tile:hover::after, .st-key-kpis_cost:hover::after,
  .st-key-kpis [data-testid="stColumn"]:has([data-testid="stHorizontalBlock"]):hover::after { opacity: 1; }
  /* rim light: a thin bright edge, brighter near the pointer */
  .hero::before, .rp-panel::before, .facts::before {
    content: ""; position: absolute; inset: 0; border-radius: inherit; padding: 1px; pointer-events: none; z-index: 2;
    background: radial-gradient(360px circle at var(--mx, 50%) var(--my, 0%), rgba(255,255,255,.9), rgba(255,255,255,.12) 45%, transparent 70%);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor;
    mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0); opacity: .7;
  }

  .facts { border-top: 1px solid var(--g-line) !important; padding: .9rem 1.2rem .5rem; }
  .facts dt, .facts dd { border-top-color: var(--g-line); }
  .facts dl > dt:first-of-type, .facts dl > dd:first-of-type { border-top: 0; }
  .hero { grid-template-columns: 1fr 1.25fr; border-top: 1px solid var(--g-line) !important; margin: 1.3rem 0 .7rem; }
  .hero > div { padding: 1.6rem 1.8rem 1.5rem; }
  .hero > div + div { padding: 1.6rem 1.8rem 1.5rem; border-left: 1px solid var(--g-line); }
  .dd-t { background: color-mix(in srgb, currentColor 7%, transparent); border-radius: 99px; height: .62rem; }
  .dd-t > .bar { border-radius: 99px; box-shadow: 0 0 14px -2px currentColor; }
  .tape { border-radius: 99px; margin: 1.4rem 0 0; padding: .55rem 0; border-top: 1px solid var(--g-line) !important; }
  .tape span { border-right-color: var(--g-line); }
  .badge { backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); padding: .38rem .85rem .38rem .65rem; }

  /* six measures: two glass cards with hairline dividers */
  .st-key-kpis [data-testid="stColumn"]:has([data-testid="stHorizontalBlock"]) { padding: 1rem 1.2rem .4rem; margin-top: 1.1rem; }
  .grp-h { border-bottom: 1px solid var(--g-line); margin-top: 0; padding-bottom: .55rem; }
  .grp-h span:first-child { color: currentColor; font-size: .92rem !important; font-weight: 600 !important; }
  .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { border-bottom: 0 !important; }
  .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] + [data-testid="stColumn"] {
    border-left: 1px solid var(--g-line) !important; }
  .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:hover { background: transparent; }
  .st-key-kpis_cost { padding: .2rem .9rem; }
  .st-key-kpis_cost [data-testid="stColumn"] { border-top: 0 !important; border-bottom: 0 !important; }
  .st-key-kpis_cost [data-testid="stColumn"] + [data-testid="stColumn"] { border-left: 1px solid var(--g-line) !important; }
  [data-testid="stMetricDelta"] { border-radius: 99px; }

  /* charts and tables float on glass */
  [data-testid="stPlotlyChart"] { padding: 0; border-radius: var(--r-lg); overflow: hidden; }
  [data-testid="stDataFrame"] { padding: .35rem; border-radius: var(--r-lg); overflow: hidden; }
  .src.line { border-top: 0; margin-top: .4rem; padding-top: 0; }

  /* tabs: an iOS segmented control */
  [data-testid="stTabs"] [role="tablist"] { gap: .2rem; border: 1px solid var(--g-line); border-radius: 99px; padding: .28rem;
    background: linear-gradient(165deg, var(--g-fill), var(--g-fill2)); backdrop-filter: blur(24px) saturate(180%);
    -webkit-backdrop-filter: blur(24px) saturate(180%); box-shadow: inset 0 1px 0 var(--g-edge), var(--g-shadow); width: fit-content; max-width: 100%; }
  [data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] { display: none !important; }
  [data-testid="stTabs"] button[role="tab"] { border-radius: 99px; padding: .45rem 1rem; transition: background .3s, box-shadow .3s; }
  [data-testid="stTabs"] button[role="tab"] p { text-transform: none; letter-spacing: -.005em; font-size: .86rem; font-weight: 550; }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] { background: var(--g-thumb);
    box-shadow: 0 1px 2px rgba(20,32,56,.12), 0 6px 16px -8px rgba(20,32,56,.35), inset 0 1px 0 var(--g-edge); }
  [data-testid="stTabs"] button[role="tab"][aria-selected="true"] p { color: currentColor; }

  /* sidebar: frosted */
  [data-testid="stSidebar"] { background: linear-gradient(180deg, var(--g-fill), var(--g-fill2)) !important;
    backdrop-filter: blur(30px) saturate(180%); -webkit-backdrop-filter: blur(30px) saturate(180%); border-right: 1px solid var(--g-line); }
  [data-testid="stSidebar"] .sb-t { letter-spacing: -.03em; font-weight: 650; }
  [data-testid="stSidebar"] .sb-g { border-top-color: var(--g-line); }
  [data-testid="stSidebar"] .sb-e { color: var(--acc) !important; }
  [data-testid="stBaseButton-primary"] { border-radius: 99px; box-shadow: 0 8px 20px -10px rgba(46,104,168,.9), inset 0 1px 0 rgba(255,255,255,.35); }
  [data-testid="stExpander"] details { border-radius: var(--r-md); border-color: var(--g-line); background: var(--g-fill2); }
  [data-testid="stAlert"] { border-radius: var(--r-lg); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); }

  .ii { padding: 1.2rem 1.4rem .6rem; border-top: 1px solid var(--g-line) !important; }

  @media (max-width: 640px) {
    .hero { grid-template-columns: 1fr; border-radius: var(--r-lg); }
    .hero > div, .hero > div + div { padding: 1.2rem 1.15rem; }
    .facts, .st-key-kpis [data-testid="stColumn"]:has([data-testid="stHorizontalBlock"]) { border-radius: var(--r-lg); }
    .st-key-kpis [data-testid="stMetric"] { padding: .6rem .35rem .5rem !important; }
    .st-key-kpis [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child [data-testid="stMetric"] { padding-left: 0 !important; }
    .st-key-kpis [data-testid="stMetricLabel"] p { font-size: .72rem; }
    .st-key-kpis [data-testid="stMetricDelta"] { font-size: .64rem; padding: .1rem .35rem; }
    .st-key-kpis [data-testid="stMetricDelta"] svg { width: .7rem; height: .7rem; }
    .hero > div + div { border-left: 0; border-top: 1px solid var(--g-line); }
    .big { font-size: 2.6rem; }
    .st-key-kpis [data-testid="stColumn"]:has([data-testid="stHorizontalBlock"]) { padding: .8rem .7rem .2rem; }
    .st-key-kpis [data-testid="stMetricValue"] > div { font-size: 1.6rem; }
    [data-testid="stTabs"] [role="tablist"] { width: auto; overflow-x: auto; scrollbar-width: none; }
    [data-testid="stTabs"] button[role="tab"] { padding: .4rem .75rem; flex: none; }
    .eyebrow > span:nth-child(2) { display: none; }
  }
  @media (prefers-reduced-motion: reduce) { [data-testid="stAppViewContainer"]::before { animation: none; } }
  @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    :root, .stApp { --g-fill: rgba(255,255,255,.92); --g-fill2: rgba(255,255,255,.86); }
    html[data-bp-theme="dark"], html[data-bp-theme="dark"] .stApp { --g-fill: rgba(40,44,54,.92); --g-fill2: rgba(34,38,48,.9); }
  }
</style>
"""

JS = """<script>
(function () {
  if (window.__bpGlass) return; window.__bpGlass = true;
  var root = document.documentElement;
  function theme() {
    var app = document.querySelector(".stApp"); if (!app) return;
    var m = getComputedStyle(app).backgroundColor.match(/\\d+(\\.\\d+)?/g); if (!m) return;
    var lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
    var t = lum < 0.5 ? "dark" : "light"; if (root.getAttribute("data-bp-theme") !== t) root.setAttribute("data-bp-theme", t);
  }
  theme(); setInterval(theme, 400);
  if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) return;
  var SEL = ".facts, .hero, .rp-panel, .ii, .rp-tile, .st-key-kpis_cost, .st-key-kpis [data-testid='stColumn']:has([data-testid='stHorizontalBlock'])";
  var pending = null;
  document.addEventListener("pointermove", function (e) {
    pending = e; if (pending.__q) return;
    requestAnimationFrame(function () {
      var ev = pending; if (!ev) return; pending = null;
      var t = ev.target && ev.target.closest ? ev.target.closest(SEL) : null;
      if (!t) return;
      var r = t.getBoundingClientRect();
      t.style.setProperty("--mx", (ev.clientX - r.left) + "px"); t.style.setProperty("--my", (ev.clientY - r.top) + "px");
    });
  }, { passive: true });
})();
</script>"""
