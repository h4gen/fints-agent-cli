#!/usr/bin/env python3
"""Backward-compatible entrypoint. Use fints_agent_cli instead."""

from fints_agent_cli import *  # noqa: F401,F403
from fints_agent_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
