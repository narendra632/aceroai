"""Boundaries with the outside world.

An adapter is the only place allowed to import a third-party client for an external
service. Everything above it takes a small interface instead, which is what lets the whole
test suite run with no credentials and no network — CI has neither.

The rule that makes this worth having: **an adapter never raises past its own boundary in a
shape the caller has to know about**. It translates one vendor's failures into this
application's vocabulary, so a service can express a rule ("a backup that cannot be written
is a failed backup") without also expressing how one particular vendor reports a refused
write.

`services/` says what the rule is. `adapters/` says how the network behaved. Mixing the two
is how a rule quietly acquires a vendor's opinions.
"""
