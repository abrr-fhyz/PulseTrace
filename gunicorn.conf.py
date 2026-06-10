"""Gunicorn config for the Docker image.

`when_ready` runs once in the master process after the listen socket is bound —
the right place to launch the MCP server so it starts exactly once regardless of
how many workers gunicorn forks.
"""
from __future__ import annotations


def when_ready(server):  # noqa: ANN001 - gunicorn hook signature
    from lib.mcp_autostart import ensure_mcp_server
    ensure_mcp_server()
