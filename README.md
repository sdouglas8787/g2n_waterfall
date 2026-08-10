# Gross-to-Net Waterfall

A small Python module for building gross-to-net bridges that reconcile by construction.

A G2N bridge walks from gross sales to net sales through trade terms, promotional
investment and other deductions. It is one of the most common artefacts in commercial
finance and one of the most commonly wrong. This module encodes three disciplines that
stop it going wrong.

The core has **no third-party dependencies**. Charting and Excel export are optional.

---

## The three ideas

**1. Movements and running positions are different types.**

A bridge mixes deductions (which belong in the walk) with subtotals like *Invoiced Sales*
(which do not). Adding a subtotal to the walk silently double counts everything above it —
the single most common G2N bug, and an invisible one, because the chart still looks fine.
Here the distinction is a type, the summation only touches movements, and a layout that
includes a position raises rather than renders.

**2. The residual is a first-class number.**

Source data never carries every pricing effect. The gap between the deductions you can
explain and the net you actually settled at is the residual. A bridge that absorbs it into
the nearest bar is lying about its own accuracy. Here the residual is derived rather than
supplied, is always a named step, and is reported as a share of gross — the bridge's own
error rate. A residual over a couple of percent means the deduction taxonomy is incomplete,
and no amount of chart polish makes the walk trustworthy until that is understood.

**3. One ledger, several audiences.**

An exec wants five bars. A customer conversation wants trade-terms wording. An analyst
wants every atomic movement. Rebuilding the bridge per audience is how the three versions
drift apart and someone presents a net that nobody else recognises. Here layouts are views
over a single ledger, and every layout is checked to consume every movement and close on
the same net.

A layout may combine steps into one bar for presentation — but a step named in
`always_disclose` must still be published as a standalone figure. Combining bars is a
presentation choice; it must never be a way to make an uncomfortable number invisible.

---

## What it looks like

```
Total Business FY26 - Executive
----------------------------------------------------------------
= Gross Sales                  15,920,000
  On-invoice Terms             -1,762,000
                               14,158,000  (running)
  Promotional Investment       -1,522,150
                               12,635,850  (running)
  Other Trade Spend              -717,850
                               11,918,000  (running)
= Net Sales                    11,918,000
----------------------------------------------------------------
  Residual as % of gross          -0.60%
! Other Adjustments (disclosed)        -96,140
```

The same ledger, sliced by customer. Net realisation is what the structure exists to
produce — it says which accounts are actually paying for the investment they receive:

```
  Customer                       Gross         Net  Realised   Resid
  National Multiple A        4,820,000   3,082,400     64.0%   -1.0%
  National Multiple B        3,640,000   2,524,900     69.4%   -0.6%
  Discounter C               2,150,000   1,735,600     80.7%   -0.5%
  Own-label Contract D       5,310,000   4,575,100     86.2%   -0.3%
----------------------------------------------------------------
  Total                     15,920,000  11,918,000     74.9%   -0.6%
```

---

## Usage

```python
from g2n import bridge_from_rows, fmcg_layouts

bridge = bridge_from_rows(rows, label="Total Business FY26")
layouts = fmcg_layouts()

print(bridge.to_text(layouts["executive"]))
bridge.to_chart(layouts["diagnostic"], "bridge.png")   # needs matplotlib

bridge.residual                # the unexplained gap, in currency
bridge.residual_share()        # as a share of gross
bridge.disclosures(layout)     # figures a combined bar must not hide
```

Defining your own deduction taxonomy is a data change, not a code change:

```python
from g2n import Step, Kind, Ledger, Bridge, Layout

steps = (
    Step("GROSS",    "Gross Sales",   Kind.OPENING,  "Gross"),
    Step("REBATE",   "Volume Rebate", Kind.MOVEMENT, "On-invoice"),
    Step("INVOICED", "Invoiced Sales", Kind.POSITION, "Subtotal"),   # never summed
    Step("PROMO",    "Promotions",    Kind.MOVEMENT, "Off-invoice"),
    Step("OTHER",    "Other",         Kind.MOVEMENT, "Off-invoice", is_residual=True),
    Step("NET",      "Net Sales",     Kind.CLOSING,  "Net"),
)
```

The bundled `FMCG_TRADE_TERMS` ledger is a conventional starting point, not a standard.

---

## Running it

```bash
python demo.py                 # worked example, three layouts
python demo.py --chart         # also writes PNGs (pip install matplotlib)
python -m pytest test_g2n.py   # 15 tests
```

The tests are not coverage tests. Each one pins a specific way a bridge goes wrong in
practice: a subtotal added as a movement, a deduction dropped from one audience's view,
a residual quietly absorbed, a step counted twice.

---

## Notes

The figures in `demo.py` are illustrative and invented. They deliberately do not fully
explain the settled net, so the demo shows a real residual rather than a tidy zero — that
is the normal state of trade-spend data, not an edge case.

Written by Stuart Douglas. Built from experience implementing pricing and gross-to-net
reporting in a manufacturing business; the module itself is general-purpose and contains
no employer data, configuration or code.
