"""Provider-neutral POS integration contracts.

The production QuickResto flow remains in ``app.services.integrations`` until
the stage-two compatibility adapter is ready.  Keeping this package free of
runtime side effects lets the canonical foundation ship without changing the
existing import path.
"""
