"""Stub backend for C2 (No Review) — not yet implemented.

See spec §5: C2–C7 are stubs so the runner/registry/storage design is
proven end-to-end against C1 before each remaining condition is built as
its own follow-up task.
"""

from experiments.pipeline.backends.base import NotImplementedBackend

BACKEND = NotImplementedBackend("C2")
