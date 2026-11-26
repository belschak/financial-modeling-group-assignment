"""A live download that runs past the notebook's END must still give the notebook's B3 (offline: synthetic APIs).

fl.chain_b3 measures B3's pre-2009 gap to the index over the overlap up to the download's last month, so a later
download would shift B3 before Nov 2009 a little. data_layer.anchor_b3 chains B3 again up to the notebook's END.
"""
import numpy as np
import pandas as pd

import data_layer as dl
import fm_lean as fl

STARTS = {"SPY": "1993-01-29", "EFA": "2001-08-17", "IEF": "2002-07-26", "XLU": "1998-12-22", "DBC": "2006-02-06",
          "GLD": "2004-11-18", "^SPGSCI": "1990-01-02", "GC=F": "2000-08-30", "EUNL.DE": "2009-09-25",
          "^990100-USD-STRD": "1990-01-02"}


def _fake_apis(monkeypatch):
    days = pd.bdate_range("1990-01-01", "2026-12-31")
    rng = np.random.default_rng(7)
    px = pd.DataFrame({t: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(days)))) for t in STARTS}, index=days)
    for t, s in STARTS.items():
        px.loc[:pd.Timestamp(s) - pd.Timedelta(days=1), t] = np.nan
    monkeypatch.setattr(fl, "yahoo", lambda tickers, start, end: px.loc[start:end, tickers])
    monthly = pd.date_range("1999-01-01", "2026-12-01", freq="MS")
    monkeypatch.setattr(fl, "ecb", lambda key: pd.Series(2.0, index=monthly))
    fx_d = pd.Series(1.1 + 0.1 * np.sin(np.arange(len(days)) / 300), index=days).loc["1999":]

    def fred(series, **extra):
        if series == "EFFR":
            return pd.Series(3.0, index=days.copy()).loc["2000-07":]
        return fx_d.resample("MS").last() if extra.get("fq") else fx_d
    monkeypatch.setattr(fl, "fred", fred)


def test_anchor_b3_reproduces_the_notebooks_b3_and_keeps_later_returns(monkeypatch):
    _fake_apis(monkeypatch)
    nb = fl.load_data(dl.NOTEBOOK_END)                   # what the notebook downloads (END = Dec 2025)
    live = fl.load_data("2026-10-31")                    # the app, eleven months later
    fixed = dl.anchor_b3(live)
    for key in ("px", "px_next"):
        a, b = nb[key]["B3"], fixed[key]["B3"].loc[:dl.NOTEBOOK_END]
        assert not np.allclose(live[key]["B3"].loc["2005":"2009-09"].pct_change().dropna(),
                               a.loc["2005":"2009-09"].pct_change().dropna(), rtol=0, atol=1e-12)   # the gap does move
        pd.testing.assert_series_equal(a.loc["2004":], b.loc["2004":], check_names=False, rtol=1e-12)
        r_live, r_fixed = live[key]["B3"].pct_change().loc["2026-01":], fixed[key]["B3"].pct_change().loc["2026-01":]
        pd.testing.assert_series_equal(r_live, r_fixed, check_names=False, rtol=1e-10)
    for t in fl.TICKERS:   # nothing else changes
        pd.testing.assert_series_equal(live["px"][t], fixed["px"][t])
    assert dl.anchor_b3(nb) is nb                        # a download that ends at END is left alone
