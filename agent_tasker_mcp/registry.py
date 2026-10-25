"""One manifest for shell schemas and strict argument validation."""
from copy import deepcopy
from .models import TaskType


def field(kind, **constraints):
    return {"type": kind, **constraints}


FIELDS = {
    "command": field("string", minLength=1, description="Bash on the MCP server host; no retries; requires --allow-shell"),
    "cwd": field("string", minLength=1, description="Existing absolute directory on the execution host"),
    "env": field("object", additionalProperties=field("string")),
    "timeout": field("integer", minimum=1, default=30),
    "max_output_bytes": field("integer", minimum=1, maximum=65536, default=8192, description="Retained tail bytes per stream"),
}
CONTROL_FIELDS = {
    "output_mode": field("string", enum=["compact", "full"], default="compact"),
    "concurrency": field("integer", minimum=1),
    "wait": field("boolean", default=True, description="False returns a background batch_id immediately"),
    "wait_seconds": field("integer", minimum=0, maximum=30, default=0),
}
TASK_PROPERTIES = {
    "name": field("string", minLength=1),
    "task_type": field("string", enum=["shell"]),
    **FIELDS,
    "depends_on": field("array", items=field("string", minLength=1)),
}


def validate_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a non-empty name")
    return value.strip()


def _validate(value, spec, path):
    kind = spec["type"]
    expected = {"string": str, "boolean": bool, "integer": int, "array": list, "object": dict}[kind]
    if not isinstance(value, expected) or (kind == "integer" and isinstance(value, bool)):
        raise ValueError(f"'{path}' must be a {kind}")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f"'{path}' must be one of {spec['enum']}")
    for bound, compare in (("minimum", lambda a, b: a < b), ("maximum", lambda a, b: a > b)):
        if bound in spec and compare(value, spec[bound]):
            raise ValueError(f"'{path}' violates {bound} {spec[bound]}")
    if spec.get("minLength") and not value.strip():
        raise ValueError(f"'{path}' must be non-empty")
    if kind == "array":
        if len(value) < spec.get("minItems", 0):
            raise ValueError(f"'{path}' must be non-empty")
        for item in value:
            _validate(item, spec["items"], path)
    if kind == "object":
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"'{path}' keys must be strings")
            _validate(item, spec["additionalProperties"], f"{path}.{key}")


def validate_payload(task_type, source):
    if task_type != TaskType.SHELL:
        raise ValueError("Only shell tasks are supported")
    if "command" not in source:
        raise ValueError("'command' is required for shell")
    payload = {key: deepcopy(source.get(key, spec.get("default"))) for key, spec in FIELDS.items()
               if key in source or "default" in spec}
    for key, value in payload.items():
        _validate(value, FIELDS[key], key)
    for key, value in payload.get("env", {}).items():
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise ValueError("Invalid shell environment name/value")
    if "\x00" in payload["command"] or "\x00" in payload.get("cwd", ""):
        raise ValueError("Shell command/cwd cannot contain NUL")
    return payload


def option(arguments, name, **bounds):
    spec = {**CONTROL_FIELDS[name], **bounds}
    value = arguments.get(name, spec.get("default"))
    _validate(value, spec, name)
    return value


def check_keys(arguments, properties):
    unknown = arguments.keys() - properties.keys()
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")


def execute_schema():
    return field("object", properties=deepcopy({**TASK_PROPERTIES, "output_mode": CONTROL_FIELDS["output_mode"]}),
                 required=["task_type", "command"], additionalProperties=False)


def execute_batch_schema():
    task = field("object", properties=deepcopy(TASK_PROPERTIES), required=["task_type", "command"], additionalProperties=False)
    return field("object", properties={"tasks": field("array", minItems=1, items=task),
        **deepcopy({key: CONTROL_FIELDS[key] for key in ("concurrency", "wait", "output_mode")})},
        required=["tasks"], additionalProperties=False)


def get_batch_schema():
    return field("object", properties={"batch_id": field("string", minLength=1),
        **deepcopy({key: CONTROL_FIELDS[key] for key in ("wait_seconds", "output_mode")})},
        required=["batch_id"], additionalProperties=False)


def cancel_batch_schema():
    return field("object", properties={"batch_id": field("string", minLength=1)}, required=["batch_id"], additionalProperties=False)


def output_schema(name):
    required = ["task"] if name == "execute" else ["results"]
    if name in {"get_batch", "cancel_batch"}:
        required.append("batch_id")
    return field("object", properties={"task": field("object"), "results": field("array", items=field("object")),
        "batch_id": field("string"), "status": field("string"), "error": field("string")},
        anyOf=[{"required": required}, {"required": ["error"]}])
