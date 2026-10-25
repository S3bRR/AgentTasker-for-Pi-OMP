import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_tasker_mcp.installation import main, make_entry, parser, read_config, target_config, write_config


class InstallationTests(unittest.TestCase):
    def test_preserves_unrelated_entries_and_private_backup_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            original = b'{ "otherSetting": true, "mcpServers": {"existing": {"command": "example"}} }\n'
            path.write_bytes(original)
            entry = {"command": "python", "args": []}
            backup, changed = write_config(path, entry)
            self.assertTrue(changed)
            self.assertEqual(backup.read_bytes(), original)
            merged = json.loads(path.read_text())
            self.assertTrue(merged["otherSetting"])
            self.assertEqual(merged["mcpServers"]["existing"], {"command": "example"})
            self.assertEqual(merged["mcpServers"]["agent-tasker"], entry)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_idempotent_entry_does_not_create_more_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            entry = {"command": "example", "args": []}
            write_config(path, entry)
            raw = path.read_bytes()
            self.assertEqual(write_config(path, entry), (None, False))
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(Path(directory).glob("*.backup-*")), [])

    def test_collision_requires_explicit_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            write_config(path, {"command": "old"})
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "--replace"):
                write_config(path, {"command": "new"})
            self.assertEqual(path.read_bytes(), before)
            backup, changed = write_config(path, {"command": "new"}, replace=True)
            self.assertTrue(changed)
            self.assertEqual(backup.read_bytes(), before)

    def test_malformed_and_duplicate_json_refused(self):
        for raw in ('{', 'null', '[]', '{"mcpServers":[]}', '{"mcpServers":{},"mcpServers":{}}'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "mcp.json"
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    read_config(path)
                self.assertEqual(path.read_text(), raw)

    @unittest.skipUnless(os.name == "posix", "Symlink test")
    def test_config_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real.json"
            target.write_text('{}')
            link = Path(directory) / "mcp.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                read_config(link)
            self.assertEqual(target.read_text(), '{}')

    def test_concurrent_config_change_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{}')
            original = path.read_bytes()
            path.write_text('{"new": true}')
            with self.assertRaisesRegex(ValueError, "changed"):
                write_config(path, {"command": "example"}, original=original)
            self.assertEqual(json.loads(path.read_text()), {"new": True})

    def test_config_selection_is_explicit_for_omp(self):
        with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": "/example/pi-profile", "OMP_PROFILE": "unrelated"}):
            self.assertEqual(target_config("pi"), Path("/example/pi-profile/mcp.json"))
            self.assertIsNone(target_config("omp"))
            self.assertEqual(target_config("omp", profile="work"), Path.home() / ".omp/profiles/work/agent/mcp.json")
            with self.assertRaises(ValueError):
                target_config("omp", profile="../other")

    def test_config_preview_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()), \
                    patch("agent_tasker_mcp.installation.subprocess.run", side_effect=AssertionError("No install expected")):
                result = main(["--client", "pi", "--config", str(path), "--skip-install", "--venv", sys.prefix,
                               "--cwd", directory, "--allow-shell"])
            self.assertEqual(result, 0)
            self.assertFalse(path.exists())
            entry = json.loads(out.getvalue())["mcpServers"]["agent-tasker"]
            self.assertEqual(entry["exposure"], "direct")
            self.assertIn("4", entry["args"])
            self.assertIn("--allow-shell", entry["args"])

    def test_apply_merges_only_selected_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = main(["--client", "omp", "--config", str(path), "--skip-install", "--venv", sys.prefix,
                               "--cwd", directory, "--allow-shell", "--apply"])
            self.assertEqual(result, 0)
            self.assertIn("agent-tasker", json.loads(path.read_text())["mcpServers"])
            self.assertFalse((Path(directory) / "mcp.json").exists())

    def test_bad_configuration_fails_before_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{broken')
            with contextlib.redirect_stderr(io.StringIO()), patch("agent_tasker_mcp.installation.subprocess.run") as run:
                self.assertEqual(main(["--config", str(path), "--cwd", directory, "--allow-shell", "--apply"]), 1)
            run.assert_not_called()

    def test_ssh_configuration_quotes_remote_paths_and_never_installs_locally(self):
        args = parser().parse_args(["--transport", "ssh", "--ssh-host", "operator@example.invalid",
            "--remote-python", "/remote/path with spaces/.venv/bin/python", "--cwd", "/work/path with spaces", "--allow-shell"])
        with patch("agent_tasker_mcp.installation.shutil.which", return_value="/usr/bin/ssh"):
            entry = make_entry(args, "/unused/python")
        self.assertEqual(entry["command"], "/usr/bin/ssh")
        self.assertIn("StrictHostKeyChecking=yes", entry["args"])
        self.assertIn("BatchMode=yes", entry["args"])
        self.assertIn("PermitLocalCommand=no", entry["args"])
        remote = shlex.split(entry["args"][-1])
        self.assertEqual(remote[0], "/remote/path with spaces/.venv/bin/python")
        self.assertEqual(remote[-1], "/work/path with spaces")
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()), patch("agent_tasker_mcp.installation.subprocess.run") as run, \
                patch("agent_tasker_mcp.installation.shutil.which", return_value="/usr/bin/ssh"):
            path = Path(directory) / "mcp.json"
            self.assertEqual(main(["--transport", "ssh", "--ssh-host", "example.invalid", "--remote-python", "/remote/python",
                                  "--cwd", "/work", "--allow-shell", "--config", str(path)]), 0)
            self.assertFalse(path.exists())
            run.assert_not_called()

    def test_validation_rejects_ambiguous_and_unsafe_inputs(self):
        cases = [
            ["--allow-shell"], ["--cwd", "/tmp"], ["--workers", "0"], ["--workers", "257"],
            ["--replace"], ["--client", "omp", "--apply"],
            ["--client", "omp", "--profile", "work", "--config", "/example/mcp.json"], ["--client", "pi", "--profile", "work"],
            ["--ssh-host", "example.invalid"],
            ["--transport", "ssh", "--ssh-host", "example.invalid; touch /tmp/forbidden", "--remote-python", "/remote/python"],
            ["--transport", "ssh", "--ssh-host", "example.invalid", "--remote-python", "relative/python"],
            ["--transport", "ssh", "--ssh-host", "example.invalid", "--remote-python", "/remote/python", "--ssh-port", "70000"],
        ]
        for args in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), \
                    patch("agent_tasker_mcp.installation.subprocess.run") as run:
                self.assertEqual(main(args), 1)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
