"""The real Streamlit page, driven headlessly (streamlit.testing), on the stored snapshot (no network)."""
import json
import os

import pytest

import data_layer as dl
from conftest import REPO, repo_results_json

pytestmark = pytest.mark.skipif(not dl.snapshot_available(), reason="no stored snapshot")
RJ = json.loads(repo_results_json().read_text(encoding="utf-8"))
S = RJ["portfolios"]["strategy"]


def _app():
    from streamlit.testing.v1 import AppTest
    os.chdir(REPO)
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=120)
    at.session_state["data_pref"] = "snapshot"
    at.run()
    assert not at.exception, at.exception
    return at


def _card(at, label_start):
    return next(m for m in at.metric if m.label.startswith(label_start))


def _md(at):
    return " ".join(m.value for m in at.markdown)


def test_default_cards_equal_prospectus_table1_and_badge():
    at = _app()
    assert "matches prospectus Table 1" in _md(at)
    assert _card(at, "Average return p.a.").value == f"{S['ann_return']:.1%}"
    assert _card(at, "Volatility p.a.").value == f"{S['ann_vol']:.1%}"
    assert _card(at, "Sharpe ratio").value == f"{S['sharpe']:.2f}"
    alpha = _card(at, "Alpha p.a. vs B1")
    assert alpha.value == f"{S['alpha_ann']:.1%}" and alpha.delta == f"t = {S['alpha_t']:.2f}"
    assert _card(at, "Beta vs B1").value == f"{S['beta']:.2f}"   # not annualised


def test_both_information_ratios_shown():
    """D3: regression IR on the card, tracking-error IR in the caption, both equal to results.json."""
    at = _app()
    assert _card(at, "Information ratio (regression)").value == f"{S['information_ratio_regression']:.2f}"
    md = _md(at)
    assert "Regression (alpha / residual volatility" in md and "Tracking error (return above" in md
    assert f"<b>{S['information_ratio']:.2f}</b>" in md and f"<b>{S['information_ratio_regression']:.2f}</b>" in md


def test_client_target_and_ceiling_equal_results_json():
    """D2: the client's 10% target and 20% hard ceiling, as in results.json `client`."""
    import core
    at = _app()
    c = RJ["client"]
    assert (core.CLIENT_DD_TARGET, core.CLIENT_DD_CEILING) == (c["target_max_drawdown"],
                                                                                c["hard_max_drawdown"])
    assert (f"worst fall of at most {c['target_max_drawdown']:.0%}, with {c['hard_max_drawdown']:.0%} as the hard "
            "ceiling") in _md(at)


def test_changing_one_assumption_changes_numbers_and_reset_restores():
    at = _app()
    sharpe0 = _card(at, "Sharpe ratio").value
    at.select_slider(key="cost_bps").set_value(75).run()
    assert _card(at, "Sharpe ratio").value != sharpe0 and "Custom assumptions" in _md(at)
    at.button[0].click().run()
    assert not at.exception and _card(at, "Sharpe ratio").value == sharpe0
    assert at.session_state["period_rev"] == 1 and at.select_slider(key="period_1").value == ("2007-01", "2025-12")


def test_next_day_shown_beside_and_selectable():
    at = _app()
    nd = RJ["prospectus_numbers"]["headline_next_day"]
    assert f"Sharpe ratio {nd['sharpe']:.2f}" in _md(at)
    at.radio(key="next_day").set_value(True).run()
    assert not at.exception and _card(at, "Sharpe ratio").value == f"{nd['sharpe']:.2f}"


def test_period_and_benchmark_keep_each_other():
    at = _app()
    at.select_slider(key="period_0").set_range("2010-01", "2020-12").run()
    at.radio(key="bench").set_value("B2").run()
    assert at.session_state["period_0"] == ("2010-01", "2020-12")
    assert any(m.label == "Beta vs B2" for m in at.metric)


def test_long_window_moves_the_start_instead_of_failing():
    at = _app()
    at.slider(key="sma").set_value(12).run()
    at.radio(key="lag").set_value(2).run()
    assert not at.exception and not at.error
    assert any("Start moved to" in i.value for i in at.info)


def test_extreme_settings_never_show_a_traceback():
    at = _app()
    for c in (dict(tickers=["SPY", "IEF"]), dict(bench="B2"), dict(cost_bps=100), dict(lag=2, sma=6),
              dict(next_day=True, tickers=["VNQ", "DBC"])):
        for k, v in c.items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, (c, at.exception)
    at.select_slider(key="period_0").set_range("2007-01", "2008-12").run()
    assert not at.exception and any("Method" in t.label for t in at.tabs)


def test_live_failure_falls_back_to_snapshot_with_notice(monkeypatch):
    import streamlit as st
    st.cache_resource.clear()
    st.cache_data.clear()
    monkeypatch.setenv("FM_SIMULATE_LIVE_FAILURE", "1")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(REPO / "app.py"), default_timeout=120)
    at.session_state["data_pref"] = "live"
    at.run()
    assert not at.exception, at.exception
    assert any("Live data unavailable, showing snapshot as of" in w.value for w in at.warning)
    calls = []
    real = dl.load_live
    monkeypatch.setattr(dl, "load_live", lambda *a, **k: calls.append(1) or real(*a, **k))
    at.select_slider(key="cost_bps").set_value(25).run()
    assert not at.exception and calls == []   # a failed download is remembered; clicks do not retry it
