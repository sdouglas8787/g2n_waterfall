"""
PVM (price, volume, mix): why net revenue moved between two periods.

The gross-to-net bridge in `g2n.py` explains where the money went *within* one
period. PVM is the other half of the question and the other bridge every
commercial finance team builds: net revenue was X last year and Y this year -
how much of the gap is price, how much is selling more, and how much is selling
a different shape of business?

It reuses the same Bridge, Ledger and Layout machinery. Opening is last year's
net, the movements are the drivers, closing is this year's net.

## The decomposition

For every product in both periods, with last-year price/volume (p0, q0) and
this-year (p1, q1):

    Price  = SUM q1 * (p1 - p0)          charged more per unit
    Volume = (Q1 - Q0) * P0bar           sold more units at last year's average
    Mix    = SUM q1 * p0 - Q1 * P0bar    sold a different blend of products

where Q is total units and P0bar is last year's volume-weighted average price.
Products present in only one period cannot have a price or volume effect
computed against a price that does not exist, so they are separated out:

    New    = SUM p1 * q1  over products only in this year
    Lost   = -SUM p0 * q0 over products only in last year

These five sum exactly to the change in net revenue - there is no interaction
or "unexplained" bucket by construction. Mix is the residual of the *volume*
calculation, not a plug: it is what is left once total units and per-unit price
are accounted for, which is precisely what "mix" means.

Mix is the driver most often quietly dropped, and dropping it makes price look
better or worse than it was. That is why the module refuses to render a layout
that omits a movement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from g2n import Bridge, Kind, Layout, Ledger, Step, format_money

__all__ = [
    "PeriodRow",
    "PVM_DRIVERS",
    "pvm_bridge",
    "pvm_layout",
    "price_growth",
]


@dataclass(frozen=True)
class PeriodRow:
    """One product's trading in one period.

    `revenue` is derived rather than supplied so price x volume can never
    disagree with the revenue it is supposed to explain.
    """

    product: str
    volume: float
    price: float

    @property
    def revenue(self) -> float:
        return self.volume * self.price


# Opening is last year's net; the drivers walk it to this year's net.
# None of these are conditional - PVM explains movement, it does not describe
# an agreement, so the conditionality question does not apply here.
PVM_DRIVERS: tuple[Step, ...] = (
    Step("LY_NET", "Last Year Net", Kind.OPENING, "Opening"),
    Step("PRICE", "Price", Kind.MOVEMENT, "Drivers"),
    Step("VOLUME", "Volume", Kind.MOVEMENT, "Drivers"),
    Step("MIX", "Mix", Kind.MOVEMENT, "Drivers"),
    Step("NEW", "New Lines", Kind.MOVEMENT, "Range"),
    Step("LOST", "Delisted Lines", Kind.MOVEMENT, "Range"),
    Step("PVM_OTHER", "Unexplained", Kind.MOVEMENT, "Drivers", is_residual=True),
    Step("TY_NET", "This Year Net", Kind.CLOSING, "Closing"),
)


def pvm_layout(name: str = "PVM") -> Layout:
    """One bar per driver. PVM is short enough that combining bars hides more
    than it helps, so there is a single layout rather than an exec cut."""
    return Layout(
        name=name,
        bars=[
            ("Last Year Net", ["LY_NET"]),
            ("Price", ["PRICE"]),
            ("Volume", ["VOLUME"]),
            ("Mix", ["MIX"]),
            ("New Lines", ["NEW"]),
            ("Delisted", ["LOST"]),
            ("Unexplained", ["PVM_OTHER"]),
            ("This Year Net", ["TY_NET"]),
        ],
    )


def _index(rows: Iterable[PeriodRow]) -> dict[str, PeriodRow]:
    out: dict[str, PeriodRow] = {}
    for row in rows:
        if row.product in out:
            raise ValueError(
                f"duplicate product in one period: {row.product}. "
                "Aggregate to one row per product before decomposing."
            )
        out[row.product] = row
    return out


def decompose(
    last_year: Iterable[PeriodRow], this_year: Iterable[PeriodRow]
) -> dict[str, float]:
    """Return the five driver amounts. Exact: they sum to the revenue change."""
    ly, ty = _index(last_year), _index(this_year)
    common = sorted(set(ly) & set(ty))

    q0_total = sum(ly[p].volume for p in common)
    q1_total = sum(ty[p].volume for p in common)
    ly_common_rev = sum(ly[p].revenue for p in common)

    # Last year's volume-weighted average price across the common range. With
    # no common volume there is no price to hold constant, so volume and mix
    # are undefined and the whole movement is new/lost.
    p0_bar = (ly_common_rev / q0_total) if q0_total else 0.0

    price = sum(ty[p].volume * (ty[p].price - ly[p].price) for p in common)
    volume = (q1_total - q0_total) * p0_bar
    mix = sum(ty[p].volume * ly[p].price for p in common) - q1_total * p0_bar

    new = sum(ty[p].revenue for p in sorted(set(ty) - set(ly)))
    lost = -sum(ly[p].revenue for p in sorted(set(ly) - set(ty)))

    return {"PRICE": price, "VOLUME": volume, "MIX": mix, "NEW": new, "LOST": lost}


def pvm_bridge(
    last_year: Sequence[PeriodRow],
    this_year: Sequence[PeriodRow],
    *,
    label: str = "Net Revenue Movement",
    currency: str = "£",
    ty_net_actual: float | None = None,
) -> Bridge:
    """Build the PVM bridge from two periods of product-level trading.

    ty_net_actual: this year's net as reported, where that differs from
    price x volume - a reconciliation difference, a late credit, a rounding
    convention. Supplying it puts the gap in the Unexplained step instead of
    silently reshaping the drivers. Left out, the drivers explain everything
    and Unexplained is zero.
    """
    drivers = decompose(last_year, this_year)
    ly_net = sum(r.revenue for r in last_year)
    ty_net = ty_net_actual if ty_net_actual is not None else sum(r.revenue for r in this_year)

    return Bridge(
        Ledger(
            steps=PVM_DRIVERS,
            amounts={"LY_NET": ly_net, **drivers},
            closing_actual=ty_net,
            label=label,
            currency=currency,
            # A movement bridge has no realisation rate, and its residual is a
            # share of last year's net, not of anything called "gross".
            ratio_label=None,
            basis_label="last year net",
        )
    )


def price_growth(bridge: Bridge) -> float:
    """Price growth %: the price effect as a share of last year's net.

    This is the number a pricing review is judged on - the realised year-on-year
    price movement, isolated from having sold more, or having sold a richer
    blend. It is not the same as the average shelf price moving by that much,
    and it is not list price inflation: it is what actually landed in net
    revenue.
    """
    if not bridge.opening_value:
        return 0.0
    return bridge.amount("PRICE") / bridge.opening_value


def growth_summary(bridge: Bridge, width: int = 68) -> str:
    """Year-on-year movement as percentages of last year's net."""
    cur = bridge.ledger.currency
    ly = bridge.opening_value
    pct = lambda code: (bridge.amount(code) / ly) if ly else 0.0  # noqa: E731

    total_growth = (bridge.closing_value - ly) / ly if ly else 0.0
    lines = [f"{bridge.ledger.label} - Year-on-Year Drivers", "-" * width]
    lines.append(f"  {'Last year net':<26}{format_money(ly, cur):>12}")
    lines.append(
        f"  {'This year net':<26}{format_money(bridge.closing_value, cur):>12}"
    )
    lines.append(f"  {'Total growth':<26}{total_growth:>12.1%}")
    lines.append("-" * width)
    for code, name in (
        ("PRICE", "Price growth"),
        ("VOLUME", "Volume growth"),
        ("MIX", "Mix effect"),
        ("NEW", "New lines"),
        ("LOST", "Delisted lines"),
    ):
        lines.append(
            f"  {name:<26}{format_money(bridge.amount(code), cur):>12}"
            f"{pct(code):>10.1%}"
        )
    if abs(bridge.residual) > 0.01:
        lines.append(
            f"  {'Unexplained':<26}"
            f"{format_money(bridge.residual, cur, compact=False):>12}"
            f"{bridge.residual_share():>10.1%}"
        )
    return "\n".join(lines)
