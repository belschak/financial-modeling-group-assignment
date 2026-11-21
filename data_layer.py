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
    # The pre-sample motivation series (^SP500TR) is notebook-only; the app does not need it.
    return fb.get_config(end=end, motivation_ticker=None)


def load_live(end: str | None = None) -> dict:
    data = fb.load_data(download_config(end))
    data["origin"] = "live"
    return data


def save_snapshot(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = data["prices_usd"].copy()
    df["RF_USD"] = data["rf"]["USD"]
    df["RF_EUR"] = data["rf"]["EUR"]
    df["FX_USD_PER_EUR"] = data["fx_usd_per_eur"]
    df.index.name = "month_end"
    df.to_csv(SNAP_CSV, float_format="%.12g")
    meta = dict(first_daily=data["first_daily"], sources=data["sources"], retrieved_at=data["retrieved_at"],
                note="Monthly inputs as returned by fm_backtest.load_data(); rf already converted to monthly decimals.")
    SNAP_META.write_text(json.dumps(meta, indent=2))


def load_snapshot() -> dict:
    df = pd.read_csv(SNAP_CSV, index_col=0, parse_dates=True)
    meta = json.loads(SNAP_META.read_text())
    tick = [c for c in df.columns if c not in ("RF_USD", "RF_EUR", "FX_USD_PER_EUR")]
    idx = pd.DatetimeIndex(df.index)
    return dict(
        prices_usd=df[tick].set_axis(idx),
        fx_usd_per_eur=df["FX_USD_PER_EUR"].set_axis(idx),
        rf={"USD": df["RF_USD"].set_axis(idx), "EUR": df["RF_EUR"].set_axis(idx)},
        first_daily=meta["first_daily"], sources=meta["sources"], retrieved_at=meta["retrieved_at"],
        daily_prices=None, origin="snapshot",
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
