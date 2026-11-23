"""Data for the app: fm_lean.load_data (the notebook's own download), plus a stored snapshot as fallback.

The snapshot (data/snapshot_inputs.csv) is the notebook run's own input export, so offline defaults equal the
notebook exactly. It is used only if Yahoo, ECB or FRED refuse the request (Yahoo often throttles cloud servers).
No Streamlit import here; the app adds caching.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

import core
import fm_lean as fl

DATA_DIR = Path(__file__).parent / "data"
SNAP_CSV, SNAP_META = DATA_DIR / "snapshot_inputs.csv", DATA_DIR / "snapshot_meta.json"
SOURCES = "Yahoo Finance (adjusted closes, yfinance), ECB (EONIA, then EUR STR), FRED (EFFR, DEXUSEU)"
COLS = dict(fx="FX_USDperEUR", rf="RF_EUR_monthly", usd_on="RF_USD_overnight_monthly", fx_next="FX_USDperEUR_next_day")


def last_month_end() -> pd.Timestamp:
    return pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)


def load_live() -> dict:
    # Test hook: FM_SIMULATE_LIVE_FAILURE=1 makes the download fail, to check the snapshot fallback.
    if os.environ.get("FM_SIMULATE_LIVE_FAILURE") == "1":
        raise ConnectionError("simulated Yahoo Finance rate limit")
    d = fl.load_data(last_month_end().strftime("%Y-%m-%d"), fl.TICKERS)
    d["origin"] = "live"
    return d


def save_snapshot(d: dict) -> None:
    """Same table as the notebook's export: month-end prices, FX, rates and the next-day prices."""
    snap = pd.concat([d["px"], d["fx"].rename(COLS["fx"]), d["rf"].rename(COLS["rf"]), d["usd_on"].rename(COLS["usd_on"]),
                      d["px_next"].add_suffix("_next_day"), d["fx_next"].rename(COLS["fx_next"])], axis=1)
    DATA_DIR.mkdir(exist_ok=True)
    snap.to_csv(SNAP_CSV, float_format="%.10g")
    SNAP_META.write_text(json.dumps(dict(retrieved_at=d["retrieved_at"], module_sha256=core.SHA), indent=1))


def load_snapshot(csv: Path = SNAP_CSV, meta: Path = SNAP_META) -> dict:
    df = pd.read_csv(csv, index_col=0, parse_dates=True)
    nxt = [c for c in df.columns if c.endswith("_next_day") and c != COLS["fx_next"]]
    tick = [c for c in df.columns if c not in COLS.values() and c not in nxt]
    return dict(px=df[tick], px_next=df[nxt].rename(columns=lambda c: c.removesuffix("_next_day")),
                **{k: df[c] for k, c in COLS.items()},
                retrieved_at=json.loads(meta.read_text())["retrieved_at"], origin="snapshot")


def snapshot_available() -> bool:
    return SNAP_CSV.exists() and SNAP_META.exists()


def last_complete_month(d: dict, next_day: bool = False) -> pd.Timestamp:
    """Latest month-end for which every input of the backtest exists (next-day trading needs one more day)."""
    keys = ["px", "fx", "rf", "usd_on"] + (["px_next", "fx_next"] if next_day else [])
    ends = []
    for k in keys:
        x = d[k].dropna(how="any") if isinstance(d[k], pd.DataFrame) else d[k].dropna()
        ends.append(x.index[-1])
    return min(ends)
