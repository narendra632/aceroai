"""Market data — where prices come from. Investments Phase 1b.

One adapter per source (`angel_one`, `nse`, `coingecko`, `twelve_data`, `amfi`), each knowing
only how to ask its source and parse the answer, plus `feed`, the only module that decides
what to fetch and writes observations. See `openspec/changes/add-market-data/design.md`.
"""
