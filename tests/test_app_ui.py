"""The real Streamlit page, driven headlessly (streamlit.testing), on the stored snapshot (no network)."""
import os

import pytest

import data_layer as dl
from conftest import REPO

pytestmark = pytest.mark.skipif(not dl.snapshot_available(), reason="no stored snapshot")


def _app():
    from streamlit.testing.v1 import AppTest
    os.chdir(REPO)
    at = AppTest.from_file("app.py", default_timeout=120)
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
    at.select_slider(key="period").set_range("2010-01", "2020-12").run()
    at.radio(key="base_ccy").set_value("USD").run()
    assert at.session_state["period"] == ("2010-01", "2020-12")
    assert any("Custom assumptions" in m.value for m in at.markdown)


def test_cost_slider_changes_numbers_and_reset_restores_defaults():
    at = _app()
    sharpe0 = _card(at, "Sharpe ratio")
    at.select_slider(key="cost_bps").set_value(75).run()
    assert _card(at, "Sharpe ratio") != sharpe0
    at.button[0].click().run()
    assert not at.exception
    assert _card(at, "Sharpe ratio") == sharpe0
    assert at.session_state["period"] == ("2007-01", "2025-12")


def test_too_short_history_gives_a_readable_message():
    at = _app()
    at.slider(key="sma_window").set_value(12).run()
    at.radio(key="signal_lag").set_value(2).run()
    assert not at.exception
    assert any("Move the start" in e.value for e in at.error)
