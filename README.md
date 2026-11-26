# BP Trend-Guarded Multi-Asset: interactive backtest

Streamlit app for the group assignment of **2270 Financial Modeling, Nova SBE (Fall 2026), Group BP**:
Tim Fischer, David Konrad Belschak, Tom Nico H Croe, Lennart Schmülling, Fridolin Treibig, Bastian Volkery.

**Live app:** https://financial-modeling-group-bp.streamlit.app
**Notebook:** `FM-Group-BP-Backtest.ipynb`, submitted on Moodle together with the investor prospectus

![Overview: assumptions in the sidebar, key facts, growth of 10,000 EUR, largest fall against the client's target, the six required measures](docs/screenshot-overview.png)

On a phone the same page stacks into one column ([phone layout](docs/screenshot-mobile.png)).

## What it does

The strategy holds five broad asset classes (US equity, developed ex-US equity, US Treasuries 7-10y, US REITs,
broad commodities) in equal slices of 20%. At each month-end an asset stays invested only while its price is above
its 10-month moving average (Faber 2007); otherwise its slice moves to euro cash. All returns are in EUR.

In the sidebar you change the assumptions and every number recalculates:

| Assumption | Default (= prospectus Table 1) | Range |
|---|---|---|
| Moving-average window | 10 months | 6 to 12 |
| Signal delay | 1 month | 1 or 2 |
| Trade at | month-end close | month-end close or the next trading day's close |
| Trading cost (one-way) | 10 bps (fund level) | 0 to 100 bps (50 = retail stress case) |
| Backtest period | Jan 2007 to Dec 2025 | Jan 2007 to the last complete month |
| Assets | all five | any two or more |
| Benchmark for alpha, beta, IR | B1 equal weight 1/n | B1 or B2 (60/40) |

With the defaults the page shows the badge "Defaults: matches prospectus Table 1". It shows the six measures the
brief requires (average return, volatility, Sharpe ratio, alpha with its t-statistic, information ratio and beta,
beta not annualised) against the chosen benchmark. The information ratio appears in both forms: the regression form
(alpha / residual volatility, the class definition) on the card, and the tracking-error form in the line below. The
headline compares the largest fall with the client's target of at most 10% (20% hard ceiling) and gives the
next-trading-day figures beside the month-end base case.

Tabs: growth of 1 EUR for the strategy and both benchmarks from the same start value of 1.00, drawdowns, rolling
36-month Sharpe ratio and beta, calendar-year returns; a metrics table with CSV download; holdings over time;
turnover, cost drag and breakeven costs; a 10-year Monte Carlo for 10,000 EUR (Lecture 5.3, with a cautious variant
that halves the historical return above cash); and the method.

## Same calculations as the notebook

All numbers come from **`fm_lean.py` version lean-1.1, SHA-256
`5ec1d9a4c10c34db84e8bc8349b94c09227da7606d7762abda94fea80d4eedf2`**, the module the submitted notebook writes with
`%%writefile` and runs, copied here byte for byte. The app never re-implements a calculation: `core.py` only turns
the sidebar into calls of `fm_lean.backtest`, `table`, `at_cost`, `breakeven`, `rolling`, `calendar_years` and
`monte_carlo`. The footer and the Method tab print the module version, its SHA-256 and the git commit of the running
code.

Tests (`pytest -q`, also in GitHub Actions on the pinned `requirements.txt`):

- `test_module_identity.py`: `fm_lean.py` has the expected SHA-256, the same as `results.json`; on the group's machine
  also identical to the notebook's module and to the `%%writefile` cells inside the .ipynb, and `data/` equal to the
  notebook's current output.
- `test_app_core.py`: the defaults reproduce the notebook's `results.json` (Table 1 for all four portfolios, the
  next-day row, B2-relative measures, turnover, cost drag, breakevens, Monte Carlo); series start at 1.00; a
  benchmark against itself gives beta 1 and alpha 0; every setting runs.
- `test_app_ui.py`: the real page, driven headlessly: cards equal Table 1, both information ratios shown, client
  target and ceiling equal `results.json`, settings change the numbers, reset works, no traceback at extreme settings,
  snapshot fallback when the download fails.

To check against the notebook folder, put its path in `tests/local_notebook_dir.txt` (git-ignored) or set
`FM_NOTEBOOK_DIR`.

## Data

Live, through `fm_lean.load_data` (no API keys): Yahoo Finance adjusted closes via `yfinance`, the ECB Data Portal
for the euro overnight rate (EONIA to September 2019, then EUR STR), FRED for the US overnight rate (EFFR) and
EUR/USD. Cached for 12 hours.

Yahoo sometimes throttles shared cloud servers. The app then shows "Live data unavailable, showing snapshot as of
...", never a traceback, and uses `data/snapshot_inputs.csv`: the monthly inputs the notebook run itself exported, so
offline defaults equal the notebook exactly. `data/results.json` is that run's results file, used only by the tests.
Refresh both with `python tools/make_snapshot.py --from-notebook <notebook output folder>`. "Data source" in the
sidebar selects the snapshot explicitly.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Python 3.11 to 3.13. Dependencies: streamlit, pandas (2.2 or later), numpy, requests, yfinance, plotly.
Tests: `pip install pytest` then `pytest -q`.

## Deployment

The live app runs on Streamlit Community Cloud from this repository (branch `main`, main file `app.py`,
Python 3.13, no secrets); a push to `main` redeploys it. Community Cloud apps sleep after 12 hours without visitors:
the button "Yes, get this app back up!" wakes the app in a minute or two.

When the notebook's module changes: `python tools/sync_engine.py` (copies `fm_lean.py` unchanged and prints both
SHA-256 hashes), `python tools/make_snapshot.py --from-notebook <notebook output folder>`, then `pytest -q`.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit page (UI only) |
| `core.py` | turns sidebar choices into `fm_lean` calls |
| `fm_lean.py` | the notebook's module, unchanged |
| `data_layer.py` | live download via `fm_lean.load_data`, snapshot fallback |
| `charts.py` | Plotly figures in the prospectus colours |
| `data/` | notebook's input snapshot and `results.json` |
| `tests/`, `tools/` | consistency tests, module sync, snapshot refresh |

## Use of generative AI

Strategy, client and conclusions were chosen by the group and discussed in regular group calls. We used Claude Code (Anthropic) as an assistant: to brainstorm and double-check our ideas against the published research, to help write and test the notebook and app code, and to help draft and lay out the prospectus text. We checked its outputs with 16 automated tests, a fresh Colab run, a second, separately written version of the backtest (same Table 1) and our own review of code, numbers and text against the notebook output.

(The 16 automated tests and the Colab run refer to the submitted notebook; this repository adds 18 pytest tests for the app.)

Educational project, not investment advice. Hypothetical back-tested results. Past performance does not predict
future returns.
