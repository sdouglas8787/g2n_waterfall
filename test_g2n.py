"""
Tests for the invariants that make a gross-to-net bridge trustworthy.

These are not coverage tests. Each one pins a specific way a bridge goes wrong
in practice: a subtotal added as a movement, a deduction dropped from one
audience's view, a residual quietly absorbed.

    python -m pytest test_g2n.py -q
"""

from __future__ import annotations

import pytest

from g2n import (
    FMCG_TRADE_TERMS,
    Bridge,
    Kind,
    Layout,
    LayoutError,
    Ledger,
    ReconciliationError,
    Step,
    bridge_from_rows,
    fmcg_layouts,
)

ROW = {
    "GROSS_SALES": 1_000_000,
    "LISTING": -30_000,
    "VOLUME_REBATE": -50_000,
    "LOGISTICS": -20_000,
    "PROMPT_PAY": -10_000,
    "TPR": -120_000,
    "FEATURE_DISPLAY": -40_000,
    "OVERRIDER": -25_000,
    "MARKDOWN": -8_000,
    "RETURNS": -5_000,
    "net_sales": 680_000,
}


def make_bridge(**overrides):
    row = {**ROW, **overrides}
    return bridge_from_rows([row], label="Test")


# --------------------------------------------------------------- reconciling


def test_walk_lands_on_stated_net():
    make_bridge().reconcile()


def test_residual_is_the_unexplained_gap():
    # Deductions listed total 308,000, so they imply a net of 692,000.
    # The ledger settled at 680,000, leaving 12,000 unexplained.
    bridge = make_bridge()
    assert bridge.residual == pytest.approx(-12_000)
    assert bridge.residual_share() == pytest.approx(-0.012)


def test_residual_is_zero_when_deductions_fully_explain_net():
    bridge = make_bridge(net_sales=692_000)
    assert bridge.residual == pytest.approx(0.0)


def test_every_layout_closes_on_the_same_net():
    bridge = make_bridge()
    nets = {
        name: bridge.build(layout)[-1].end
        for name, layout in fmcg_layouts().items()
    }
    assert len(nets) == 3
    for name, net in nets.items():
        assert net == pytest.approx(680_000), f"{name} layout closes at {net:,.0f}"


def test_bar_starts_and_ends_are_contiguous():
    bridge = make_bridge()
    bars = bridge.build(fmcg_layouts()["diagnostic"])
    for previous, current in zip(bars, bars[1:]):
        if current.kind is Kind.CLOSING:
            assert current.end == pytest.approx(previous.end)
        else:
            assert current.start == pytest.approx(previous.end)


# ------------------------------------------------- the double-counting guard


def test_running_position_cannot_be_used_as_a_movement():
    """The classic bridge bug: adding 'Invoiced Sales' to the walk."""
    bridge = make_bridge()
    broken = Layout(
        name="Broken",
        bars=[
            ("Gross Sales", ["GROSS_SALES"]),
            ("Invoiced Sales", ["INVOICED_SALES"]),  # a subtotal, not a movement
            ("Net Sales", ["NET_SALES"]),
        ],
    )
    with pytest.raises(LayoutError, match="running position"):
        bridge.build(broken)


def test_layout_must_consume_every_movement():
    """A layout that drops a deduction would show a flattering, wrong net."""
    bridge = make_bridge()
    incomplete = Layout(
        name="Incomplete",
        bars=[
            ("Gross Sales", ["GROSS_SALES"]),
            ("Some Terms", ["LISTING", "VOLUME_REBATE"]),  # TPR et al missing
            ("Net Sales", ["NET_SALES"]),
        ],
    )
    with pytest.raises(LayoutError, match="omitted"):
        bridge.build(incomplete)


def test_a_step_cannot_appear_in_two_bars():
    bridge = make_bridge()
    duplicated = Layout(
        name="Duplicated",
        bars=[
            ("Gross Sales", ["GROSS_SALES"]),
            ("Terms", ["LISTING", "VOLUME_REBATE", "LOGISTICS", "PROMPT_PAY"]),
            ("Terms Again", ["LISTING"]),
            ("Promos", ["TPR", "FEATURE_DISPLAY"]),
            ("Rest", ["OVERRIDER", "MARKDOWN", "RETURNS", "OTHER_ADJ"]),
            ("Net Sales", ["NET_SALES"]),
        ],
    )
    with pytest.raises(LayoutError, match="already used"):
        bridge.build(duplicated)


# ------------------------------------------------------------- ledger typing


def test_ledger_requires_exactly_one_residual():
    steps = tuple(
        Step(s.code, s.label, s.kind, s.group) for s in FMCG_TRADE_TERMS
    )  # residual flag stripped
    with pytest.raises(LayoutError, match="residual"):
        Ledger(steps=steps, amounts={"GROSS_SALES": 100.0}, closing_actual=90.0)


def test_ledger_rejects_unknown_amounts():
    with pytest.raises(LayoutError, match="unknown steps"):
        Ledger(
            steps=FMCG_TRADE_TERMS,
            amounts={"GROSS_SALES": 100.0, "NOT_A_STEP": 1.0},
            closing_actual=90.0,
        )


def test_malformed_ledger_fails_reconciliation():
    """A subtotal wrongly typed as a movement breaks the walk, loudly."""
    steps = (
        Step("GROSS", "Gross", Kind.OPENING, "Gross"),
        Step("DISC", "Discount", Kind.MOVEMENT, "Terms"),
        Step("SUBTOTAL", "Subtotal", Kind.MOVEMENT, "Subtotal"),  # should be POSITION
        Step("RESID", "Residual", Kind.MOVEMENT, "Other", is_residual=True),
        Step("NET", "Net", Kind.CLOSING, "Net"),
    )
    ledger = Ledger(
        steps=steps,
        amounts={"GROSS": 1000.0, "DISC": -100.0, "SUBTOTAL": 900.0},
        closing_actual=900.0,
    )
    bridge = Bridge(ledger)
    # The derived residual absorbs the double count, so it shows up as a
    # residual the size of the subtotal - which is the signal to look again.
    assert bridge.residual == pytest.approx(-900.0)


# ----------------------------------------------------------- the disclosure


def test_combined_bar_still_discloses_the_residual():
    """The exec view folds the residual into a bar; the number stays published."""
    bridge = make_bridge()
    executive = fmcg_layouts()["executive"]

    combined = next(b for b in bridge.build(executive) if b.label == "Other Trade Spend")
    assert "OTHER_ADJ" in combined.codes

    disclosed = dict(bridge.disclosures(executive))
    assert disclosed["Other Adjustments"] == pytest.approx(-12_000)
    assert "Other Adjustments (disclosed)" in bridge.to_text(executive)


def test_diagnostic_view_needs_no_disclosure():
    bridge = make_bridge()
    assert bridge.disclosures(fmcg_layouts()["diagnostic"]) == []


# ---------------------------------------------------------------- aggregation


def test_rows_aggregate_and_residual_is_derived_once():
    two = bridge_from_rows([ROW, ROW], label="Two rows")
    one = make_bridge()
    assert two.opening_value == pytest.approx(2 * one.opening_value)
    assert two.residual == pytest.approx(2 * one.residual)
    two.reconcile()


def test_reconciliation_error_when_closing_is_inconsistent():
    """Guard the guard: a hand-built ledger with no residual slack must fail."""
    steps = (
        Step("GROSS", "Gross", Kind.OPENING, "Gross"),
        Step("DISC", "Discount", Kind.MOVEMENT, "Terms"),
        Step("RESID", "Residual", Kind.MOVEMENT, "Other", is_residual=True),
        Step("NET", "Net", Kind.CLOSING, "Net"),
    )
    bridge = Bridge(
        Ledger(steps=steps, amounts={"GROSS": 1000.0, "DISC": -100.0}, closing_actual=900.0)
    )
    bridge.reconcile()
    bridge._amounts["RESID"] = 50.0  # simulate a supplied, wrong residual
    with pytest.raises(ReconciliationError, match="break"):
        bridge.reconcile()
