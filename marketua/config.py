"""Runtime configuration: which marketplaces are enabled.

Secrets live in a local ``.env`` file (never committed — see ``.env.example``)
or the process environment. No provider requires a token — OLX, Hotline and
Prom all work without one; any provider can be explicitly disabled with
``MARKETUA_DISABLE_PROVIDERS``.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Fills os.environ from .env if the file exists; otherwise a no-op.
load_dotenv()


def provider_enabled(name: str) -> bool:
    """True if the marketplace should be exposed as an MCP tool."""
    disabled = {
        p.strip()
        for p in os.environ.get("MARKETUA_DISABLE_PROVIDERS", "").split(",")
        if p.strip()
    }
    return name not in disabled
