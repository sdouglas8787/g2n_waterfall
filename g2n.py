"""
Gross-to-Net waterfall: an atomic step ledger that reconciles by construction.

A gross-to-net bridge walks from gross sales to net sales through a series of
deductions. It is one of the most common artefacts in commercial finance and one
of the most commonly wrong, for three reasons this module is built to prevent:

  1. Double counting. A bridge mixes two different kinds of number - MOVEMENTS
     (a deduction, which belongs in the walk) and POSITIONS (a subtotal such as
     "invoiced sales", which does not). Adding a position to a walk silently
     double counts everything above it. Here the distinction is a type, and the
     summation only ever touches movements.

  2. Silent residuals. Real source data never carries every pricing effect. The
     gap between the sum of the movements you can explain and the closing value
     you actually invoiced is the residual. A bridge that quietly absorbs it into
     the nearest bar is lying. Here the residual is computed explicitly, is
     always a named step, and Bridge.reconcile() fails loudly if it is missing.

  3. One chart, one audience. An exec wants five bars; a category buyer wants
     trade-terms wording; an analyst wants every atomic movement. Rebuilding the
     bridge per audience is how the three versions drift apart. Here layouts are
     views over a single ledger, and every layout is checked to close on the
     same net.

The core has no third-party dependencies. Charting and Excel export are optional
extras (matplotlib, xlsxwriter) and are imported only when called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence

__all__ = [
    "Kind",
    "Step",
    "Ledger",
    "Bridge",
    "Layout",
    "Bar",
    "ReconciliationError",
    "LayoutError",
    "FMCG_TRADE_TERMS",
]

# Money is compared to the nearest penny. Anything larger than this between the
# stated closing value and the walked closing value is a real break, not float
# noise, and reconcile() will raise.
TOLERANCE = 0.01


class ReconciliationError(AssertionError):
    """The walk does not arrive at the stated closing value."""


class LayoutError(ValueError):
    """A layout is malformed - unknown step, or a position used as a movement."""


class Kind(Enum):
    """What a step *is*, which determines whether it may enter a summation.

    OPENING and CLOSING are the endpoints of the walk. MOVEMENT steps are the
    deltas between them and are the only steps that get summed. POSITION steps
    are running subtotals - useful to report, never to add.
    """

    OPENING = "opening"
    MOVEMENT = "movement"
    POSITION = "position"
    CLOSING = "closing"

    @property
    def is_summable(self) -> bool:
        return self is Kind.MOVEMENT


@dataclass(frozen=True)
class Step:
    """One line in the ledger.

    code:      stable identifier; layouts and source mappings refer to this
    label:     default display name; a layout may override it
    kind:      see Kind - governs whether the step enters the summation
    group:     reporting group, used to roll atomic steps up in coarser layouts
    is_residual: marks the balancing step. Exactly one movement must set this.
    """

    code: str
    label: str
    kind: Kind
    group: str = "Other"
    is_residual: bool = False


@dataclass
class Ledger:
    """The step definitions plus the amounts, for one slice of the business.

    Amounts are signed as they act on the walk: deductions negative, uplifts
    positive. The residual step's amount is not supplied - it is derived, so
    that the bridge closes by construction rather than by hope.
    """

    steps: Sequence[Step]
    amounts: Mapping[str, float]
    closing_actual: float
    label: str = "Total"

    def __post_init__(self) -> None:
        codes = [s.code for s in self.steps]
        if len(codes) != len(set(codes)):
            dupes = sorted({c for c in codes if codes.count(c) > 1})
            raise LayoutError(f"duplicate step codes: {', '.join(dupes)}")

        openings = [s for s in self.steps if s.kind is Kind.OPENING]
        if len(openings) != 1:
            raise LayoutError(f"expected exactly 1 opening step, found {len(openings)}")

        residuals = [s for s in self.steps if s.is_residual]
        if len(residuals) != 1:
            raise LayoutError(
                f"expected exactly 1 residual step, found {len(residuals)}. "
                "A bridge without an explicit residual hides its own error."
            )
        if residuals[0].kind is not Kind.MOVEMENT:
            raise LayoutError("the residual step must be a MOVEMENT")

        unknown = set(self.amounts) - set(codes)
        if unknown:
            raise LayoutError(f"amounts given for unknown steps: {', '.join(sorted(unknown))}")

    @property
    def opening(self) -> Step:
        return next(s for s in self.steps if s.kind is Kind.OPENING)

    @property
    def residual(self) -> Step:
        return next(s for s in self.steps if s.is_residual)

    def by_code(self, code: str) -> Step:
        try:
            return next(s for s in self.steps if s.code == code)
        except StopIteration:
            raise LayoutError(f"unknown step code: {code}") from None


@dataclass
class Bar:
    """A rendered bar: one step, or several steps combined for an audience."""

    label: str
    amount: float
    kind: Kind
    group: str
    start: float = 0.0  # running total before this bar
    end: float = 0.0  # running total after this bar
    codes: tuple[str, ...] = ()

    @property
    def is_endpoint(self) -> bool:
        return self.kind in (Kind.OPENING, Kind.CLOSING)


@dataclass
class Layout:
    """An audience-specific view over the ledger.

    `bars` is an ordered list of (display label, step codes) pairs. Several
    codes under one label combine into a single bar - the exec view collapsing
    detail - while the underlying amounts stay separate in the ledger.

    `always_disclose` names steps whose amount must be reported as a standalone
    figure even when the layout has folded them into a combined bar. This is the
    guard against a large residual disappearing behind a tidy chart.
    """

    name: str
    bars: Sequence[tuple[str, Sequence[str]]]
    always_disclose: Sequence[str] = field(default_factory=tuple)


class Bridge:
    """Builds and validates the walk, then renders it per layout."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._amounts = dict(ledger.amounts)
        self._amounts[ledger.residual.code] = self._derive_residual()

    def _derive_residual(self) -> float:
        """Residual = closing actual, less opening, less every explained movement.

        Derived rather than supplied. If the source data explains everything the
        residual is zero; if it does not, the gap is visible and named instead of
        being smeared across the other bars.
        """
        explained = self._amounts.get(self.ledger.opening.code, 0.0)
        for step in self.ledger.steps:
            if step.kind.is_summable and not step.is_residual:
                explained += self._amounts.get(step.code, 0.0)
        return self.ledger.closing_actual - explained

    def amount(self, code: str) -> float:
        self.ledger.by_code(code)  # raises on unknown code
        return self._amounts.get(code, 0.0)

    @property
    def residual(self) -> float:
        return self._amounts[self.ledger.residual.code]

    @property
    def opening_value(self) -> float:
        return self._amounts.get(self.ledger.opening.code, 0.0)

    @property
    def closing_value(self) -> float:
        return self.ledger.closing_actual

    def reconcile(self) -> None:
        """Assert the walk lands on the stated closing value.

        With a derived residual this holds by construction, so a failure here
        means the ledger itself is malformed - typically a POSITION step wrongly
        typed as a MOVEMENT.
        """
        walked = self.opening_value + sum(
            self._amounts.get(s.code, 0.0)
            for s in self.ledger.steps
            if s.kind.is_summable
        )
        break_amount = walked - self.closing_value
        if abs(break_amount) > TOLERANCE:
            raise ReconciliationError(
                f"{self.ledger.label}: walk closes at {walked:,.2f} but actual is "
                f"{self.closing_value:,.2f} (break {break_amount:,.2f})"
            )

    def residual_share(self) -> float:
        """Residual as a share of opening value - the bridge's own error rate.

        Worth publishing beside any bridge. A residual over a couple of percent
        means the deduction taxonomy is incomplete, and no amount of chart
        polish makes the walk trustworthy until that is understood.
        """
        if not self.opening_value:
            return 0.0
        return self.residual / self.opening_value

    def build(self, layout: Layout) -> list[Bar]:
        """Resolve a layout into positioned bars, validating as it goes."""
        self.reconcile()

        seen: set[str] = set()
        bars: list[Bar] = []
        running = 0.0

        for label, codes in layout.bars:
            if not codes:
                raise LayoutError(f"{layout.name}/{label}: no step codes")

            steps = [self.ledger.by_code(c) for c in codes]

            positions = [s.code for s in steps if s.kind is Kind.POSITION]
            if positions:
                raise LayoutError(
                    f"{layout.name}/{label}: {', '.join(positions)} is a running "
                    "position, not a movement. Including it double counts every "
                    "step above it."
                )

            kinds = {s.kind for s in steps}
            if len(kinds) > 1:
                raise LayoutError(
                    f"{layout.name}/{label}: cannot combine {', '.join(sorted(k.value for k in kinds))}"
                )
            kind = kinds.pop()

            repeated = seen.intersection(codes)
            if repeated:
                raise LayoutError(
                    f"{layout.name}/{label}: {', '.join(sorted(repeated))} already used"
                )
            seen.update(codes)

            amount = sum(self._amounts.get(c, 0.0) for c in codes)
            groups = {s.group for s in steps}
            group = groups.pop() if len(groups) == 1 else "Combined"

            if kind is Kind.OPENING:
                start, end, running = 0.0, amount, amount
            elif kind is Kind.CLOSING:
                start, end = 0.0, running
                amount = running
            else:
                start = running
                running += amount
                end = running

            bars.append(
                Bar(
                    label=label,
                    amount=amount,
                    kind=kind,
                    group=group,
                    start=start,
                    end=end,
                    codes=tuple(codes),
                )
            )

        self._check_layout_closes(layout, bars, seen)
        return bars

    def _check_layout_closes(
        self, layout: Layout, bars: list[Bar], seen: set[str]
    ) -> None:
        """Every layout must consume every movement and land on the same net.

        This is what stops the exec view and the analyst view drifting apart:
        a layout that drops a deduction fails here rather than quietly showing
        a better net than the business actually made.
        """
        movements = {s.code for s in self.ledger.steps if s.kind.is_summable}
        missing = movements - seen
        if missing:
            labels = ", ".join(sorted(self.ledger.by_code(c).label for c in missing))
            raise LayoutError(
                f"{layout.name}: movements omitted, so the layout would not close: {labels}"
            )

        closings = [b for b in bars if b.kind is Kind.CLOSING]
        if len(closings) != 1:
            raise LayoutError(f"{layout.name}: expected exactly 1 closing bar")
        if abs(closings[0].end - self.closing_value) > TOLERANCE:
            raise ReconciliationError(
                f"{layout.name}: layout closes at {closings[0].end:,.2f}, "
                f"ledger closes at {self.closing_value:,.2f}"
            )

    def disclosures(self, layout: Layout) -> list[tuple[str, float]]:
        """Figures that must be published even though a bar has absorbed them.

        A combined bar is a presentation choice. It must never be a way of
        making an uncomfortable number invisible.
        """
        return [
            (self.ledger.by_code(code).label, self._amounts.get(code, 0.0))
            for code in layout.always_disclose
        ]

    # ---------------------------------------------------------------- output

    def to_text(self, layout: Layout, width: int = 64) -> str:
        """Plain-text bridge. No dependencies, works in a terminal or a log."""
        bars = self.build(layout)
        name_w = max(len(b.label) for b in bars) + 2
        lines = [f"{self.ledger.label} - {layout.name}", "-" * width]

        for bar in bars:
            value = bar.end if bar.is_endpoint else bar.amount
            marker = "=" if bar.is_endpoint else " "
            lines.append(f"{marker} {bar.label:<{name_w}} {value:>14,.0f}")
            if not bar.is_endpoint:
                lines.append(f"  {'':<{name_w}} {bar.end:>14,.0f}  (running)")

        lines.append("-" * width)
        lines.append(
            f"  {'Residual as % of gross':<{name_w}} {self.residual_share():>13.2%}"
        )
        for label, amount in self.disclosures(layout):
            lines.append(f"! {label + ' (disclosed)':<{name_w}} {amount:>14,.0f}")
        return "\n".join(lines)

    # Palette: reference data-viz palette, validated with the six checks on the
    # light surface (#fcfcfb), all pairs. Red vs green measures CVD dE 7.2, in
    # the 6-8 band that is permitted only with secondary encoding - here sign is
    # carried three ways over and above hue: deduction bars point down, uplift
    # bars point up, and every bar is direct-labelled with a signed value.
    SURFACE = "#fcfcfb"
    C_ENDPOINT = "#2a78d6"   # slot 1 blue  - opening and closing positions
    C_DEDUCTION = "#e34948"  # slot 8 red   - reduces net
    C_UPLIFT = "#008300"     # slot 6 green - increases net
    C_RESIDUAL = "#eda100"   # slot 4 yellow - the unexplained gap, never hidden
    INK = "#0b0b0b"
    INK_MUTED = "#898781"
    GRID = "#e1e0d9"
    CONNECTOR = "#c3c2b7"

    def to_chart(
        self,
        layout: Layout,
        path: str,
        title: str | None = None,
        subtitle: str | None = None,
    ) -> str:
        """Render the walk as a waterfall. Requires matplotlib.

        Imported lazily so the core module stays dependency-free.
        """
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib.patches import Patch
            from matplotlib.ticker import FuncFormatter
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "charting needs matplotlib: pip install matplotlib"
            ) from exc

        bars = self.build(layout)
        residual_code = self.ledger.residual.code

        fig, ax = plt.subplots(figsize=(max(8.0, len(bars) * 1.15), 4.6))
        fig.patch.set_facecolor(self.SURFACE)
        ax.set_facecolor(self.SURFACE)

        def colour_for(bar: Bar) -> str:
            if bar.is_endpoint:
                return self.C_ENDPOINT
            if bar.codes == (residual_code,):
                return self.C_RESIDUAL
            return self.C_UPLIFT if bar.amount >= 0 else self.C_DEDUCTION

        # Headroom is set from the tallest bar so labels never reach the title.
        peak = max(max(b.start, b.end) for b in bars)
        pad = peak * 0.045

        for i, bar in enumerate(bars):
            colour = colour_for(bar)
            if bar.is_endpoint:
                ax.bar(i, bar.end, color=colour, width=0.58, zorder=3)
                label_y, va = bar.end + pad * 0.35, "bottom"
                text = f"{bar.end:,.0f}"
            else:
                ax.bar(
                    i,
                    bar.amount,
                    bottom=bar.start,
                    color=colour,
                    width=0.58,
                    zorder=3,
                )
                # A deduction hangs below its start, so its label sits under the
                # bar; an uplift labels above. Neither can collide with the title.
                if bar.amount < 0:
                    label_y, va = min(bar.start, bar.end) - pad * 0.35, "top"
                else:
                    label_y, va = max(bar.start, bar.end) + pad * 0.35, "bottom"
                text = f"{bar.amount:+,.0f}"

            ax.text(
                i,
                label_y,
                text,
                ha="center",
                va=va,
                fontsize=8.5,
                color=self.INK,
                zorder=4,
            )

            # Connector from this bar's closing level to the next bar's start.
            if i < len(bars) - 1 and not bars[i + 1].is_endpoint:
                ax.plot(
                    [i + 0.29, i + 1 - 0.29],
                    [bar.end, bar.end],
                    color=self.CONNECTOR,
                    linewidth=1.0,
                    zorder=2,
                )

        ax.set_xticks(range(len(bars)))
        ax.set_xticklabels(
            [b.label for b in bars], rotation=22, ha="right", fontsize=8.5
        )
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.tick_params(colors=self.INK_MUTED, labelsize=8.5, length=0)
        for lbl in ax.get_xticklabels():
            lbl.set_color(self.INK)

        ax.set_ylim(0, peak + pad * 3)
        ax.grid(axis="y", color=self.GRID, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(self.CONNECTOR)

        # Identity is never colour-alone: a legend is always present.
        legend_roles = [
            (self.C_ENDPOINT, "Opening / closing"),
            (self.C_DEDUCTION, "Deduction"),
        ]
        if any(
            (not b.is_endpoint) and b.amount >= 0 and b.codes != (residual_code,)
            for b in bars
        ):
            legend_roles.append((self.C_UPLIFT, "Uplift"))
        if any(b.codes == (residual_code,) for b in bars):
            legend_roles.append((self.C_RESIDUAL, "Unexplained residual"))

        ax.legend(
            handles=[Patch(facecolor=c, label=t) for c, t in legend_roles],
            loc="lower left",
            bbox_to_anchor=(0.0, 1.005),
            ncol=len(legend_roles),
            frameon=False,
            fontsize=8.5,
            labelcolor=self.INK,
            handlelength=1.1,
            handleheight=1.1,
            columnspacing=1.4,
        )

        ax.set_title(
            title or f"{self.ledger.label} \u2013 {layout.name}",
            fontsize=12.5,
            color=self.INK,
            loc="left",
            pad=28,
        )

        note = subtitle or (
            f"Residual {self.residual:,.0f} "
            f"({self.residual_share():.2%} of gross)   |   "
            f"Net realisation {self.closing_value / self.opening_value:.1%}"
        )
        fig.text(0.012, 0.015, note, fontsize=8, color=self.INK_MUTED)

        fig.tight_layout(rect=(0, 0.035, 1, 1))
        fig.savefig(path, dpi=160, facecolor=self.SURFACE)
        plt.close(fig)
        return path


# --------------------------------------------------------------------------
# A conventional FMCG trade-terms ledger.
#
# Supplied as a starting point, not a standard: every business has its own
# deduction taxonomy, and the point of the module is that redefining these steps
# is a data change, not a code change.
# --------------------------------------------------------------------------

FMCG_TRADE_TERMS: tuple[Step, ...] = (
    Step("GROSS_SALES", "Gross Sales", Kind.OPENING, "Gross"),
    # On-invoice: visible to the customer on the invoice itself.
    Step("LISTING", "Listing Discount", Kind.MOVEMENT, "On-invoice"),
    Step("VOLUME_REBATE", "Volume Rebate", Kind.MOVEMENT, "On-invoice"),
    Step("LOGISTICS", "Logistics Allowance", Kind.MOVEMENT, "On-invoice"),
    Step("PROMPT_PAY", "Prompt Payment Discount", Kind.MOVEMENT, "On-invoice"),
    Step("INVOICED_SALES", "Invoiced Sales", Kind.POSITION, "Subtotal"),
    # Off-invoice: settled retrospectively, and where bridges usually go wrong.
    Step("TPR", "Temporary Price Reduction", Kind.MOVEMENT, "Off-invoice"),
    Step("FEATURE_DISPLAY", "Feature & Display", Kind.MOVEMENT, "Off-invoice"),
    Step("OVERRIDER", "Annual Overrider", Kind.MOVEMENT, "Off-invoice"),
    Step("MARKDOWN", "Markdown & Distress", Kind.MOVEMENT, "Off-invoice"),
    Step("RETURNS", "Returns & Claims", Kind.MOVEMENT, "Off-invoice"),
    Step("OTHER_ADJ", "Other Adjustments", Kind.MOVEMENT, "Off-invoice", is_residual=True),
    Step("NET_SALES", "Net Sales", Kind.CLOSING, "Net"),
)


def fmcg_layouts() -> dict[str, Layout]:
    """Three audiences, one ledger, one closing net."""
    return {
        # Five bars. Detail collapsed, but the residual is still disclosed as a
        # standalone figure beside the chart.
        "executive": Layout(
            name="Executive",
            bars=[
                ("Gross Sales", ["GROSS_SALES"]),
                ("On-invoice Terms", ["LISTING", "VOLUME_REBATE", "LOGISTICS", "PROMPT_PAY"]),
                ("Promotional Investment", ["TPR", "FEATURE_DISPLAY"]),
                ("Other Trade Spend", ["OVERRIDER", "MARKDOWN", "RETURNS", "OTHER_ADJ"]),
                ("Net Sales", ["NET_SALES"]),
            ],
            always_disclose=["OTHER_ADJ"],
        ),
        # Customer-facing wording, split the way a joint business plan is argued.
        "trade_terms": Layout(
            name="Trade Terms",
            bars=[
                ("Gross Sales", ["GROSS_SALES"]),
                ("Listing & Volume", ["LISTING", "VOLUME_REBATE"]),
                ("Logistics & Payment", ["LOGISTICS", "PROMPT_PAY"]),
                ("Promotions", ["TPR", "FEATURE_DISPLAY"]),
                ("Overriders", ["OVERRIDER"]),
                ("Markdown & Returns", ["MARKDOWN", "RETURNS", "OTHER_ADJ"]),
                ("Net Sales", ["NET_SALES"]),
            ],
            always_disclose=["OTHER_ADJ"],
        ),
        # Every movement as its own bar. Nothing combined, nothing to disclose.
        "diagnostic": Layout(
            name="Diagnostic",
            bars=[
                ("Gross Sales", ["GROSS_SALES"]),
                ("Listing", ["LISTING"]),
                ("Volume Rebate", ["VOLUME_REBATE"]),
                ("Logistics", ["LOGISTICS"]),
                ("Prompt Payment", ["PROMPT_PAY"]),
                ("TPR", ["TPR"]),
                ("Feature & Display", ["FEATURE_DISPLAY"]),
                ("Overrider", ["OVERRIDER"]),
                ("Markdown", ["MARKDOWN"]),
                ("Returns", ["RETURNS"]),
                ("Other Adjustments", ["OTHER_ADJ"]),
                ("Net Sales", ["NET_SALES"]),
            ],
        ),
    }


def bridge_from_rows(
    rows: Iterable[Mapping[str, float]],
    *,
    steps: Sequence[Step] = FMCG_TRADE_TERMS,
    opening_field: str = "GROSS_SALES",
    closing_field: str = "net_sales",
    label: str = "Total",
) -> Bridge:
    """Aggregate transaction rows into a bridge.

    Each row carries its deduction amounts keyed by step code, plus the actual
    net it settled at. Summing the rows and deriving one residual at the top is
    deliberate: it surfaces the aggregate unexplained gap, which is the number
    worth arguing about.
    """
    steps = tuple(steps)
    movement_codes = [s.code for s in steps if s.kind.is_summable and not s.is_residual]

    totals = {code: 0.0 for code in [opening_field, *movement_codes]}
    closing = 0.0

    for row in rows:
        for code in totals:
            totals[code] += float(row.get(code, 0.0))
        closing += float(row.get(closing_field, 0.0))

    return Bridge(
        Ledger(steps=steps, amounts=totals, closing_actual=closing, label=label)
    )
