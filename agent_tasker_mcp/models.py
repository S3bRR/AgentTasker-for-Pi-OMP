"""Shell task identity and bounded server defaults."""
from enum import Enum


class TaskType(Enum):
    SHELL = "shell"


DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_BATCHES = 32
DEFAULT_BATCH_TTL_SECONDS = 3600
DEFAULT_MAX_TASKS = 1000
DEFAULT_MAX_PAYLOAD_BYTES = 1_000_000
