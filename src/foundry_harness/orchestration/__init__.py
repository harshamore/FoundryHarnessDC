"""Substrate contracts (spec.md §4.4, §8) that agent roles depend on.

Roles depend only on these contracts, never on a concrete provider (US-13),
so any datastore/queue/sandbox implementation satisfying them is
substitutable without redesigning a role.
"""
