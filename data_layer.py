"""Data layer for the app: the engine's own live download, plus a snapshot fallback.

Live (default): `fm_backtest.load_data()`, i.e. exactly the notebook's download code
(Yahoo Finance via yfinance, falling back to Yahoo's chart API; FRED key-less CSV for rates and FX;
ECB Data Portal for the latest EUR rate months).

Snapshot (fallback): `data/snapshot_inputs.csv` + `data/snapshot_meta.json`, the same monthly inputs
stored once. Used only if Yahoo or FRED refuse the request (Yahoo often rate-limits cloud servers).

No Streamlit import here; the app adds caching.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import fm_backtest as fb

DATA_DIR = Path(__file__).parent / "data"
SNAP_CSV = DATA_DIR / "snapshot_inputs.csv"
SNAP_META = DATA_DIR / "snapshot_meta.json"


def download_config(end: str | None = None) -> dict:
    """Engine config used for downloading: the default universe up to the last complete month."""
    if end is None:
        end = (pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return fb.get_config(end=end)


def load_live(end: str | None = None) -> dict:
    data = fb.load_data(download_config(end))
    data["origin"] = "live"
    return data


RF_EUR_COL, RF_USD_COL, FX_COL = "RF_EUR_monthly", "RF_USD_monthly_shifted", "FX_USDperEUR"


def save_snapshot(data: dict) -> None:
    """Store the engine's own snapshot table (fm_backtest.snapshot_frame) plus provenance."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = fb.snapshot_frame(data)
    df.index.name = "month_end"
    df.to_csv(SNAP_CSV, float_format="%.12g")
    meta = dict(first_daily=data["first_daily"], sources=data["sources"], retrieved_at=data["retrieved_at"],
                n_daily_rows=data.get("n_daily_rows"), engine_version=fb.ENGINE_VERSION,
                note="fm_backtest.snapshot_frame(load_data(cfg)): month-end USD prices, FX, monthly rf decimals.")
    SNAP_META.write_text(json.dumps(meta, indent=2))


def load_snapshot(csv: Path = SNAP_CSV, meta_path: Path = SNAP_META) -> dict:
    df = pd.read_csv(csv, index_col=0, parse_dates=True)
    meta = json.loads(meta_path.read_text())
    idx = pd.DatetimeIndex(df.index)
    tick = [c for c in df.columns if c not in (RF_EUR_COL, RF_USD_COL, FX_COL)]
    return dict(
        prices_usd=df[tick].set_axis(idx),
        fx_usd_per_eur=df[FX_COL].set_axis(idx),
        rf={"EUR": df[RF_EUR_COL].set_axis(idx), "USD": df[RF_USD_COL].set_axis(idx)},
        first_daily=meta.get("first_daily", {t: df[t].first_valid_index().strftime("%Y-%m-%d") for t in tick}),
        sources=meta["sources"], retrieved_at=meta["retrieved_at"],
        n_daily_rows=meta.get("n_daily_rows"), origin="snapshot",
    )


def snapshot_available() -> bool:
    return SNAP_CSV.exists() and SNAP_META.exists()


def last_complete_month(data: dict, tickers: list[str]) -> pd.Timestamp:
    """Latest month-end for which every input needed by the backtest exists."""
    ends = [data["prices_usd"][t].last_valid_index() for t in tickers]
    ends += [data["fx_usd_per_eur"].last_valid_index(), data["rf"]["EUR"].last_valid_index(),
             data["rf"]["USD"].last_valid_index()]
    return min(ends)


def describe(data: dict) -> str:
    src = data["sources"]
    used = sorted(set(src["prices"].values())) if isinstance(src.get("prices"), dict) else [str(src.get("prices"))]
    px = ", ".join(u.replace("yahoo_chart_api", "Yahoo chart API").replace("yfinance", "Yahoo Finance via yfinance")
                   for u in used)
    return f"prices {px}; EUR rate {src['rf_EUR']}; USD rate {src['rf_USD']}; FX {src['fx']}; retrieved {data['retrieved_at']}"
