"""Guided-tour legibility polish -- static assertions on the hand-authored
HTML (no browser in CI), same style as test_ingest_wire.py.

Six legibility criteria pinned here: (1) home.html orients a stranger in one
screen; (2) index.html explains itself without leaving the page and each tier
chip carries a plain-language tooltip; (3) the dataset switch states plainly
what changed when toggled; (4) absent classes read as a data gap, never as
zero waste; (5) the per-call drill-down has visible back navigation; (6) the
narrow (<680px) pass: the page never scrolls sideways and tooltips stay on
screen."""
from __future__ import annotations

import build_data


def _html() -> str:
    return (build_data.DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")


def _home() -> str:
    return (build_data.DASHBOARD_DIR / "home.html").read_text(encoding="utf-8")


# -------------------------------------------------------------------------- #
# 1. home.html orients a stranger: what Turnstile is, the tiers, the entry.   #
# -------------------------------------------------------------------------- #

def test_home_tiers_say_how_to_read_them():
    home = _home()
    # The three-tier block tells the reader how each label is used, not just
    # what it means: every number wears one label.
    assert "wears one of these three labels" in home
    assert "How to read" in home
    # The tiers keep their plain-language one-liners (polish, not redesign).
    assert "the saving is real" in home
    assert "Never mixed into the proven number" in home


# -------------------------------------------------------------------------- #
# 2. index.html explains itself without leaving the page.                     #
# -------------------------------------------------------------------------- #

def test_index_has_self_contained_what_is_this():
    html = _html()
    assert 'id="about"' in html
    assert "What am I looking at" in html
    assert "Why trust these numbers" in html
    # The masthead link opens the on-page explainer (not an external doc).
    assert 'href="#about"' in html
    about = html.split('id="about"')[1].split("</details>")[0]
    # The explainer names all three honesty labels itself.
    for tier in ("Proven", "Measured", "Conditional"):
        assert tier in about, tier


def test_tier_chips_carry_plain_language_tooltips():
    html = _html()
    for tier in ("proven", "measured", "conditional"):
        assert f'data-tip-tier="{tier}"' in html, tier
    assert "bindTierTips(" in html
    # Plain-language copies the tooltip shows (mirrors home.html's wording).
    assert "outcome stayed the same" in html
    assert "confidence intervals" in html
    assert "never mixed into the proven number" in html


# -------------------------------------------------------------------------- #
# 3. the dataset switch states plainly what changed when toggled.             #
# -------------------------------------------------------------------------- #

def test_dataset_switch_states_what_changed():
    html = _html()
    assert '<p class="t-note" id="dataset-note" hidden></p>' in html
    assert "Now viewing" in html
    # Panels that intentionally stay golden-only are named as such.
    assert "did not switch" in html


# -------------------------------------------------------------------------- #
# 4. absence is legible: a data gap, never zero waste.                        #
# -------------------------------------------------------------------------- #

def test_absence_reads_as_a_data_gap_not_zero():
    html = _html()
    # Fleet leaderboard rows AND the per-call coverage strip both explain why
    # the class is absent (the log lacked the acoustic fields) -- and both
    # say absence is not $0.
    assert html.count("a data gap, not zero waste") >= 2
    assert "acoustic fields" in html
    # The original honest-absence markers stay intact.
    assert "absent — no data for this input" in html
    assert "no data for this input -- not zero waste" in html


# -------------------------------------------------------------------------- #
# 5. navigation: home -> fleet -> per-call drill-down -> back is obvious.     #
# -------------------------------------------------------------------------- #

def test_per_call_drill_down_has_visible_back_navigation():
    html = _html()
    assert '<div class="t-note" id="hero-back">' in html
    back = html.split('id="hero-back"')[1].split("</div>")[0]
    assert 'href="#calls"' in back
    assert "Back to all calls" in back
    # The call list advertises that it is clickable.
    assert "click a call to drill down" in html
    # The home page links both ways (landing -> report, report -> landing).
    home = _home()
    assert 'href="index.html"' in home


# -------------------------------------------------------------------------- #
# 6. <680px: no horizontal body scroll; tooltips stay on screen.              #
# -------------------------------------------------------------------------- #

def test_narrow_viewport_keeps_the_page_scroll_free():
    html = _html()
    home = _home()
    assert "html, body { overflow-x: clip; }" in html
    assert "html, body { overflow-x: clip; }" in home
    assert ".tscroll { overflow-x: auto; }" in html
    # Tooltips clamp inside the viewport on phones instead of spilling right.
    assert "Math.max(8, Math.min(" in html
    assert "max-width: calc(100vw - 16px)" in html
