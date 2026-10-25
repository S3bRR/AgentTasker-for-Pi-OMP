"""Real subprocess coverage: no network, credentials, or external targets."""

import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agent_tasker_mcp.configuration import server_args
from agent_tasker_mcp.models import TaskType
from agent_tasker_mcp.registry import validate_payload
from agent_tasker_mcp.server import MCPServer, main


def python_command(code):
    return shlex.join([sys.executable, "-c", code])


@unittest.skipUnless(os.name == "posix", "POSIX process groups required")
class ShellTests(unittest.TestCase):
    def server(self, **kwargs):
        server = MCPServer(allow_shell=True, **kwargs)
        self.addCleanup(server.close)
        return server

    def task(self, command, **options):
        return {"task_type": "shell", "command": command, **options}

    def execute(self, server, command, **options):
        return server._execute({**self.task(command, **options), "output_mode": "full"})["task"]

    def collect(self, server, batch):
        return server._get_batch({"batch_id": batch["batch_id"], "wait_seconds": 10, "output_mode": "full"})

    def test_shell_disabled_by_default_and_atomic_batch_validation(self):
        server = MCPServer()
        self.addCleanup(server.close)
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.execute(server, "printf forbidden")
        server = self.server()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "unexpected"
            with self.assertRaises(ValueError):
                server._execute_batch({"tasks": [self.task(f"touch {shlex.quote(str(marker))}"),
                    self.task("true", cwd="relative/path")], "wait": False})
            self.assertFalse(marker.exists())

    def test_four_real_processes_overlap_in_background(self):
        server = self.server(max_workers=4)
        with tempfile.TemporaryDirectory() as directory:
            code = ("from pathlib import Path; import time,sys; "
                    "p=Path('.'); (p/sys.argv[1]).touch(); "
                    "deadline=time.monotonic()+5\n"
                    "while len(list(p.glob('ready-*')))<4 and time.monotonic()<deadline: time.sleep(.01)\n"
                    "assert len(list(p.glob('ready-*')))==4, 'commands were serialized'\n"
                    "print(sys.argv[1])")
            tasks = [self.task(python_command(code) + f" ready-{i}", name=f"job-{i}", cwd=directory, timeout=8) for i in range(4)]
            batch = server._execute_batch({"tasks": tasks, "concurrency": 4, "wait": False, "output_mode": "full"})
            self.assertIn("batch_id", batch)
            result = self.collect(server, batch)
            self.assertEqual(result["completed"], 4, result)
            for i, task in enumerate(result["results"]):
                self.assertEqual(task["result"]["stdout"].strip(), f"ready-{i}")
                self.assertEqual(task["result"]["cwd"], str(Path(directory).resolve()))
                self.assertTrue(task["result"]["host"])

    def test_global_worker_cap_across_batches(self):
        server = self.server(max_workers=2)
        # Observe actual shell starts, across two independent background batches.
        from agent_tasker_mcp.executors.shell import ShellExecutor
        original = ShellExecutor.run
        lock = threading.Lock()
        active, peak = 0, 0
        barrier = threading.Barrier(2)

        def run(executor, *args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(5)
                return original(executor, *args, **kwargs)
            finally:
                with lock:
                    active -= 1

        with patch.object(ShellExecutor, "run", run):
            batches = [server._execute_batch({"tasks": [self.task("sleep .05", name=str(i)) for i in range(4)],
                       "wait": False}) for _ in range(2)]
            for batch in batches:
                self.assertEqual(self.collect(server, batch)["completed"], 4)
        self.assertEqual(peak, 2)

    def test_stdout_stderr_exit_and_failed_dependencies(self):
        server = self.server()
        result = server._execute_batch({"tasks": [
            self.task("printf out; printf err >&2; exit 7", name="fail"),
            self.task("printf should-not-run", name="blocked", depends_on=["fail"]),
            self.task("printf independent", name="ok"),
        ], "output_mode": "full"})
        self.assertEqual((result["failed"], result["completed"]), (2, 1))
        out = result["results"][0]["result"]
        self.assertEqual((out["stdout"], out["stderr"], out["exit_code"]), ("out", "err", 7))
        self.assertIn("Blocked", result["results"][1]["error"])

    def test_successful_dependency_plan_and_isolated_cwd_env(self):
        server = self.server()
        with tempfile.TemporaryDirectory() as directory:
            tasks = [self.task("printf ready > marker", cwd=directory, name="prepare"),
                     self.task('cat marker; printf ":%s" "$TASKER_TEST"', cwd=directory,
                               env={"TASKER_TEST": "value"}, name="read", depends_on=["prepare"])]
            result = server._execute_batch({"tasks": tasks, "output_mode": "full"})
            self.assertEqual(result["completed"], 2, result)
            self.assertEqual(result["results"][1]["result"]["stdout"], "ready:value")
        self.assertNotIn("TASKER_TEST", os.environ)

    def test_both_streams_drained_and_bounded(self):
        task = self.execute(self.server(), python_command(
            "import os; os.write(1,b'x'*200000); os.write(2,b'y'*200000)"), max_output_bytes=1024)
        self.assertEqual(task["status"], "completed", task)
        for stream in ("stdout", "stderr"):
            self.assertEqual(len(task["result"][stream]), 1024)
            self.assertEqual(task["result"][stream + "_bytes"], 200000)
            self.assertTrue(task["result"][stream + "_truncated"])

    def test_timeout_kills_descendants_and_retains_output(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "leaked"
            command = f"trap '' TERM; printf started; (sleep 2; touch {shlex.quote(str(marker))}) & wait"
            task = self.execute(self.server(), command, timeout=1)
            self.assertEqual(task["status"], "failed")
            self.assertTrue(task["result"]["timed_out"])
            self.assertEqual(task["result"]["stdout"], "started")
            time.sleep(.7)
            self.assertFalse(marker.exists(), "descendant survived timeout")

    def test_cancel_running_and_queued_commands(self):
        server = self.server(max_workers=1)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "started"
            batch = server._execute_batch({"tasks": [
                self.task(f"touch {shlex.quote(str(marker))}; sleep 30", name="running"),
                self.task("printf must-not-run", name="queued")], "wait": False})
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(marker.exists())
            server._cancel_batch({"batch_id": batch["batch_id"]})
            result = self.collect(server, batch)
            self.assertEqual(result["cancelled"], 2, result)
            self.assertTrue(result["results"][0]["result"]["cancelled"])
            self.assertIsNone(result["results"][1]["result"])

    def test_normal_exit_cleans_background_children(self):
        task = self.execute(self.server(), "sleep 30 & printf finished", timeout=3)
        self.assertEqual(task["status"], "completed", task)
        self.assertFalse(task["result"]["timed_out"])
        self.assertEqual(task["result"]["stdout"], "finished")
        self.assertLess(task["duration_seconds"], 2)

    def test_validation(self):
        for options in ({"command": ""}, {"command": "x\x00"}, {"timeout": 0},
                        {"max_output_bytes": 65537}, {"max_output_bytes": True},
                        {"env": {"bad=name": "x"}}, {"env": {"x": "\x00"}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_payload(TaskType.SHELL, {"command": "true", **options})

    def test_pi_omp_config_and_cli(self):
        for client in ("pi", "omp"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["--print-config", client, "--allow-shell", "--workers", "4",
                                       "--shell-cwd", "/tmp"]), 0)
            args = json.loads(out.getvalue())["mcpServers"]["agent-tasker"]["args"]
            self.assertIn("--allow-shell", args)
            self.assertIn("4", args)
            self.assertIn("/tmp", args)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--shell-cwd", "/tmp"])
        with self.assertRaises(ValueError):
            server_args(4, shell_cwd="/tmp")


@unittest.skipUnless(os.name == "posix", "POSIX process groups required")
class ShellProtocolTests(unittest.TestCase):
    def test_sigterm_cleans_running_shell(self):
        from test_protocol import MCPProcess
        server = MCPProcess(extra_args=["--allow-shell"])
        self.addCleanup(server.close)
        server.initialize()
        with tempfile.TemporaryDirectory() as directory:
            started = Path(directory) / "started"
            leaked = Path(directory) / "leaked"
            batch = server.call("execute_batch", {"wait": False, "tasks": [{"task_type": "shell",
                "command": f"touch {shlex.quote(str(started))}; sleep 2; touch {shlex.quote(str(leaked))}"}]})
            self.assertFalse(batch["isError"], batch)
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(started.exists())
            server.process.terminate()
            server.process.wait(timeout=5)
            time.sleep(2)
            self.assertFalse(leaked.exists(), "command survived server SIGTERM")
            self.assertNotIn("Traceback", server.process.stderr.read())

    def test_request_cancellation_stops_synchronous_command(self):
        from test_protocol import MCPProcess
        server = MCPProcess(extra_args=["--allow-shell"])
        self.addCleanup(server.close)
        server.initialize()
        with tempfile.TemporaryDirectory() as directory:
            started = Path(directory) / "started"
            leaked = Path(directory) / "leaked"
            server.send({"jsonrpc": "2.0", "id": 88, "method": "tools/call", "params": {
                "name": "execute", "arguments": {"task_type": "shell",
                "command": f"touch {shlex.quote(str(started))}; sleep 2; touch {shlex.quote(str(leaked))}"}}})
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(started.exists())
            server.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 88}})
            time.sleep(2)
            self.assertFalse(leaked.exists())
            response = server.request({"jsonrpc": "2.0", "id": 89, "method": "ping"})
            self.assertEqual(response["id"], 89, "cancelled call must not send a result")


if __name__ == "__main__":
    unittest.main()
