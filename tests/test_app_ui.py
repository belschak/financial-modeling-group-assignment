"""The real Streamlit page, driven headlessly (streamlit.testing), on the stored snapshot (no network)."""
import os

import pytest

import data_layer as dl
from conftest import REPO

pytestmark = pytest.mark.skipif(not dl.snapshot_available(), reason="no stored snapshot")


def _app():
    from streamlit.testing.v1 import AppTest
    os.chdir(REPO)
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=120)
    at.session_state["data_pref"] = "snapshot"
    at.run()
    assert not at.exception, at.exception
    return at


def _card(at, label_start):
    return next(m.value for m in at.metric if m.label.startswith(label_start))


def test_defaults_page_shows_six_required_measures_and_badge():
    at = _app()
    labels = [m.label for m in at.metric]
    for want in ("Average return p.a.", "Volatility p.a.", "Sharpe ratio", "Alpha p.a.", "Information ratio", "Beta"):
        assert any(lbl.startswith(want) for lbl in labels), want
    assert any("matches prospectus Table 1" in m.value for m in at.markdown)


def test_changing_one_assumption_keeps_the_others():
    at = _app()
    at.select_slider(key="period_0").set_range("2010-01", "2020-12").run()
    at.radio(key="base_ccy").set_value("USD").run()
    assert at.session_state["period_0"] == ("2010-01", "2020-12")
    assert any("Custom assumptions" in m.value for m in at.markdown)


def test_cost_slider_changes_numbers_and_reset_restores_defaults():
    at = _app()
    sharpe0 = _card(at, "Sharpe ratio")
    at.select_slider(key="cost_bps").set_value(75).run()
    assert _card(at, "Sharpe ratio") != sharpe0
    at.button[0].click().run()
    assert not at.exception
    assert _card(at, "Sharpe ratio") == sharpe0
    # Reset gives the period slider a new key, so the browser cannot keep showing the old range
    assert at.session_state["period_rev"] == 1
    assert at.select_slider(key="period_1").value == ("2007-01", "2025-12")


def test_long_window_moves_the_start_instead_of_failing():
    at = _app()
    at.slider(key="sma_window").set_value(12).run()
    at.radio(key="signal_lag").set_value(2).run()
    assert not at.exception and not at.error
    assert any("Start moved to" in i.value for i in at.info)
    assert any(m.label == "Sharpe ratio" for m in at.metric)


def test_exactly_24_months_never_shows_a_traceback():
    # review finding 1: the window comparison shortened this to 23 months and raised
    at = _app()
    at.select_slider(key="period_0").set_range("2007-01", "2008-12").run()
    assert not at.exception, at.exception
    assert any("Method" in t.label for t in at.tabs)


def test_extreme_settings_never_show_a_traceback():
    at = _app()
    combos = [dict(tickers=["SPY", "IEF"]), dict(base_ccy="USD", hedge=False), dict(rebalance="none"),
              dict(primary_benchmark="B2 Classic 60/40"), dict(cost_bps=100), dict(signal_lag=2, sma_window=6)]
    for c in combos:
        for k, v in c.items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, (c, at.exception)


def test_live_failure_falls_back_to_snapshot_with_notice(monkeypatch):
    import streamlit as st
    st.cache_resource.clear()   # no failure remembered from an earlier test
    st.cache_data.clear()
    monkeypatch.setenv("FM_SIMULATE_LIVE_FAILURE", "1")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=120)
    at.session_state["data_pref"] = "live"
    at.run()
    assert not at.exception, at.exception
    assert any("Live data unavailable, showing snapshot as of" in w.value for w in at.warning)
    assert any(m.label == "Sharpe ratio" for m in at.metric)
    # review finding 3: a failed download is remembered; further clicks do not retry it
    import data_layer as dlm
    calls = []
    real = dlm.load_live
    monkeypatch.setattr(dlm, "load_live", lambda *a, **k: calls.append(1) or real(*a, **k))
    at.select_slider(key="cost_bps").set_value(25).run()
    assert not at.exception and calls == []
