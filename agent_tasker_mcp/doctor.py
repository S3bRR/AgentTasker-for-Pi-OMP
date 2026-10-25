"""Exercise an actual stdio MCP transport; shell verification is explicit."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

from .installation import read_config


class Probe:
    def __init__(self, entry, timeout=15):
        if entry.get("type", "stdio") != "stdio" or not isinstance(entry.get("command"), str):
            raise ValueError("Doctor requires a trusted stdio MCP entry")
        if entry.get("env"):
            raise ValueError("Doctor does not expand environment/credential expressions; use a plain generated entry")
        args = entry.get("args", [])
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValueError("MCP args must be an array of strings")
        self.timeout, self.counter = timeout, 0
        self.messages, self.errors = queue.Queue(), deque(maxlen=4)
        self.process = subprocess.Popen([entry["command"], *args], cwd=entry.get("cwd"),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name == "posix")
        self.readers = [threading.Thread(target=self._read, daemon=True), threading.Thread(target=self._stderr, daemon=True)]
        for reader in self.readers:
            reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(8_000_001)
                if not line:
                    break
                if len(line) > 8_000_000:
                    raise ValueError("MCP reply exceeds doctor message limit")
                self.messages.put(json.loads(line))
        except Exception as exc:
            self.messages.put(exc)
        finally:
            self.messages.put(EOFError("MCP server exited; verify executable, SSH authentication and host key"))

    def _stderr(self):
        while chunk := self.process.stderr.read(1024):
            self.errors.append(chunk)

    def send(self, method, params=None, *, notification=False):
        self.counter += 1
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            message["id"] = self.counter
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()
        if notification:
            return None
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                reply = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError(f"MCP {method} timed out") from exc
            if isinstance(reply, Exception):
                raise reply
            if reply.get("id") != self.counter:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"MCP {method} timed out")
                continue
            if "error" in reply:
                raise ValueError(f"MCP error: {reply['error']}")
            return reply["result"]

    def call(self, name, arguments):
        result = self.send("tools/call", {"name": name, "arguments": arguments})
        data = result.get("structuredContent")
        if data is None:
            data = json.loads(next(item["text"] for item in result["content"] if item.get("type") == "text"))
        if result.get("isError"):
            raise ValueError(f"{name} failed: {json.dumps(data)}")
        return data

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait(timeout=3)
        finally:
            for reader in self.readers:
                reader.join(timeout=1)
            self.process.stdout.close()
            self.process.stderr.close()


def verify(entry, *, shell_test=False, timeout=15):
    probe = Probe(entry, timeout)
    try:
        initialized = probe.send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "agent-tasker-doctor", "version": "1.0.0"}})
        probe.send("notifications/initialized", notification=True)
        tools = probe.send("tools/list")["tools"]
        names = {tool["name"] for tool in tools}
        required = {"execute", "execute_batch", "get_batch", "cancel_batch", "list_remote_tools"}
        if not required <= names:
            raise ValueError("Server is missing required AgentTasker tools")
        report = {"protocol_ok": True, "server": initialized["serverInfo"], "tools": sorted(names),
                  "shell_test_run": shell_test}
        if shell_test:
            launched = probe.call("execute_batch", {"wait": False, "concurrency": 4, "tasks": [
                {"name": f"job-{i}", "task_type": "shell", "command": f"printf 'PASS job-{i}\\n'; sleep 1", "timeout": 10}
                for i in range(4)]})
            batch_id = launched["batch_id"]
            deadline = time.monotonic() + timeout
            while True:
                result = probe.call("get_batch", {"batch_id": batch_id, "wait_seconds": min(5, timeout), "output_mode": "full"})
                if result["status"] not in {"running", "cancelling"}:
                    break
                if time.monotonic() >= deadline:
                    probe.call("cancel_batch", {"batch_id": batch_id})
                    raise TimeoutError("Shell batch did not finish before the doctor deadline")
            tasks = result["results"]
            if result.get("completed") != 4 or any(t["result"]["exit_code"] != 0 for t in tasks):
                raise ValueError("Not all four test commands completed successfully")
            for i, task in enumerate(tasks):
                if task["result"]["stdout"].strip() != f"PASS job-{i}":
                    raise ValueError("A command result was missing or mixed with another task")
            starts = [datetime.fromisoformat(t["started_at"]) for t in tasks]
            ends = [datetime.fromisoformat(t["completed_at"]) for t in tasks]
            overlap = (min(ends) - max(starts)).total_seconds()
            if overlap <= 0:
                raise ValueError("Commands succeeded but did not demonstrate four-way overlap")
            report.update({"completed": 4, "four_way_overlap": True,
                "overlap_seconds": round(overlap, 3), "batch_seconds": round((max(ends) - min(starts)).total_seconds(), 3),
                "hosts": sorted({t["result"]["host"] for t in tasks}),
                "directories": sorted({t["result"]["cwd"] for t in tasks}),
                "outputs": [t["result"]["stdout"].strip() for t in tasks]})
        return report
    finally:
        probe.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify a trusted MCP config. Does not change configuration. --shell-test explicitly runs four harmless commands on its configured host.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--shell-test", action="store_true", help="Run four printf/sleep shell commands on the configured execution host")
    parser.add_argument("--timeout", type=int, default=15, choices=range(1, 31), metavar="1..30")
    args = parser.parse_args(argv)
    try:
        config, _ = read_config(args.config)
        entry = config.get("mcpServers", {}).get("agent-tasker")
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            raise ValueError("No enabled agent-tasker entry in this config")
        print(json.dumps(verify(entry, shell_test=args.shell_test, timeout=args.timeout), indent=2))
        return 0
    except (ValueError, OSError, TimeoutError, KeyError, StopIteration) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
