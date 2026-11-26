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

  /* masthead: one quiet context line, a big headline, the lede, a single status line, a spec strip */
  .mh-ctx { font-size: .92rem; font-weight: 500; color: var(--ink3); letter-spacing: -.01em; margin-top: 1.6rem;
            animation: rise .7s cubic-bezier(.2,.7,.2,1) both; }
  .mh-ctx i { font-style: normal; margin: 0 .55rem; opacity: .45; }
  .fund { font-size: clamp(2.5rem, 1.2rem + 3.8vw, 4.4rem); line-height: .98; letter-spacing: -.048em; font-weight: 680;
          margin: .55rem 0 1.1rem; max-width: 15ch;
          background: linear-gradient(180deg, currentColor 35%, color-mix(in srgb, currentColor 62%, transparent));
          -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; padding-bottom: .06em; }
  .lede { font-size: 1.16rem; line-height: 1.55; max-width: 42rem; letter-spacing: -.01em; }
  .mh-meta { display: flex; flex-wrap: wrap; gap: .5rem 1.6rem; font-size: .86rem; color: var(--ink2); margin: 1.2rem 0 0;
             animation: rise .8s cubic-bezier(.2,.7,.2,1) .2s both; }
  .mh-meta .st { display: inline-flex; align-items: center; gap: .5rem; }
  .mh-meta .st > i { position: relative; width: .45rem; height: .45rem; border-radius: 50%; display: inline-block; background: var(--ok); }
  .mh-meta .st.cu > i, .mh-meta .st.snap > i, .mh-meta .st.snap > i::after { background: var(--ochre); }
  .spec { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 2.4rem 0 .6rem; border-top: 1px solid var(--g-line);
          animation: rise .9s cubic-bezier(.2,.7,.2,1) .28s both; }
  .spec > div { padding: .95rem 1.2rem .95rem 0; border-bottom: 1px solid var(--g-line); min-width: 0; }
  .spec > div:not(:nth-child(4n+1)) { padding-left: 1.2rem; border-left: 1px solid var(--g-line); }
  .spec span { display: block; font-size: .78rem; color: var(--ink3); margin-bottom: .3rem; }
  .spec b { display: block; font-weight: 560; font-size: .98rem; letter-spacing: -.012em; }
  @media (prefers-reduced-motion: reduce) { .mh-ctx, .mh-meta, .spec { animation: none !important; } }

  @media (max-width: 640px) {
    .mh-ctx { margin-top: .6rem; font-size: .84rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .fund { font-size: 2.45rem; }
    .lede { font-size: 1.02rem; }
    .spec { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 1.6rem; }
    .spec > div, .spec > div:not(:nth-child(4n+1)) { padding: .8rem .9rem .8rem 0; border-left: 0; }
    .spec > div:nth-child(2n) { padding-left: .9rem; border-left: 1px solid var(--g-line); }
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
  var SEL = ".facts, .hero, .rp-panel, .ii, .rp-tile, .st-key-kpis_cost, .st-key-bento [data-testid='stColumn']";
  var pending = null, lastStage = null;
  document.addEventListener("pointermove", function (e) {
    pending = e; if (pending.__q) return;
    requestAnimationFrame(function () {
      var ev = pending; if (!ev) return; pending = null;
      // stage parallax: the orb and the floating asset chips lean towards the pointer (-1..1)
      var stg = ev.target && ev.target.closest ? ev.target.closest(".stage") : null;
      if (lastStage && lastStage !== stg) { lastStage.style.setProperty("--px", 0); lastStage.style.setProperty("--py", 0); }
      lastStage = stg;
      if (stg) { var b = stg.getBoundingClientRect();
        stg.style.setProperty("--px", (((ev.clientX - b.left) / b.width) * 2 - 1).toFixed(3));
        stg.style.setProperty("--py", (((ev.clientY - b.top) / b.height) * 2 - 1).toFixed(3)); }
      var t = ev.target && ev.target.closest ? ev.target.closest(SEL) : null;
      if (!t) return;
      var r = t.getBoundingClientRect();
      t.style.setProperty("--mx", (ev.clientX - r.left) + "px"); t.style.setProperty("--my", (ev.clientY - r.top) + "px");
    });
  }, { passive: true });
})();
</script>"""

# Round 3, "obsidian stage": the masthead and the replay sit on a dark, lit stage in both themes (Apple-style dark
# sections on a light page); the six measures become a bento of glass cards, each with a small picture of the same
# fm_lean output. Scroll reveals use the CSS view timeline (no script; browsers without it simply show everything).
STAGE = """
<style>
  .stApp { --c-s: #2E68A8; --c-b1: #C08A2B; --c-b2: #8A94A6; }
  html[data-bp-theme="dark"] .stApp { --c-s: #5AA9FF; --c-b1: #F5B544; --c-b2: #AEB8CA; }
  .stage, .rp-root.stage-dark {
    --stage-bg: #070A12; color: #E9EEF6;
    --g-fill: rgba(255,255,255,.07); --g-fill2: rgba(255,255,255,.025); --g-edge: rgba(255,255,255,.16);
    --g-line: rgba(255,255,255,.10); --g-spec: rgba(255,255,255,.18); --g-thumb: rgba(255,255,255,.15);
    --acc: #5AA9FF; --ok: #3EE6A4; --ochre: #F5B544; --loss: #FF6B6E; --c-s: #5AA9FF; --c-b1: #F5B544; --c-b2: #AEB8CA;
  }
  .stage, .rp-root.stage-dark {
    position: relative; isolation: isolate; overflow: hidden; border-radius: 34px !important;
    background:
      radial-gradient(70% 60% at 88% 0%, rgba(58,123,213,.34), transparent 62%),
      radial-gradient(55% 55% at 0% 100%, rgba(245,181,68,.13), transparent 62%),
      linear-gradient(165deg, #0D1526 0%, #070A12 55%, #05070C 100%) !important;
    border: 1px solid rgba(255,255,255,.08) !important;
    box-shadow: 0 50px 100px -50px rgba(7,20,48,.85), 0 24px 44px -32px rgba(0,0,0,.7), inset 0 1px 0 rgba(255,255,255,.14) !important;
  }
  .stage { --sx: clamp(1.2rem, .8rem + 2.6vw, 3.4rem); margin: .4rem 0 1.1rem;
    padding: clamp(1.4rem, 1rem + 2.6vw, 3.4rem) var(--sx) clamp(1.2rem, 1rem + 1.4vw, 2.2rem);
    animation: rise .9s cubic-bezier(.2,.7,.2,1) both; }
  .stage > * { position: relative; }
  /* the real growth line, glowing, full-bleed in its own lane; it draws itself in (clip reveal: exact at any width) */
  @keyframes wipe { from { clip-path: inset(-20% 100% -20% 0); } to { clip-path: inset(-20% -2% -20% 0); } }
  .stg-bd { height: 190px; margin: 1.4rem calc(var(--sx) * -1) 0; pointer-events: none; z-index: 0;
    -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 9%); mask-image: linear-gradient(90deg, transparent 0, #000 9%); }
  .stg-bdi { position: relative; height: 100%; margin-right: var(--sx); }
  .stg-bd svg { display: block; width: 100%; height: 100%; overflow: visible; }
  .stg-bd path { fill: none; vector-effect: non-scaling-stroke; stroke-linejoin: round; stroke-linecap: round; }
  .stg-bd path.s { stroke-width: 2.6; filter: drop-shadow(0 0 5px rgba(90,169,255,.95)) drop-shadow(0 0 22px rgba(90,169,255,.55));
    animation: wipe 2.8s cubic-bezier(.45,.05,.2,1) .35s both; }
  .stg-bd path.b { stroke-width: 1.5; stroke-opacity: .75; animation: wipe 2.8s cubic-bezier(.45,.05,.2,1) .5s both; }
  .stg-bd path.a { stroke: none; animation: wipe 2.8s cubic-bezier(.45,.05,.2,1) .35s both; }
  .stage .spec { position: relative; z-index: 1; }
  .stg-end { position: absolute; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%; background: #5AA9FF;
    box-shadow: 0 0 0 4px rgba(90,169,255,.22), 0 0 26px 8px rgba(90,169,255,.65); animation: fadein .5s 3s both; }
  .stg-end::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: #5AA9FF;
    animation: ping 2.4s cubic-bezier(0,0,.2,1) 3.2s infinite; }
  .stg-grid { position: absolute !important; inset: 0; z-index: -2; pointer-events: none; opacity: .6;
    background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px);
    background-size: 56px 56px; animation: stgPan 50s linear infinite;
    -webkit-mask-image: radial-gradient(75% 70% at 72% 45%, #000, transparent 78%); mask-image: radial-gradient(75% 70% at 72% 45%, #000, transparent 78%); }
  @keyframes stgPan { to { background-position: 56px 56px, 56px 56px; } }
  .stg-orb { position: absolute !important; width: 40rem; height: 40rem; right: -10rem; top: -18rem; z-index: -1; border-radius: 50%;
    pointer-events: none; filter: blur(80px); opacity: .9;
    background: conic-gradient(from 0deg, rgba(90,169,255,0), rgba(90,169,255,.42), rgba(62,230,164,.16), rgba(245,181,68,.28), rgba(90,169,255,0));
    translate: calc(var(--px, 0) * 34px) calc(var(--py, 0) * 34px); transition: translate .9s cubic-bezier(.2,.7,.2,1);
    animation: stgSpin 26s linear infinite; }
  @keyframes stgSpin { to { rotate: 360deg; } }

  .stg-in { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 2rem 3.2rem; align-items: end; }
  .stage .mh-ctx { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: 0; color: rgba(233,238,246,.7); font-size: .8rem; }
  .stage .mh-ctx span { padding: .3rem .75rem; border-radius: 99px; border: 1px solid var(--g-line);
    background: linear-gradient(160deg, rgba(255,255,255,.09), rgba(255,255,255,.02)); box-shadow: inset 0 1px 0 rgba(255,255,255,.1); }
  .stage .mh-ctx span:first-child { color: #CFE6FF; border-color: rgba(90,169,255,.35); background: rgba(90,169,255,.12); }
  .stage .fund { font-size: clamp(2.5rem, 1.1rem + 3.6vw, 4.7rem); max-width: 13ch; margin: .9rem 0 1rem;
    background: linear-gradient(180deg, #FFFFFF 30%, rgba(214,226,244,.62)); -webkit-background-clip: text; background-clip: text; }
  .stage .lede { color: rgba(233,238,246,.74); font-size: 1.08rem; max-width: 34rem; }
  .stage .mh-meta { color: rgba(233,238,246,.8); }
  .stage .mh-meta .st.ok > i { box-shadow: 0 0 10px var(--ok); }
  .stage .k { color: rgba(233,238,246,.6) !important; }
  .stg-r { padding-bottom: .3rem; min-width: 0; }
  .mega { font-family: var(--serif); font-size: clamp(3.9rem, 1.4rem + 6.6vw, 8.4rem); font-weight: 700; letter-spacing: -.065em;
    line-height: .9; margin: .45rem 0 .7rem -.05em; white-space: nowrap; font-variant-numeric: tabular-nums lining-nums; }
  .mega .cu-n { background: linear-gradient(100deg, #FFFFFF 0%, #D4E8FF 26%, #5AA9FF 46%, #FFFFFF 60%, #F7D594 80%, #FFFFFF 100%);
    background-size: 280% 100%; -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
    animation: shimmer 10s ease-in-out infinite alternate; filter: drop-shadow(0 0 34px rgba(90,169,255,.38)); padding-right: .04em; }
  .mega small { font-size: .19em; letter-spacing: 0; margin-left: .55rem; color: rgba(233,238,246,.55); font-weight: 600; }
  @keyframes shimmer { from { background-position: 0% 0; } to { background-position: 100% 0; } }
  .stage .cmp { color: rgba(233,238,246,.74); font-size: .96rem; }
  .stage .cmp i { display: inline-block; width: 1rem; height: 3px; border-radius: 2px; vertical-align: middle; margin-right: .55rem; }
  .stage .hint { color: rgba(233,238,246,.5); max-width: 30rem; }
  .chips-k { margin-top: 1.3rem; }
  .chips { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .55rem; }
  .chip { display: inline-flex; align-items: center; gap: .45rem; padding: .42rem .7rem .42rem .6rem; border-radius: 14px; font-size: .78rem;
    background: linear-gradient(160deg, rgba(255,255,255,.11), rgba(255,255,255,.03)); border: 1px solid rgba(255,255,255,.12);
    backdrop-filter: blur(14px) saturate(160%); -webkit-backdrop-filter: blur(14px) saturate(160%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.16), 0 12px 26px -16px rgba(0,0,0,.9);
    translate: calc(var(--px, 0) * (5px + var(--d) * 3px)) calc(var(--py, 0) * (4px + var(--d) * 2px));
    transition: translate .7s cubic-bezier(.2,.7,.2,1), border-color .3s;
    animation: bob 6s ease-in-out infinite; animation-delay: calc(var(--d) * -1.2s); }
  .chip:hover { border-color: rgba(255,255,255,.3); }
  @keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
  .chip i { width: .5rem; height: .5rem; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px rgba(62,230,164,.18), 0 0 12px var(--ok); }
  .chip.out i { background: var(--ochre); box-shadow: 0 0 0 3px rgba(245,181,68,.18); }
  .chip b { font-weight: 650; letter-spacing: .02em; }
  .chip small { color: rgba(233,238,246,.55); font-size: .72rem; }
  .chip em { font-style: normal; font-size: .68rem; font-weight: 600; padding: .08rem .45rem; border-radius: 99px; background: rgba(62,230,164,.14); color: #86F2C6; }
  .chip.out em { background: rgba(245,181,68,.15); color: #F8CB7A; }
  .stage .spec { margin: -3.2rem 0 0; border: 1px solid var(--g-line); border-radius: 20px; overflow: hidden;
    background: linear-gradient(160deg, rgba(255,255,255,.06), rgba(255,255,255,.015));
    backdrop-filter: blur(18px) saturate(150%); -webkit-backdrop-filter: blur(18px) saturate(150%); box-shadow: inset 0 1px 0 rgba(255,255,255,.1); }
  .stage .spec > div, .stage .spec > div:not(:nth-child(4n+1)) { padding: .9rem 1.15rem; }
  .stage .spec > div:nth-last-child(-n+4) { border-bottom: 0; }
  .stage .spec span { color: rgba(233,238,246,.5); }

  /* drawdown: the client's key number, big */
  .ddc .ddn { display: flex; flex-wrap: wrap; gap: .6rem 2.4rem; margin-top: .7rem; }
  .ddc .ddn b { display: block; font-family: var(--serif); font-size: clamp(2.6rem, 1.6rem + 2.6vw, 3.9rem); font-weight: 700;
    letter-spacing: -.055em; line-height: 1; font-variant-numeric: tabular-nums lining-nums; }
  .ddc .ddn small { display: block; font-size: .8rem; color: var(--ink3); margin-top: .35rem; }
  .ddc .dd { margin-top: .35rem; }

  /* the six measures: a bento of glass cards */
  .st-key-bento .grp-h { border: 0 !important; margin: 1.5rem .2rem .15rem; padding: 0; }
  .st-key-bento .grp-h span + span { color: var(--ink3); }
  .st-key-bento [data-testid="stHorizontalBlock"] { gap: .9rem; }
  .st-key-bento [data-testid="stColumn"] { position: relative; isolation: isolate; overflow: hidden; border-radius: 26px;
    padding: 1.15rem 1.3rem 1.05rem; background: linear-gradient(165deg, var(--g-fill), var(--g-fill2));
    backdrop-filter: blur(24px) saturate(180%); -webkit-backdrop-filter: blur(24px) saturate(180%); border: 1px solid var(--g-line);
    box-shadow: inset 0 1px 0 var(--g-edge), var(--g-shadow); transition: translate .35s cubic-bezier(.2,.7,.2,1), box-shadow .35s; }
  .st-key-bento [data-testid="stColumn"]::before { content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none;
    background: radial-gradient(70% 60% at 100% 0%, color-mix(in srgb, var(--c-s) 16%, transparent), transparent 70%); }
  .st-key-bento [data-testid="stColumn"]::after { content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
    background: radial-gradient(380px circle at var(--mx, 50%) var(--my, -30%), var(--g-spec), transparent 45%); mix-blend-mode: soft-light;
    opacity: 0; transition: opacity .4s; }
  .st-key-bento [data-testid="stColumn"]:hover { translate: 0 -3px; box-shadow: inset 0 1px 0 var(--g-edge), var(--g-shadow),
    0 26px 50px -28px color-mix(in srgb, var(--c-s) 70%, transparent); }
  .st-key-bento [data-testid="stColumn"]:hover::after { opacity: 1; }
  .st-key-bento [data-testid="stMetricLabel"] p { font-size: .84rem; color: var(--ink2); }
  .st-key-bento [data-testid="stMetricValue"] > div { font-family: var(--serif); font-size: 2.7rem; font-weight: 680; letter-spacing: -.055em; line-height: 1.05; }
  .st-key-bento [data-testid="stColumn"]:has(.mv.g) [data-testid="stMetricValue"] > div,
  .st-key-bento [data-testid="stColumn"]:has(.ndl) [data-testid="stMetricValue"] > div { font-size: 3.5rem; }
  .mv { display: block; width: 100%; height: 64px; overflow: visible; margin-top: .45rem; }
  .mv.g { height: 92px; }
  .mv .ln { fill: none; vector-effect: non-scaling-stroke; stroke-linecap: round; stroke-linejoin: round;
    animation: wipe 1.9s cubic-bezier(.45,.05,.2,1) .25s both; }
  .mv .ln.s { stroke: var(--c-s); stroke-width: 2.4; filter: drop-shadow(0 0 4px color-mix(in srgb, var(--c-s) 75%, transparent)); }
  .mv .ln.b { stroke-width: 1.4; stroke-opacity: .85; animation-delay: .4s; }
  .mv .ar { fill: color-mix(in srgb, var(--c-s) 15%, transparent); animation: wipe 1.9s cubic-bezier(.45,.05,.2,1) .25s both; }
  .mv .zl { stroke: currentColor; stroke-opacity: .28; stroke-dasharray: 2 3; vector-effect: non-scaling-stroke; }
  .mvw { position: relative; margin-top: .45rem; } .mvw .mv { margin-top: 0; }
  .mdot { position: absolute; width: 8px; height: 8px; margin: -4px 0 0 -4px; border-radius: 50%; background: var(--c-s);
    box-shadow: 0 0 10px var(--c-s); animation: fadein .4s 2s both; }
  .mv.arc { height: 104px; }
  .mv .trk, .mv .val { fill: none; stroke-width: 13; stroke-linecap: round; }
  .mv .trk { stroke: currentColor; stroke-opacity: .09; }
  .mv .val { stroke: var(--c-s); stroke-dasharray: 100; stroke-dashoffset: var(--o); animation: arcIn 1.7s cubic-bezier(.2,.7,.2,1) .2s both;
    filter: drop-shadow(0 0 6px color-mix(in srgb, var(--c-s) 60%, transparent)); }
  .mv .val.soft { opacity: .28; filter: none; }
  @keyframes arcIn { from { stroke-dashoffset: 100; } }
  .mv .tk { stroke: currentColor; stroke-opacity: .55; stroke-width: 2; }
  .mv .tl { font-size: 11px; fill: currentColor; fill-opacity: .55; font-weight: 600; }
  .mv .ndl { transform-box: view-box; transform-origin: 100px 92px; transform: rotate(var(--a)); animation: ndl 1.8s cubic-bezier(.3,1.35,.5,1) .25s both; }
  .mv .ndl line { stroke: currentColor; stroke-width: 3; stroke-linecap: round; } .mv .ndl circle { fill: var(--c-s); }
  @keyframes ndl { from { transform: rotate(-90deg); } }
  .mbars { display: grid; gap: .6rem; margin-top: 1rem; }
  .mbars > div { display: grid; grid-template-columns: 4.4rem minmax(0, 1fr) 3rem; align-items: center; gap: .6rem; font-size: .78rem; }
  .mbars span { color: var(--ink3); } .mbars b { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
  .mbars i { display: block; height: .6rem; border-radius: 99px; background: color-mix(in srgb, currentColor 8%, transparent); overflow: hidden; }
  .mbars u { display: block; height: 100%; border-radius: 99px; transform-origin: left; animation: grow 1.3s cubic-bezier(.2,.7,.2,1) .25s both; }
  .tg { margin-top: 1.1rem; }
  .tg > i { position: relative; display: block; height: .62rem; border-radius: 99px; background: color-mix(in srgb, currentColor 8%, transparent); }
  .tg u { position: absolute; inset: 0 auto 0 0; border-radius: 99px; transform-origin: left;
    background: linear-gradient(90deg, color-mix(in srgb, var(--c-s) 35%, transparent), var(--c-s)); box-shadow: 0 0 14px -2px var(--c-s);
    animation: grow 1.4s cubic-bezier(.2,.7,.2,1) .25s both; }
  .tg s { position: absolute; top: -.32rem; bottom: -.32rem; width: 0; border-left: 2px dashed color-mix(in srgb, currentColor 55%, transparent); }
  .tg > div { position: relative; height: 1.1rem; font-size: .68rem; color: var(--ink3); margin-top: .35rem; }
  .tg > div span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
  .tg > div span:first-child { left: 0; transform: none; } .tg > div span:last-child { right: 0; transform: none; }
  .mcap { font-size: .74rem; color: var(--ink3); margin-top: .5rem; line-height: 1.4; }

  /* replay: the cinematic dark stage */
  .rp-root.stage-dark { padding: .8rem 1.8rem 1.6rem; }
  .rp-root.stage-dark .rp-glow { filter: drop-shadow(0 0 5px rgba(90,169,255,.9)) drop-shadow(0 0 16px rgba(90,169,255,.45)); }
  .rp-root.stage-dark .rp-date b { font-size: 2.4rem; background: linear-gradient(90deg, #fff, #9CCBFF); -webkit-background-clip: text;
    background-clip: text; -webkit-text-fill-color: transparent; }
  .rp-root.stage-dark .rp-play { background: linear-gradient(180deg, #6DB5FF, #2F7FE0); box-shadow: 0 0 0 1px rgba(255,255,255,.12), 0 10px 30px -8px rgba(90,169,255,.9); }
  .rp-root.stage-dark .rp-tile { background: linear-gradient(165deg, rgba(255,255,255,.07), rgba(255,255,255,.02)) !important; }
  .rp-root.stage-dark .rp-tile.in { box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 0 0 1px rgba(62,230,164,.12), 0 18px 40px -26px rgba(62,230,164,.55); }

  /* scroll reveals: CSS view timeline only (nothing hidden where unsupported) */
  @keyframes reveal { from { opacity: 0; transform: translateY(42px) scale(.97); } }
  @supports (animation-timeline: view()) {
    @media (prefers-reduced-motion: no-preference) {
      .st-key-bento [data-testid="stColumn"], .ddc, [data-testid="stPlotlyChart"], .rp-root.stage-dark, .ii {
        animation: reveal linear both; animation-timeline: view(); animation-range: entry 0% entry 60%; }
    }
  }

  @media (max-width: 900px) { .stg-in { grid-template-columns: 1fr; } .stage .fund { max-width: 16ch; } }
  @media (max-width: 640px) {
    .stage { border-radius: 26px !important; padding: 1.35rem 1.15rem 1.15rem; }
    .stage .mh-ctx { font-size: .72rem; white-space: normal; overflow: visible; }
    .stage .fund { font-size: 2.45rem; }
    .stage .lede { font-size: 1rem; }
    .mega { font-size: 4.3rem; }
    .stg-bd { height: 120px; margin-top: 1rem; }
    .stage .spec { margin-top: -2rem; }
    .stg-orb { width: 26rem; height: 26rem; right: -12rem; top: -12rem; }
    .chip { font-size: .74rem; padding: .36rem .6rem .36rem .5rem; } .chip small { display: none; }
    .stage .spec { margin-top: 1.6rem; }
    .stage .spec > div, .stage .spec > div:not(:nth-child(4n+1)), .stage .spec > div:nth-child(2n) { padding: .75rem .85rem; }
    .stage .spec > div:nth-last-child(-n+4) { border-bottom: 1px solid var(--g-line); }
    .stage .spec > div:nth-last-child(-n+2) { border-bottom: 0; }
    .st-key-bento [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: .7rem !important; }
    .st-key-bento [data-testid="stColumn"] { min-width: calc(50% - .35rem) !important; width: calc(50% - .35rem) !important;
      flex: 1 1 calc(50% - .35rem) !important; padding: .95rem .95rem .85rem; border-radius: 22px; }
    .st-key-bento [data-testid="stColumn"]:has(.mv.g), .st-key-bento [data-testid="stColumn"]:has(.ndl) {
      min-width: 100% !important; width: 100% !important; flex-basis: 100% !important; }
    .st-key-bento [data-testid="stMetricValue"] > div { font-size: 2.1rem; }
    .st-key-bento [data-testid="stColumn"]:has(.mv.g) [data-testid="stMetricValue"] > div,
    .st-key-bento [data-testid="stColumn"]:has(.ndl) [data-testid="stMetricValue"] > div { font-size: 2.8rem; }
    .st-key-bento [data-testid="stMetricLabel"] p { font-size: .76rem; }
    .mbars > div { grid-template-columns: 3.4rem minmax(0, 1fr) 2.6rem; gap: .4rem; font-size: .72rem; }
    .mv.arc { height: 84px; }
    .ddc .ddn { gap: .5rem 1.6rem; }
    .rp-root.stage-dark { padding: .5rem .95rem 1.1rem; border-radius: 26px !important; }
  }
  @media (prefers-reduced-motion: reduce) {
    .stage, .stg-bd path, .stg-end, .stg-end::after, .stg-grid, .stg-orb, .mega .cu-n, .chip, .mv .ln, .mv .ar, .mdot, .mv .val, .mv .ndl,
    .mbars u, .tg u { animation: none !important; }
    .stg-bd path, .mv .ln { clip-path: none; }
  }
</style>
"""
