# BP Trend-Guarded Multi-Asset: interactive backtest

Streamlit app for the group assignment of **2270 Financial Modeling, Nova SBE (Fall 2026), Group BP**:
Tim Fischer, David Konrad Belschak, Tom Nico H Croe, Lennart Schmülling, Fridolin Treibig, Bastian Volkery.

**Live app:** https://fm-group-bp-backtest.streamlit.app
**Notebook:** `FM-Group-BP-Backtest.ipynb`, submitted on Moodle together with the investor prospectus

![Overview: assumptions in the sidebar, the six required measures against the benchmark](docs/screenshot-overview.png)

## What it does

The strategy holds five broad asset classes (US equity, developed ex-US equity, US Treasuries 7-10y, US REITs,
broad commodities) in equal capital slices. At each month-end an asset stays invested only while its price is above
its 10-month moving average (Faber 2007); otherwise its slice moves to cash.

In the sidebar you change the assumptions and every number recalculates:

| Assumption | Default (= prospectus) | Range |
|---|---|---|
| Moving-average window | 10 months | 6 to 12 |
| Signal delay | 1 month | 1 or 2 |
| Rebalancing back to equal slices | Monthly | monthly, quarterly, annually, never |
| Trading cost (one-way) | 10 bps (fund level) | 0 to 100 bps (50 = retail stress case) |
| Base currency | EUR | EUR or USD |
| Hedge bond slice to EUR | on | on / off (EUR view) |
| Backtest period | Jan 2007 to Dec 2025 | Jan 2007 to the last complete month |
| Assets | all five | any two or more |
| Benchmark for alpha, beta, IR | B1 equal weight 1/n | B1 or B2 (60/40) |

The page shows the six measures the brief requires (annualised average return, volatility, Sharpe ratio, alpha,
information ratio in both forms, regression and tracking error, and beta, the latter not annualised) with plain-English explanations;
the largest fall against the client's 10% target (20% hard ceiling); the growth of 1 for the
strategy and both benchmarks from the same start date; drawdowns; calendar-year returns; holdings over time;
turnover, cost drag and breakeven costs (on return and on Sharpe); a 10-year Monte Carlo outlook for 10,000 EUR
(P10/P50/P90, with a cautious variant that halves the historical excess return);
the indicative PRIIPs risk class; a full metrics table with CSV download; and the method.

Two views go beyond the headline numbers:

- **Crisis replay**: the 2008 financial crisis, the 2011 euro crisis, the 2020 Covid crash, the 2022 rate shock and
  the February to April 2025 tariff shock. Strategy against both benchmarks through each window, plus a month-by-month
  strip of which slices were invested or in cash, and the list of switches.
- **Robustness**: the notebook's own checks for your settings: execution timing (lag 1, next trading day, lag 2,
  and the non-implementable lag 0 as a look-ahead control), rebalance-day timing luck, first vs second half of the
  sample, a bootstrap interval for the Sharpe advantage, and costs by fund.
- **Window stability**: the 6, 8, 10 and 12-month windows side by side on one common sample. It is a check that the
  result does not hinge on the 10 months from the paper, not a menu: choosing the best-looking window afterwards would
  be data-snooping.

![Crisis replay: 2008, strategy vs benchmarks and which slices were in cash](docs/screenshot-crisis-replay.png)

## Same calculations as the notebook

**Engine frozen:** `fm_backtest.py` SHA-256
`ffc29e11f02fc67f8ac678cc760d4a01c2637ba37538679f0ad4db23ddf7a50d` (final fresh-Colab run of the notebook,
21.11.2026). The app footer and Method tab show the SHA of the engine actually running.

`fm_backtest.py` is the **unchanged engine file** of the submitted notebook (the notebook writes it with
`%%writefile`). The app never re-implements a calculation: `core.py` only maps the sidebar to the engine's `CONFIG`
and calls engine functions (`run_backtest`, `metrics_table`, `turnover_stats`, `breakeven_cost`,
`cost_sensitivity`, `annual_returns`, `risk_indicator`, `monte_carlo`, `robustness`, `extra_robustness`). The footer and the Method tab print the engine
version and SHA-256, which the notebook prints too, and the git commit of the running code.

Tests (`pytest -q`):

- `test_engine_identity.py`: the app's engine is byte-identical to the engine inside the notebook
  (`%%writefile` cells of the .ipynb) and to the group's engine file.
- `test_consistency_with_notebook.py`: the app's defaults reproduce the notebook's `results.json`.
- `test_app_core.py`: app defaults equal the notebook `CONFIG` exactly; every setting runs; series start at 1.00;
  a benchmark against itself gives beta 1, alpha 0, tracking error 0.
- `test_app_ui.py`: the real page, driven headlessly: required measures shown, settings keep each other, reset works.

To point the identity and consistency tests at the notebook, put the notebook folder path in
`tests/local_notebook_dir.txt` (git-ignored) or set `FM_NOTEBOOK_DIR`, or copy the .ipynb into `notebook/`.
GitHub Actions runs all tests on the pinned `requirements.txt`.

## Data

Live, through the engine's own loader (no API keys, no data files needed): Yahoo Finance adjusted closes
(via `yfinance`, falling back to Yahoo's chart API, same data), the ECB Data Portal for the euro overnight rate
(EONIA to September 2019, then the euro short-term rate), FRED for the US T-bill rate and the EUR/USD rate. One
batched download, cached for 12 hours.

Yahoo sometimes throttles shared cloud servers. The app then shows "Live data unavailable, showing snapshot as of
...", never a traceback, and uses `data/snapshot_inputs.csv`: the same monthly inputs, saved with the engine's own
`snapshot_frame`: the monthly file is the notebook run's own input export, so offline defaults equal the notebook
exactly; `data/snapshot_daily.csv` adds daily closes and FX for the daily risk class and the day-of-month check
(`python tools/make_snapshot.py --from-notebook <notebook output folder>` refreshes both). "Data source" in the sidebar selects it explicitly.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Python 3.11 to 3.13. Tests: `pip install pytest` then `pytest -q`.

## Deployment

The live app runs on Streamlit Community Cloud from this repository (branch `main`, main file `app.py`,
Python 3.13, no secrets); a push to `main` redeploys it. Community Cloud apps sleep after 12 hours without visitors:
the button "Yes, get this app back up!" wakes the app in a minute or two.

When the notebook's engine changes: `python tools/sync_engine.py` (copies it unchanged and prints both SHA-256
hashes), `python tools/make_snapshot.py --from-notebook <notebook output folder>`, then `pytest -q`.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit page (UI only) |
| `core.py` | maps sidebar choices to the engine CONFIG, collects results |
| `fm_backtest.py` | shared engine, identical to the notebook |
| `data_layer.py` | live download via the engine, snapshot fallback |
| `charts.py` | Plotly figures in the prospectus colours |
| `.streamlit/config.toml` | theme (light and dark) |
| `tests/`, `tools/` | consistency tests, engine sync, snapshot refresh |

## Use of generative AI

Use of generative AI. We used Claude Code (Anthropic) throughout the project: for research, including proposing the published trend rule we adopted (Faber 2007), for the notebook and app code, and for drafting and laying out this text. We checked all outputs with 23 automated tests, a fresh Colab run, a second, separately written backtest that gives the same headline numbers, and our own review of code, numbers and text against the notebook output.

Educational project, not investment advice. Hypothetical back-tested results. Past performance does not predict
future returns.
