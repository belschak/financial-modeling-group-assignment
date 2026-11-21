# BP Trend-Guarded Multi-Asset: interactive backtest

Streamlit app for the group assignment of **2270 Financial Modeling, Nova SBE (Fall 2026), Group BP**:
Tim Fischer, David Konrad Belschak, Tom Nico H Croe, Lennart Schmülling, Fridolin Treibig, Bastian Volkery.

**Live app:** `https://<app-name>.streamlit.app` (added after deployment)
**Notebook:** submitted with the investor prospectus (Colab link added here once shared)

## What it does

The strategy holds five broad asset classes (US equity, developed ex-US equity, US Treasuries 7-10y, US REITs,
broad commodities) in equal slices. At each month-end an asset stays invested only while its price is above its
10-month moving average (Faber 2007); otherwise its slice moves to cash at the risk-free rate.

In the sidebar you change the assumptions and every number recalculates:

| Assumption | Default (= prospectus) | Range |
|---|---|---|
| Moving-average window | 10 months | 3 to 24 |
| Signal delay | 1 month | 1 or 2 |
| Rebalancing back to target | Monthly | monthly, quarterly, annually, never |
| Trading cost (one-way) | 10 bps | 0 to 100 bps |
| Base currency | EUR | EUR or USD |
| Backtest period | Jan 2007 to Dec 2025 | Jan 2007 to the last complete month |
| Assets | all five | any two or more |
| Benchmark for alpha, beta, IR | B1 static 1/n | B1 or B2 (60/40) |

The page shows the six measures the brief requires (annualised average return, volatility, Sharpe ratio, alpha,
information ratio, beta, the latter not annualised) with plain-English explanations, the growth of 1 for the
strategy and both benchmarks from the same start date, drawdowns, holdings over time, turnover, cost drag,
breakeven cost and a full metrics table (CSV download).

## Same calculations as the notebook

`fm_backtest.py` is the **unchanged engine file** of the submitted notebook (the notebook writes it with
`%%writefile`). The app never re-implements a calculation: `core.py` only maps the sidebar to the engine's
`CONFIG` and calls `run_backtest`, `metrics_table`, `turnover_stats`, `breakeven_cost` and `cost_sensitivity`.
The Method tab prints the engine's SHA-256, which the notebook prints too.

Tests (`pytest -q`):

- `test_engine_identity.py`: app engine is byte-identical to the notebook's engine (file and `%%writefile` cells).
- `test_consistency_with_notebook.py`: app defaults reproduce the notebook's `results.json`.
- `test_app_core.py`: app defaults equal the notebook `CONFIG` exactly; every setting runs; series start at 1.00;
  a benchmark against itself gives beta 1, alpha 0, tracking error 0.

The GitHub Actions workflow runs the tests and a headless start of the app on the pinned `requirements.txt`.

## Data

Live, through the engine's own loader (no API keys, no data files needed): Yahoo Finance adjusted closes
(via `yfinance`, falling back to Yahoo's chart API), FRED key-less CSV for TB3MS, the euro 3-month rate and
DEXUSEU, and the ECB Data Portal for the newest euro-rate months. Downloads are cached for 6 hours.

Yahoo sometimes rate-limits cloud servers. In that case the app shows a clear notice and falls back to
`data/snapshot_inputs.csv`, the same monthly inputs downloaded once with the same code
(`python tools/make_snapshot.py` refreshes it). The sidebar's "Data source" lets you choose it explicitly.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Python 3.11 to 3.13. Tests: `pip install pytest` then `pytest -q`.

## Deploy on Streamlit Community Cloud (about 5 minutes, one group member)

1. The repository must be on GitHub under the deploying member's account (or one they can access).
2. Go to `https://share.streamlit.io` and sign in with GitHub. Allow access to the repository when asked
   (for a private repository, tick private repository access).
3. Click **Create app**, then **"Yup, I have an app"**.
4. Repository `belschak/fm-2270-backtest-app`, branch `main`, main file path `app.py`.
5. App URL: choose a short subdomain, e.g. `bp-trend-guarded`.
6. Open **Advanced settings**, set **Python version 3.13** (cannot be changed later without redeploying).
   No secrets are needed. Save.
7. Click **Deploy**. The first build takes a few minutes; then the app downloads the data once (about 15 seconds).
8. Make the app viewable without login: in the app's **Share** menu choose **"Make this app public"**
   (apps from private repositories start private; graders must open the link logged out).
9. Graders also need the source: the group switches this repository to public (Settings, General, Danger Zone,
   Change visibility) or adds the graders as collaborators.
10. Put both links (app URL and `https://github.com/belschak/fm-2270-backtest-app`) in the prospectus and the
    notebook, then check both in a private browser window.

Apps on Community Cloud sleep after 12 hours without visitors; a visitor wakes them with one click
("Yes, get this app back up!"), which takes a minute or two. Opening the app shortly before grading avoids this.

## Updating after the notebook changes

```bash
python tools/sync_engine.py      # copies the notebook's engine unchanged and prints both SHA-256 hashes
python tools/make_snapshot.py    # optional: refresh the offline snapshot
pytest -q
```

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

An AI coding assistant (Claude) helped write the app code. The group checked it with the tests above: the engine is
the notebook's own file, the defaults reproduce the notebook's numbers, and each user setting was exercised.

Educational project, not investment advice. Past performance does not predict future returns.
