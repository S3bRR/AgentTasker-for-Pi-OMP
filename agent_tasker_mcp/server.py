"""Shell-only stdio MCP server and bounded parallel scheduler."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from graphlib import CycleError, TopologicalSorter
import os
import signal
import sys
from threading import Event, Lock, local
import time
import uuid

from .batches import BatchManager
from .shell import ShellExecutor
from .models import DEFAULT_MAX_BATCHES, DEFAULT_BATCH_TTL_SECONDS, DEFAULT_MAX_PAYLOAD_BYTES, DEFAULT_MAX_TASKS, DEFAULT_MAX_WORKERS, TaskType
from .protocol import MAX_MESSAGE_BYTES, PROTOCOLS, dumps, loads, valid_id, validate_initialize
from .registry import TASK_PROPERTIES, cancel_batch_schema, check_keys, execute_batch_schema, execute_schema, get_batch_schema, option, output_schema, validate_name, validate_payload
from .version import package_version

SERVER_NAME, SERVER_VERSION = "agent-tasker", package_version()
SUPPORTED_PROTOCOL_VERSIONS = PROTOCOLS


class _LifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class _PreparedTask:
    id: str
    name: str
    task_type: TaskType
    payload: dict
    depends_on: tuple = ()


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _now_iso():
    return datetime.now().isoformat()


def _jsonrpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", **({"id": request_id} if request_id is not None else {}), "error": {"code": code, "message": message}}


def _tool_result(payload, *, is_error=False, structured=True):
    content = [{"type": "text", "text": dumps(payload)}]
    return {"content": content, **({"structuredContent": payload} if structured else {}), "isError": is_error}


def _tool_payload_failed(payload):
    return payload.get("status") == "failed" or payload.get("task", {}).get("status") == "failed" or any(task["status"] == "failed" for task in payload.get("results", []))


class AgentTasker:
    def __init__(self, max_workers=DEFAULT_MAX_WORKERS, max_tasks=DEFAULT_MAX_TASKS,
                 max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES, allow_shell=False, shell_cwd=None):
        for name, value in (("max_workers", max_workers), ("max_tasks", max_tasks), ("max_payload_bytes", max_payload_bytes)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"'{name}' must be a positive integer")
        if max_workers > 256:
            raise ValueError("max_workers must not exceed 256")
        self.max_workers, self.max_tasks, self.max_payload_bytes = max_workers, max_tasks, max_payload_bytes
        self.shutdown = Event()
        self.shell = ShellExecutor(shell_cwd) if allow_shell else None
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tasker-work")

    def close(self):
        self.shutdown.set()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def validate_concurrency(self, value):
        if value is None:
            return self.max_workers
        return option({"concurrency": value}, "concurrency", maximum=self.max_workers)

    def _prepare_tasks(self, definitions):
        if len(definitions) > self.max_tasks:
            raise ValueError(f"Task limit reached ({self.max_tasks})")
        prepared, names = [], set()
        for definition in definitions:
            if len(definition) not in (3, 4):
                raise ValueError("Task definition needs name, type, payload, and optional dependencies")
            name, kind, source = definition[:3]
            name = validate_name(name)
            if name in names:
                raise ValueError(f"Duplicate task name: {name}")
            names.add(name)
            if self.shell is None:
                raise ValueError("Shell execution is disabled; start the server with --allow-shell to opt in")
            payload = validate_payload(kind, source)
            if "cwd" in payload:
                self.shell.validate_cwd(payload["cwd"])
            if len(dumps(payload).encode("utf-8")) > self.max_payload_bytes:
                raise ValueError("Payload too large")
            dependencies = definition[3] if len(definition) == 4 else []
            if not isinstance(dependencies, list):
                raise ValueError("'depends_on' must be an array of task names")
            dependencies = tuple(dict.fromkeys(validate_name(item) for item in dependencies))
            prepared.append(_PreparedTask(uuid.uuid4().hex[:12], name, kind, payload, dependencies))
        pending = {task.name: set(task.depends_on) for task in prepared}
        for name, dependencies in pending.items():
            if name in dependencies or dependencies - names:
                raise ValueError(f"Invalid or unknown dependency for '{name}'")
        try:
            tuple(TopologicalSorter(pending).static_order())
        except CycleError as exc:
            raise ValueError("Task dependencies must be acyclic") from exc
        return prepared

    @staticmethod
    def _record(task, status, result=None, error=None):
        return {"id": task.id, "name": task.name, "task_type": task.task_type.value, "status": status, "result": result, "error": error}

    def _execute_task(self, task, cancel=None):
        started, result, error, status = time.perf_counter(), None, None, "completed"
        started_at = _now_iso()
        try:
            result = self.shell.run(task.payload, cancel=cancel, shutdown=self.shutdown)
            if result["cancelled"]:
                status, error = "cancelled", "Shell command cancelled"
            elif result["timed_out"]:
                status, error = "failed", "Shell command timed out"
            elif result["exit_code"] != 0:
                status, error = "failed", f"Shell exited with code {result['exit_code']}"
        except Exception as exc:
            error, status = str(exc), "failed"
        return {**self._record(task, status, result, error), "started_at": started_at,
                "completed_at": _now_iso(), "duration_seconds": round(time.perf_counter() - started, 3)}

    def execute_tasks(self, definitions, *, concurrency=None, cancel=None):
        return self._execute_prepared(self._prepare_tasks(definitions), concurrency=self.validate_concurrency(concurrency), cancel=cancel)

    def _execute_prepared(self, prepared, *, concurrency, cancel=None, on_update=None):
        cancel = cancel if cancel is not None else Event()
        by_name = {task.name: task for task in prepared}
        ordered = dict.fromkeys(by_name)
        waiting = {task.name: len(task.depends_on) for task in prepared}
        blocked = {task.name: [] for task in prepared}
        children = {task.name: [] for task in prepared}
        for task in prepared:
            for dependency in task.depends_on:
                children[dependency].append(task.name)
        ready = deque(name for name, count in waiting.items() if not count)
        futures = {}
        started_at = _now_iso()

        def publish(record):
            if on_update:
                on_update(record)

        def run(task):
            if cancel.is_set():
                return self._record(task, "cancelled", error="Cancelled before starting")
            publish(self._record(task, "running"))
            return self._execute_task(task, cancel=cancel)

        def resolve(name, record):
            queue = deque([(name, record)])
            while queue:
                name, record = queue.popleft()
                if ordered[name] is not None:
                    continue
                ordered[name] = record
                publish(record)
                if cancel.is_set():
                    continue
                for child in children[name]:
                    waiting[child] -= 1
                    if record["status"] != "completed":
                        blocked[child].append(name)
                    if not waiting[child]:
                        if blocked[child]:
                            queue.append((child, self._record(by_name[child], "failed", error="Blocked by failed dependencies: " + ", ".join(blocked[child]))))
                        else:
                            ready.append(child)

        while True:
            if cancel.is_set():
                ready.clear()
                for future in list(futures):
                    if future.cancel():
                        futures.pop(future)
                active = set(futures.values())
                for name, record in ordered.items():
                    if record is None and name not in active:
                        ordered[name] = self._record(by_name[name], "cancelled", error="Batch cancelled")
                        publish(ordered[name])
            while ready and len(futures) < concurrency and not cancel.is_set():
                name = ready.popleft()
                futures[self.executor.submit(run, by_name[name])] = name
            if not futures:
                if ready and cancel.is_set():
                    continue  # Cancellation raced initial submission.
                break
            done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                name = futures.pop(future)
                try:
                    record = future.result()
                except Exception as exc:
                    record = self._record(by_name[name], "failed", error=str(exc))
                resolve(name, record)
        results = list(ordered.values())
        counts = {status: sum(item["status"] == status for item in results) for status in ("completed", "failed", "cancelled")}
        return {"total": len(results), **counts, "concurrency": concurrency, "started_at": started_at,
                "completed_at": _now_iso(), "status": "cancelled" if counts["cancelled"] else "failed" if counts["failed"] else "completed", "results": results}


def _task_definition(source, index, *, single=False):
    if not isinstance(source, dict):
        raise ValueError("Each task must be an object")
    try:
        kind = TaskType(source["task_type"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("task_type must be shell") from exc
    check_keys(source, {**TASK_PROPERTIES, **({"output_mode": {}} if single else {})})
    name = source.get("name", f"{kind.value}_{index + 1}")
    return name, kind, source, source.get("depends_on", [])


def _batch_definitions(arguments):
    tasks = arguments.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("'tasks' must be a non-empty array")
    return [_task_definition(task, index) for index, task in enumerate(tasks)]


def _output_mode(arguments):
    return option(arguments, "output_mode")


def _format_execution(raw, *, output_mode):
    if output_mode == "full":
        return raw
    result = {key: raw[key] for key in ("batch_id", "status", "error") if raw.get(key) is not None}
    if "batch_id" in raw:
        result["progress"] = {"done": raw["completed"] + raw["failed"] + raw["cancelled"], "total": raw["total"]}
    result["results"] = [{key: task[key] for key in ("name", "status", "error", "result") if task.get(key) is not None}
                         for task in raw["results"] if task["status"] not in {"queued", "running"}]
    return result


_PUBLIC_TOOL_SPECS = (
    ("execute", "Run one opt-in shell command on the server host.", execute_schema),
    ("execute_batch", "Run independent tasks in parallel, including opt-in shell commands. Use depends_on for a plan; concurrency sets the limit, wait=false returns a batch_id immediately.", execute_batch_schema),
    ("get_batch", "Collect background progress and finished results; full mode includes unfinished placeholders.", get_batch_schema),
    ("cancel_batch", "Cancel queued tasks and terminate running shell process groups.", cancel_batch_schema),
)


TOOL_ANNOTATIONS = {
    "execute": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    "execute_batch": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    "get_batch": {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    "cancel_batch": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
}


def _tool_catalog():
    return [(name, description, schema()) for name, description, schema in _PUBLIC_TOOL_SPECS]


class MCPServer:
    def __init__(self, max_workers=DEFAULT_MAX_WORKERS, allow_shell=False, shell_cwd=None):
        self.tasker = AgentTasker(max_workers=max_workers, allow_shell=allow_shell, shell_cwd=shell_cwd,
            max_tasks=_env_int("AGENT_TASKER_MAX_TASKS", DEFAULT_MAX_TASKS),
            max_payload_bytes=_env_int("AGENT_TASKER_MAX_PAYLOAD_BYTES", DEFAULT_MAX_PAYLOAD_BYTES))
        self.batches = BatchManager(self.tasker, max_batches=_env_int("AGENT_TASKER_MAX_BATCHES", DEFAULT_MAX_BATCHES),
                                    ttl_seconds=_env_int("AGENT_TASKER_BATCH_TTL_SECONDS", DEFAULT_BATCH_TTL_SECONDS))
        self._initialize_sent = self._ready = False
        self._protocol_version = PROTOCOLS[0]
        self._request_context, self._request_lock, self._inflight = local(), Lock(), {}
        self.handlers = {"execute": self._execute, "execute_batch": self._execute_batch, "get_batch": self._get_batch,
                         "cancel_batch": self._cancel_batch}

    def close(self):
        self.batches.close()
        self.tasker.close()

    def _list_tools(self):
        tools = []
        for name, description, schema in _tool_catalog():
            if name == "execute_batch":
                schema["properties"]["concurrency"].update(maximum=self.tasker.max_workers, default=self.tasker.max_workers)
                schema["properties"]["tasks"]["maxItems"] = self.tasker.max_tasks
            tool = {"name": name, "title": name.replace("_", " ").title(), "description": description, "inputSchema": schema}
            if self._protocol_version >= "2025-03-26":
                tool["annotations"] = TOOL_ANNOTATIONS[name]
            if self._protocol_version >= "2025-06-18":
                tool["outputSchema"] = output_schema(name)
            tools.append(tool)
        return {"tools": tools}

    def _execute(self, arguments):
        mode = _output_mode(arguments)
        raw = self.tasker.execute_tasks([_task_definition(arguments, 0, single=True)], cancel=getattr(self._request_context, "cancel", None))
        result = _format_execution(raw, output_mode=mode)
        return {"task": result["results"][0]}

    def _execute_batch(self, arguments):
        should_wait = option(arguments, "wait")
        mode = _output_mode(arguments)
        concurrency = self.tasker.validate_concurrency(option(arguments, "concurrency") if "concurrency" in arguments else None)
        definitions = _batch_definitions(arguments)
        raw = self.tasker.execute_tasks(definitions, concurrency=concurrency, cancel=getattr(self._request_context, "cancel", None)) if should_wait else self.batches.submit(definitions, concurrency=concurrency)
        if not should_wait:
            self._request_context.batch_id = raw["batch_id"]
        return _format_execution(raw, output_mode=mode)

    def _get_batch(self, arguments):
        seconds = option(arguments, "wait_seconds")
        mode = _output_mode(arguments)
        return _format_execution(self.batches.get(validate_name(arguments.get("batch_id")), wait_seconds=seconds,
                                cancel=getattr(self._request_context, "cancel", None)), output_mode=mode)

    def _cancel_batch(self, arguments):
        return _format_execution(self.batches.cancel(validate_name(arguments.get("batch_id"))), output_mode="compact")

    def _require_ready(self):
        if not self._initialize_sent or not self._ready:
            raise _LifecycleError("Server not initialized")

    def _handle_notification(self, method, params):
        if method == "notifications/initialized" and self._initialize_sent:
            self._ready = True
        elif method == "notifications/cancelled" and valid_id(params.get("requestId")):
            with self._request_lock:
                cancel = self._inflight.get(params["requestId"])
                if cancel is not None:
                    cancel.set()

    def _handle_method(self, method, params):
        if method == "initialize":
            if self._initialize_sent:
                raise ValueError("initialize may only be called once per session")
            validate_initialize(params)
            requested = params["protocolVersion"]
            self._protocol_version = requested if requested in PROTOCOLS else PROTOCOLS[0]
            self._initialize_sent, self._ready = True, False
            return {"protocolVersion": self._protocol_version, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": f"Plan shell work with execute_batch (up to {self.tasker.max_workers} concurrent jobs). "
                    "wait=false returns a batch_id immediately; collect it with get_batch and stop unwanted work with cancel_batch. "
                    "Use depends_on for ordering. Check every exit code, host, cwd and output. Results are session-local, not durable. "
                    + (f"Shell ENABLED on the server host; default cwd: {self.tasker.shell.cwd}. " if self.tasker.shell else "Shell execution is disabled. ")
                    + "Commands are arbitrary code, not sandboxed. Client SSH routing is not inherited; never silently fall back locally."}
        if method == "ping":
            return {}
        if method == "tools/list":
            self._require_ready()
            if "cursor" in params:
                raise ValueError("This catalog is returned in one page; no cursor is valid")
            return self._list_tools()
        if method == "tools/call":
            self._require_ready()
            name, arguments = params.get("name"), params.get("arguments", {})
            if not isinstance(name, str) or name not in self.handlers:
                raise ValueError(f"Unknown tool: {name}")
            if not isinstance(arguments, dict):
                raise ValueError("'arguments' must be an object")
            if "task" in params:
                raise ValueError("Native MCP Tasks are not supported; use execute_batch with wait=false")
            if "_meta" in params and not isinstance(params["_meta"], dict):
                raise ValueError("_meta must be an object")
            structured = self._protocol_version >= "2025-06-18"
            try:
                schema = next(schema() for tool, _, schema in _PUBLIC_TOOL_SPECS if tool == name)
                check_keys(arguments, schema["properties"])
                payload = self.handlers[name](arguments)
                return _tool_result(payload, is_error=_tool_payload_failed(payload), structured=structured)
            except Exception as exc:
                return _tool_result({"error": str(exc)}, is_error=True, structured=structured)
        raise KeyError(method)

    def handle_message(self, message):
        if isinstance(message, list) and message and self._initialize_sent and self._protocol_version < "2025-06-18":
            responses = [self.handle_message(item) if isinstance(item, dict) else _jsonrpc_error(None, -32600, "Invalid request") for item in message]
            return [response for response in responses if response is not None] or None
        if not isinstance(message, dict):
            return _jsonrpc_error(None, -32600, "Invalid request")
        if "method" not in message and ("result" in message or "error" in message):
            return None  # No server-initiated requests: ignore stray responses, never create error loops.
        request_id = message.get("id")
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str) or ("id" in message and not valid_id(request_id)):
            return _jsonrpc_error(request_id if valid_id(request_id) else None, -32600, "Invalid request")
        method, params = message["method"], message.get("params", {})
        if not isinstance(params, dict):
            return _jsonrpc_error(request_id, -32602, "Invalid params") if "id" in message else None
        if "id" not in message:
            self._handle_notification(method, params)
            return None
        request_id = message["id"]
        try:
            return _jsonrpc_result(request_id, self._handle_method(method, params))
        except KeyError:
            return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")
        except _LifecycleError as exc:
            return _jsonrpc_error(request_id, -32002, str(exc))
        except ValueError as exc:
            return _jsonrpc_error(request_id, -32602, str(exc))
        except Exception as exc:
            return _jsonrpc_error(request_id, -32603, str(exc))

    def serve_stdio(self, stdin=sys.stdin, stdout=sys.stdout):
        # Coordination is separate from execution, so synchronous calls cannot block ping/cancellation.
        requests = ThreadPoolExecutor(max_workers=self.tasker.max_workers, thread_name_prefix="tasker-request")
        write_lock = Lock()

        def write(response):
            if response is not None:
                with write_lock:
                    stdout.write(dumps(response) + "\n")
                    stdout.flush()

        def call(message, cancel):
            self._request_context.cancel, self._request_context.batch_id = cancel, None
            try:
                if cancel.is_set():
                    return
                response = self.handle_message(message)
                with self._request_lock:
                    if cancel.is_set():
                        batch_id = self._request_context.batch_id
                        if batch_id:
                            self.batches.cancel(batch_id)
                    else:
                        write(response)
            finally:
                with self._request_lock:
                    self._inflight.pop(message["id"], None)

        try:
            while line := stdin.readline(MAX_MESSAGE_BYTES + 1):
                if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    while line and not line.endswith("\n"):
                        line = stdin.readline(MAX_MESSAGE_BYTES + 1)
                    write(_jsonrpc_error(None, -32600, "MCP message exceeds 8MB"))
                    continue
                if not line.strip():
                    continue
                try:
                    message = loads(line)
                except (ValueError, RecursionError):
                    write(_jsonrpc_error(None, -32700, "Parse error"))
                    continue
                if self._ready and isinstance(message, dict) and message.get("jsonrpc") == "2.0" and message.get("method") == "tools/call" and valid_id(message.get("id")):
                    with self._request_lock:
                        if message["id"] in self._inflight:
                            write(_jsonrpc_error(message["id"], -32600, "Request ID is already in flight"))
                        elif len(self._inflight) >= 2 * self.tasker.max_workers:
                            write(_jsonrpc_error(message["id"], -32000, "Too many in-flight requests"))
                        else:
                            cancel = self._inflight[message["id"]] = Event()
                            requests.submit(call, message, cancel)
                else:
                    write(self.handle_message(message))
        finally:
            with self._request_lock:
                for cancel in self._inflight.values():
                    cancel.set()
            requests.shutdown(wait=True)
            self.close()


def create_server(max_workers=DEFAULT_MAX_WORKERS, **options):
    return MCPServer(max_workers, **options)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AgentTasker: parallel background shell jobs for Pi and OMP")
    parser.add_argument("--workers", "-w", type=int, default=DEFAULT_MAX_WORKERS, help="Concurrent workers (default: 4, max: 256)")
    parser.add_argument("--allow-shell", action="store_true", help="Enable arbitrary Bash commands on this host (not sandboxed)")
    parser.add_argument("--shell-cwd", help="Default absolute execution directory; requires --allow-shell")
    args = parser.parse_args(argv)
    if args.shell_cwd and not args.allow_shell:
        parser.error("--shell-cwd requires --allow-shell")
    try:
        server = create_server(args.workers, allow_shell=args.allow_shell, shell_cwd=args.shell_cwd)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_stdio()
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


def cli():
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
