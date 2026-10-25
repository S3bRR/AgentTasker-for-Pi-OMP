import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import socket
import sys
import tempfile
import unittest

from agent_tasker_mcp.doctor import main, verify
from agent_tasker_mcp.installation import make_entry, parser


@unittest.skipUnless(os.name == "posix", "POSIX shell/process tests")
class DoctorTests(unittest.TestCase):
    def entry(self, cwd, shell=True):
        args = ["-m", "agent_tasker_mcp.server", "--workers", "4"]
        if shell:
            args += ["--allow-shell", "--shell-cwd", cwd]
        return {"type": "stdio", "command": sys.executable, "args": args}

    def test_protocol_only_does_not_enable_or_run_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify(self.entry(directory, shell=False))
            self.assertTrue(result["protocol_ok"])
            self.assertFalse(result["shell_test_run"])
            self.assertNotIn("completed", result)

    def test_four_real_shell_jobs_and_results(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify(self.entry(directory), shell_test=True)
            self.assertEqual(result["completed"], 4)
            self.assertTrue(result["four_way_overlap"])
            self.assertGreater(result["overlap_seconds"], 0)
            self.assertEqual(result["hosts"], [socket.gethostname()])
            self.assertEqual(result["directories"], [str(Path(directory).resolve())])
            self.assertEqual(result["outputs"], [f"PASS job-{i}" for i in range(4)])

    def test_shell_disabled_is_an_error_not_a_false_pass(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "disabled"):
            verify(self.entry(directory, shell=False), shell_test=True)

    def test_ssh_command_quoting_with_local_transport_fixture(self):
        # This is a fake SSH relay, not an external network/VM test.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "work with spaces"
            workspace.mkdir()
            python = root / "python with spaces"
            python.symlink_to(sys.executable)
            relay = root / "ssh_fixture.py"
            relay.write_text('import os,shlex,sys\nargs=shlex.split(sys.argv[-1]); os.execv(args[0],args)\n')
            args = parser().parse_args(["--transport", "ssh", "--ssh-host", "example.invalid",
                "--remote-python", str(python), "--cwd", str(workspace), "--allow-shell"])
            from unittest.mock import patch
            with patch("agent_tasker_mcp.installation.shutil.which", return_value="/usr/bin/ssh"):
                entry = make_entry(args, "/unused")
            # Retain the generated remote shell string, but replace OpenSSH with
            # a local deterministic fixture that implements its argv concatenation.
            entry["command"] = sys.executable
            entry["args"] = [str(relay), *entry["args"]]
            self.assertEqual(shlex.split(entry["args"][-1])[0], str(python))
            result = verify(entry, shell_test=True)
            self.assertEqual(result["completed"], 4)
            self.assertEqual(result["directories"], [str(workspace.resolve())])

    def test_cli_reads_only_selected_server_and_never_changes_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text(json.dumps({"mcpServers": {"agent-tasker": self.entry(directory),
                "unrelated": {"command": "/never/run/this"}}}))
            original = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(["--config", str(path), "--shell-test"]), 0)
            self.assertEqual(json.loads(out.getvalue())["completed"], 4)
            self.assertEqual(path.read_bytes(), original)

    def test_missing_disabled_and_unsupported_entries_fail(self):
        for value in ({}, {"enabled": False}, {"command": "example", "type": "http"},
                      {"command": "example", "env": {"TOKEN": "${VALUE}"}}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "mcp.json"
                path.write_text(json.dumps({"mcpServers": {"agent-tasker": value}}))
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["--config", str(path)]), 1)


if __name__ == "__main__":
    unittest.main()
