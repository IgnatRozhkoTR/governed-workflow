"""Drop the legacy improvements subsystem.

Improvements were the first attempt at recording agent-flagged workflow
gaps; the proposals pipeline (table ``proposals`` + the four
``workspace_*_proposal`` MCP tools) has fully replaced it. No agent has
the improvement tools granted, the admin UI never wires up the dead
``improvements.js`` widget, and the global Setup-page widget was a
companion of this same dead path. Drop the storage so the schema matches
reality.
"""
from yoyo import step


step("DROP TABLE IF EXISTS improvements")
