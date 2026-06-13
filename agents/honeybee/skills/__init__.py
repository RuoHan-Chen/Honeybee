"""MCP-style pluggable skill modules.

Each skill exports `register(orchestrator)` and may hook into market topics
to inject custom prompts, fetchers, or post-trade analyses.
"""
from . import sports, politics

ALL_SKILLS = [sports, politics]
