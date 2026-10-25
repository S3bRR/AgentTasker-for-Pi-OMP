"""Shared traditional MCP wire rules; no draft/newer protocol claims."""

import json

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE_BYTES = 8_000_000


def valid_id(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def loads(text):
    def reject_constant(value):
        raise ValueError(f"Non-JSON numeric constant: {value}")

    return json.loads(text, parse_constant=reject_constant)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def validate_initialize(params):
    if not isinstance(params.get("protocolVersion"), str) or not params["protocolVersion"]:
        raise ValueError("protocolVersion must be a non-empty string")
    if not isinstance(params.get("capabilities"), dict):
        raise ValueError("capabilities must be an object")
    info = params.get("clientInfo")
    if not isinstance(info, dict) or any(not isinstance(info.get(key), str) or not info[key] for key in ("name", "version")):
        raise ValueError("clientInfo needs string name and version")
