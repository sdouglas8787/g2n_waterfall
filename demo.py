"""
Worked example: a gross-to-net bridge for an ambient grocery supplier.

The figures are illustrative and invented - the point is the mechanics, not the
numbers. Note that the rows deliberately do not explain the whole deduction:
the actual net settled is lower than the listed deductions imply, so the bridge
derives a residual and reports it rather than absorbing it. That is the normal
state of real trade-spend data, not an edge case.

    python demo.py
    python demo.py --chart      # also writes PNGs (needs matplotlib)
"""

from __future__ import annotations

import argparse

from g2n import bridge_from_rows, fmcg_layouts

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart", action="store_true", help="write waterfall PNGs")
    args = parser.parse_args()

    layouts = fmcg_layouts()

    # ---- One bridge for the whole business, three ways of showing it --------
    total = bridge_from_rows(ROWS, label="Total Business FY26")

    for key in ("executive", "trade_terms", "diagnostic"):
        print(total.to_text(layouts[key]))
        print()

    if args.chart:
        for key in ("executive", "diagnostic"):
            path = total.to_chart(layouts[key], f"bridge_{key}.png")
            print(f"wrote {path}")
        print()

    # ---- The same ledger, sliced by customer -------------------------------
    # Net-to-gross realisation per customer is the number this whole structure
    # exists to produce: it is what says which accounts are actually paying for
    # the investment they receive.
    print("Net realisation by customer")
    print("-" * 64)
    print(f"  {'Customer':<24}{'Gross':>12}{'Net':>12}{'Realised':>10}{'Resid':>8}")

    for row in ROWS:
        bridge = bridge_from_rows([row], label=row["customer"])
        bridge.reconcile()
        realisation = bridge.closing_value / bridge.opening_value
        print(
            f"  {row['customer']:<24}"
            f"{bridge.opening_value:>12,.0f}"
            f"{bridge.closing_value:>12,.0f}"
            f"{realisation:>10.1%}"
            f"{bridge.residual_share():>8.1%}"
        )

    print("-" * 64)
    print(
        f"  {'Total':<24}"
        f"{total.opening_value:>12,.0f}"
        f"{total.closing_value:>12,.0f}"
        f"{total.closing_value / total.opening_value:>10.1%}"
        f"{total.residual_share():>8.1%}"
    )


if __name__ == "__main__":
    main()
