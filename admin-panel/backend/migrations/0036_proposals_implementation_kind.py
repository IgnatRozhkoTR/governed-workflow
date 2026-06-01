"""Add implementation_kind column to proposals.

Tracks whether a proposal should be executed automatically by the orchestrator
('auto') or requires a human to carry out the change ('manual'). Defaults to
'manual' so existing rows and new proposals submitted without an explicit kind
follow the conservative path.
"""
from yoyo import step

step("ALTER TABLE proposals ADD COLUMN implementation_kind TEXT NOT NULL DEFAULT 'manual'")
