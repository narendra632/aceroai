"""The investment ledger: what is held, what it cost, and what it is worth.

**One idea holds this package together: transactions are facts, everything else is a
function of them.** A position is not a row that gets updated when you buy more — it is
`fold(transactions)`. A cost basis is not maintained; it is computed. A portfolio value is
not stored; it is positions × latest prices, evaluated when someone looks.

That costs a little arithmetic on every read and buys the property that matters: **nothing
derived can drift out of step with what actually happened.** Every portfolio tracker that has
ever shown a wrong holding did so because it stored a number and missed an update.

    portfolio.py   the fold — transactions to positions
    valuation.py   positions x prices, with staleness         (later in this change)
    returns.py     XIRR, TWR, currency decomposition          (later in this change)
    costmodel.py   charges, from a dated schedule             (later in this change)
    taxrules.py    lots, holding periods, flags               (later in this change)
    entry.py       the one write path                         (later in this change)
"""
