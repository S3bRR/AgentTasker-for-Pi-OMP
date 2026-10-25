"""AgentTasker MCP package."""

from .models import TaskType

__all__ = [
    "AgentTasker",
    "TaskType",
    "cli",
    "create_server",
    "main",
]


def __getattr__(name: str):
    if name in {"AgentTasker", "cli", "create_server", "main"}:
        from . import server

        value = getattr(server, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
