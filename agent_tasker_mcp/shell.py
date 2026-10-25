"""Opt-in POSIX shell execution on the server's host (never implicit SSH)."""

from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import time


class ShellExecutor:
    """One process group per command; bounded tails, deadlines and cancellation."""

    def __init__(self, cwd=None):
        if os.name != "posix":
            raise ValueError("Shell execution currently requires POSIX (Linux/macOS)")
        self.cwd = self.validate_cwd(cwd or os.getcwd())
        self.shell = "/bin/bash"
        if not Path(self.shell).is_file():
            raise ValueError("Shell execution requires /bin/bash")

    @staticmethod
    def validate_cwd(value):
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("Shell cwd must be an existing absolute directory on the server host")
        return str(path.resolve())

    @staticmethod
    def _signal(process, sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can return EPERM for a group containing only dead processes.
            # A live leader must still surface genuine permission failures.
            if process.poll() is None:
                raise

    def run(self, payload, *, cancel=None, shutdown=None):
        cwd = self.validate_cwd(payload.get("cwd", self.cwd))
        limit = payload["max_output_bytes"]
        tails = {"stdout": bytearray(), "stderr": bytearray()}
        counts = {"stdout": 0, "stderr": 0}
        reason, stop_at = None, None
        killed = False
        deadline = time.monotonic() + payload["timeout"]
        # No login/interactive startup, inherited stdin, retries, or shell fallback.
        process = subprocess.Popen(
            [self.shell, "--noprofile", "--norc", "-c", payload["command"]],
            cwd=cwd, env={**os.environ, **payload.get("env", {})},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            with selectors.DefaultSelector() as selector:
                for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while True:
                    now = time.monotonic()
                    if stop_at is None:
                        if (cancel and cancel.is_set()) or (shutdown and shutdown.is_set()):
                            reason = "cancelled"
                        elif now >= deadline:
                            reason = "timeout"
                        # Clean up background descendants even after the shell exits.
                        if reason or process.poll() is not None:
                            self._signal(process, signal.SIGTERM)
                            stop_at = now
                    if stop_at is not None and now - stop_at >= 0.5:
                        self._signal(process, signal.SIGKILL)
                        killed = True
                        # Do not wait for escaped descendants holding inherited pipes.
                        break
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        name = key.data
                        counts[name] += len(chunk)
                        tails[name].extend(chunk)
                        if len(tails[name]) > limit:
                            del tails[name][:-limit]
                    if process.poll() is not None and not selector.get_map():
                        break
        finally:
            try:
                if not killed:
                    self._signal(process, signal.SIGKILL)
            finally:
                process.wait()
                process.stdout.close()
                process.stderr.close()
        return {
            "host": socket.gethostname(), "cwd": cwd, "exit_code": process.returncode,
            "timed_out": reason == "timeout", "cancelled": reason == "cancelled",
            **{name: value.decode("utf-8", errors="replace") for name, value in tails.items()},
            **{name + "_bytes": count for name, count in counts.items()},
            **{name + "_truncated": counts[name] > limit for name in tails},
        }
