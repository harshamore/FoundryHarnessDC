"""Guardrails: the Foundry Constitution as an importable, checkable object.

See constitution.py for the eleven principles. See
.specify/memory/constitution.md for the full upstream text (governance,
amendment process, versioning policy) this module is derived from.
"""

from foundry_harness.guardrails.constitution import CONSTITUTION, Principle

__all__ = ["CONSTITUTION", "Principle"]
