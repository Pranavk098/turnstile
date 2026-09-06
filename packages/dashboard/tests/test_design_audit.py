"""W3-B Item 4 -- design-audit P0/P1 fixes, pinned as static assertions on the
hand-authored HTML (no browser in CI; the <680px pass is a structural check
that every table owns an overflow container + a narrow-CSS review note)."""
from __future__ import annotations

import build_data


def _html() -> str:
    return (build_data.DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")


def _home() -> str:
    return (build_data.DASHBOARD_DIR / "home.html").read_text(encoding="utf-8")


def test_faint_contrast_fix_in_both_pages():
    # The --faint: #8a8f98 contrast fix (first landed in home.html) applies
    # to index.html too.
    assert "--faint: #8a8f98" in _html()
    assert "--faint: #8a8f98" in _home()


def test_page_never_scrolls_sideways_tables_scroll_in_their_own_box():
    html = _html()
    # The page itself clips horizontal overflow ...
    assert "html, body { overflow-x: clip; }" in html
    # ... while every table owns a scroll container:
    # calls list + per-call findings (static markup), barge-in sweeps
    # (built by table(), which wraps each in its own .tscroll),
    # leaderboard details (.wdetail), drawer bodies (.body).
    assert ".tscroll { overflow-x: auto; }" in html
    assert '<div class="tscroll">\n        <table id="calls-table">' in html
    assert '<div class="tscroll"><div id="hero-findings"></div></div>' in html
    assert 'wrap.className = "tscroll"' in html
    assert ".wdetail { padding: 6px 4px 18px; overflow-x: auto; }" in html
    assert "details.drawer .body { padding-bottom: 18px;" in html
    assert "overflow-x: auto; }" in html


def test_tabular_numbers_with_consistent_precision():
    html = _html()
    assert "font-variant-numeric: tabular-nums" in html
    # Table columns share one fixed precision (fmtMoney); headlines and
    # prose keep their compact/full forms.
    assert "const fmtMoney = (v)" in html
    assert html.count("fmtMoney(") >= 8


def test_conditional_rows_carry_no_fake_arrow_affordance():
    html = _html()
    # .crow rows are plain divs (not expandable): the chevron that implied
    # interactivity is removed rather than faked. Every remaining chevron
    # lives inside a real interactive control (details/summary or a link).
    section = html.split("function renderConditional(")[1].split("function renderReplay(")[0]
    assert "chev" not in section
    assert ".crow .chev" not in html
    assert "no chevron affordance" in html


def test_degenerate_rows_read_as_checked_zero_not_missing():
    html = _html()
    # Conditional "no measured effect" rows: muted italic via .crow.zero.
    assert ".crow.zero .cval" in html
    assert "font-style: italic" in html
    assert "no measured effect" in html
    # Per-call findings and call-list top waste: muted italic, never blank.
    assert ".zero-note { color: var(--faint); font-style: italic; }" in html
    assert "no waste detected on this call" in html
    assert ">no waste detected</span>" in html
