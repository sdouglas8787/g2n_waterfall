"""
Worked example: an ambient grocery supplier, branded and own-label.

ALL FIGURES ARE ILLUSTRATIVE AND INVENTED. They are not any real company's
trading, and they are shaped to exercise the mechanics rather than to look
plausible. Charts written by this script are stamped as example data.

Two things are deliberately not tidy, because real data is not tidy:

  * the deductions do not fully explain the settled net, so the G2N bridge
    derives a residual and reports it rather than absorbing it;
  * the range changes between years, so the PVM bridge has new and delisted
    lines to separate out before price and volume mean anything.

    python demo.py
    python demo.py --chart      # also writes PNGs (needs matplotlib)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from g2n import bridge_from_rows, fmcg_layouts
from pvm import PeriodRow, growth_summary, price_growth, pvm_bridge, pvm_layout

# ---------------------------------------------------------------- gross to net
# One row per customer x category. Deductions are negative, gross is positive.
# `net_sales` is what actually settled - taken from the ledger, not recomputed
# from the deductions, which is what allows the residual to be visible at all.
ROWS = [
    {
        "customer": "National Multiple A",
        "category": "Soup",
        "GROSS_SALES": 4_820_000,
        "LISTING": -168_700,
        "VOLUME_REBATE": -241_000,
        "LOGISTICS": -96_400,
        "PROMPT_PAY": -60_250,
        "TPR": -723_000,
        "FEATURE_DISPLAY": -192_800,
        "OVERRIDER": -144_600,
        "MARKDOWN": -38_560,
        "RETURNS": -24_100,
        "net_sales": 3_082_400,
    },
    {
        "customer": "National Multiple B",
        "category": "Soup",
        "GROSS_SALES": 3_640_000,
        "LISTING": -109_200,
        "VOLUME_REBATE": -182_000,
        "LOGISTICS": -72_800,
        "PROMPT_PAY": -45_500,
        "TPR": -400_400,
        "FEATURE_DISPLAY": -109_200,
        "OVERRIDER": -127_400,
        "MARKDOWN": -29_120,
        "RETURNS": -18_200,
        "net_sales": 2_524_900,
    },
    {
        "customer": "Discounter C",
        "category": "Condiments",
        "GROSS_SALES": 2_150_000,
        "LISTING": -21_500,
        "VOLUME_REBATE": -129_000,
        "LOGISTICS": -64_500,
        "PROMPT_PAY": -26_875,
        "TPR": -86_000,
        "FEATURE_DISPLAY": -10_750,
        "OVERRIDER": -43_000,
        "MARKDOWN": -12_900,
        "RETURNS": -8_600,
        "net_sales": 1_735_600,
    },
    {
        "customer": "Own-label Contract D",
        "category": "Canned Veg",
        "GROSS_SALES": 5_310_000,
        "LISTING": 0,
        "VOLUME_REBATE": -318_600,
        "LOGISTICS": -159_300,
        "PROMPT_PAY": -66_375,
        "TPR": 0,
        "FEATURE_DISPLAY": 0,
        "OVERRIDER": -53_100,
        "MARKDOWN": -79_650,
        "RETURNS": -42_480,
        "net_sales": 4_575_100,
    },
]

# What the customers could have taken at full performance, per the agreements.
# Only conditional terms may carry an entitlement - attainment against money
# that was never performance-linked would be meaningless, and the Ledger
# refuses it.
ENTITLEMENTS = {
    "VOLUME_REBATE": -1_020_000,   # all tiers achieved
    "PROMPT_PAY": -199_000,        # every invoice paid to terms
    "TPR": -1_320_000,             # full promotional plan executed
    "FEATURE_DISPLAY": -390_000,   # every agreed display delivered
    "OVERRIDER": -368_100,         # annual target hit in full
}

# ------------------------------------------------------- price / volume / mix
# Product-level trading, two years. The range is not identical between them:
# one line is new, one has been delisted.
LAST_YEAR = [
    PeriodRow("Soup Favourites 400g", 1_200_000, 1.10),
    PeriodRow("Soup Vegetarian 400g", 540_000, 1.15),
    PeriodRow("Beetroot 340g", 400_000, 1.35),
    PeriodRow("Chutney 290g", 250_000, 2.10),
    PeriodRow("Pie 425g", 600_000, 1.80),
]
THIS_YEAR = [
    PeriodRow("Soup Favourites 400g", 1_140_000, 1.19),
    PeriodRow("Soup Vegetarian 400g", 560_000, 1.22),
    PeriodRow("Beetroot 340g", 455_000, 1.42),
    PeriodRow("Chutney 290g", 268_000, 2.28),
    PeriodRow("Soup Luxury 400g", 210_000, 1.85),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart", action="store_true", help="write waterfall PNGs")
    args = parser.parse_args()

    print("=" * 68)
    print("  ILLUSTRATIVE EXAMPLE DATA - not actual trading figures")
    print("=" * 68)
    print()

    layouts = fmcg_layouts()

    # ---- 1. Gross to net: one bridge, three ways of showing it -------------
    total = bridge_from_rows(ROWS, label="Total Business FY26", entitlements=ENTITLEMENTS)

    for key in ("executive", "trade_terms", "diagnostic"):
        print(total.to_text(layouts[key]))
        print()

    # ---- 2. Was any of that spend actually earned? -------------------------
    print(total.to_terms_text())
    print()

    # ---- 3. Why net revenue moved year on year -----------------------------
    movement = pvm_bridge(LAST_YEAR, THIS_YEAR, label="Net Revenue FY26 vs FY25")
    print(movement.to_text(pvm_layout()))
    print()
    print(growth_summary(movement))
    print()
    print(f"  Realised price growth: {price_growth(movement):+.1%}")
    print()

    # ---- 4. The same G2N ledger, sliced by customer ------------------------
    # Net realisation is what the structure exists to produce: it says which
    # accounts are actually paying for the investment they receive.
    print("Net realisation by customer")
    print("-" * 68)
    print(f"  {'Customer':<24}{'Gross':>12}{'Net':>12}{'Realised':>10}{'Resid':>8}")

    for row in ROWS:
        bridge = bridge_from_rows([row], label=row["customer"])
        bridge.reconcile()
        print(
            f"  {row['customer']:<24}"
            f"{bridge.opening_value / 1e6:>11,.1f}m"
            f"{bridge.closing_value / 1e6:>11,.1f}m"
            f"{bridge.closing_value / bridge.opening_value:>10.1%}"
            f"{bridge.residual_share():>8.1%}"
        )

    print("-" * 68)
    print(
        f"  {'Total':<24}"
        f"{total.opening_value / 1e6:>11,.1f}m"
        f"{total.closing_value / 1e6:>11,.1f}m"
        f"{total.closing_value / total.opening_value:>10.1%}"
        f"{total.residual_share():>8.1%}"
    )
    print()

    if args.chart:
        # docs/ is the one PNG path .gitignore keeps, so the images committed to
        # the repo are exactly what this demo produces - they cannot drift.
        # illustrative=True stamps every one of them.
        Path("docs").mkdir(exist_ok=True)
        for key in ("executive", "diagnostic"):
            print(
                "wrote "
                + total.to_chart(
                    layouts[key], f"docs/bridge_{key}.png", illustrative=True
                )
            )
        print(
            "wrote "
            + movement.to_chart(
                pvm_layout(), "docs/bridge_pvm.png", illustrative=True
            )
        )


if __name__ == "__main__":
    main()
