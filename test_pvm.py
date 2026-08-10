"""
Tests for the price / volume / mix decomposition.

The central property is that the drivers are *exact* — price, volume, mix, new
and lost sum to the change in net revenue with nothing left over. A PVM bridge
that needs a plug to close is a PVM bridge nobody should present, so that
property is tested against randomised inputs rather than one hand-picked case.

    python -m pytest test_pvm.py -q
"""

from __future__ import annotations

import random

import pytest

from pvm import (
    PeriodRow,
    decompose,
    growth_summary,
    price_growth,
    pvm_bridge,
    pvm_layout,
)

LAST_YEAR = [
    PeriodRow("Soup 400g", 1_000_000, 1.00),
    PeriodRow("Beetroot 340g", 500_000, 1.50),
]
THIS_YEAR = [
    PeriodRow("Soup 400g", 1_100_000, 1.10),
    PeriodRow("Beetroot 340g", 450_000, 1.60),
]


def test_drivers_sum_to_the_revenue_change():
    bridge = pvm_bridge(LAST_YEAR, THIS_YEAR)
    bridge.reconcile()
    assert bridge.residual == pytest.approx(0.0)


def test_decomposition_is_exact_on_random_inputs():
    """The property that makes the bridge presentable: no plug, ever."""
    rng = random.Random(11)
    for _ in range(500):
        names = [f"sku{i}" for i in range(rng.randint(1, 8))]
        ly = [PeriodRow(n, rng.uniform(1, 5000), rng.uniform(0.2, 40)) for n in names]
        # Drop and add lines so new/lost are exercised too.
        ty_names = names[rng.randint(0, len(names) - 1):] + ["new_line"]
        ty = [PeriodRow(n, rng.uniform(1, 5000), rng.uniform(0.2, 40)) for n in ty_names]

        drivers = decompose(ly, ty)
        change = sum(r.revenue for r in ty) - sum(r.revenue for r in ly)
        assert sum(drivers.values()) == pytest.approx(change, rel=1e-9, abs=1e-6)


def test_pure_price_move_shows_only_price():
    """Same volumes, higher prices: nothing should leak into volume or mix."""
    ly = [PeriodRow("a", 100, 2.00), PeriodRow("b", 200, 3.00)]
    ty = [PeriodRow("a", 100, 2.20), PeriodRow("b", 200, 3.30)]
    d = decompose(ly, ty)
    assert d["PRICE"] == pytest.approx(100 * 0.20 + 200 * 0.30)
    assert d["VOLUME"] == pytest.approx(0.0)
    assert d["MIX"] == pytest.approx(0.0)


def test_proportional_volume_growth_is_volume_not_mix():
    """Every line up 10% at held prices is pure volume - mix must stay zero."""
    ly = [PeriodRow("a", 100, 2.00), PeriodRow("b", 200, 5.00)]
    ty = [PeriodRow("a", 110, 2.00), PeriodRow("b", 220, 5.00)]
    d = decompose(ly, ty)
    assert d["VOLUME"] == pytest.approx(120.0)  # 10% of 1,200
    assert d["MIX"] == pytest.approx(0.0)
    assert d["PRICE"] == pytest.approx(0.0)


def test_shift_toward_the_premium_line_is_mix_not_volume():
    """Total units flat, richer blend: the whole effect is mix."""
    ly = [PeriodRow("cheap", 100, 1.00), PeriodRow("premium", 100, 5.00)]
    ty = [PeriodRow("cheap", 50, 1.00), PeriodRow("premium", 150, 5.00)]
    d = decompose(ly, ty)
    assert d["VOLUME"] == pytest.approx(0.0)  # 200 units both years
    assert d["MIX"] == pytest.approx(200.0)  # 50 units moved, £4 richer each
    assert d["PRICE"] == pytest.approx(0.0)


def test_new_and_delisted_lines_are_separated_out():
    ly = [PeriodRow("keep", 100, 2.00), PeriodRow("drop", 50, 4.00)]
    ty = [PeriodRow("keep", 100, 2.00), PeriodRow("add", 30, 6.00)]
    d = decompose(ly, ty)
    assert d["NEW"] == pytest.approx(180.0)
    assert d["LOST"] == pytest.approx(-200.0)
    # The surviving line did not move, so no price/volume/mix effect at all.
    assert d["PRICE"] == pytest.approx(0.0)
    assert d["VOLUME"] == pytest.approx(0.0)
    assert d["MIX"] == pytest.approx(0.0)


def test_price_growth_is_price_effect_over_last_year_net():
    bridge = pvm_bridge(LAST_YEAR, THIS_YEAR)
    assert price_growth(bridge) == pytest.approx(
        bridge.amount("PRICE") / bridge.opening_value
    )


def test_reported_net_that_differs_lands_in_unexplained():
    """A reconciliation difference must not be smeared across the drivers."""
    clean = pvm_bridge(LAST_YEAR, THIS_YEAR)
    stated = clean.closing_value - 5_000
    bridge = pvm_bridge(LAST_YEAR, THIS_YEAR, ty_net_actual=stated)
    bridge.reconcile()
    assert bridge.residual == pytest.approx(-5_000)
    assert bridge.amount("PRICE") == pytest.approx(clean.amount("PRICE"))


def test_layout_closes_on_this_year_net():
    bridge = pvm_bridge(LAST_YEAR, THIS_YEAR)
    bars = bridge.build(pvm_layout())
    assert bars[-1].end == pytest.approx(bridge.closing_value)


def test_duplicate_product_in_a_period_is_refused():
    with pytest.raises(ValueError, match="duplicate product"):
        decompose([PeriodRow("a", 1, 1), PeriodRow("a", 2, 2)], THIS_YEAR)


def test_no_common_range_puts_everything_in_new_and_lost():
    d = decompose([PeriodRow("old", 10, 1.0)], [PeriodRow("new", 20, 2.0)])
    assert d["PRICE"] == pytest.approx(0.0)
    assert d["VOLUME"] == pytest.approx(0.0)
    assert d["MIX"] == pytest.approx(0.0)
    assert d["NEW"] == pytest.approx(40.0)
    assert d["LOST"] == pytest.approx(-10.0)


def test_movement_bridge_does_not_claim_a_realisation_rate():
    """'Net realisation' is gross-to-net wording and is wrong on a PVM walk."""
    text = pvm_bridge(LAST_YEAR, THIS_YEAR).to_text(pvm_layout())
    assert "Net realisation" not in text
    assert "last year net" in text


def test_growth_summary_reports_each_driver_as_a_percentage():
    summary = growth_summary(pvm_bridge(LAST_YEAR, THIS_YEAR))
    for line in ("Price growth", "Volume growth", "Mix effect", "Total growth"):
        assert line in summary
