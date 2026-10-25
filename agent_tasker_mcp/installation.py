"""Explicit, portable installation and non-destructive MCP config generation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

SERVER_NAME = "agent-tasker"
ROOT = Path(__file__).resolve().parents[1]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_config(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Config is a symlink; pass its intended real path explicitly")
    raw = path.read_bytes() if path.exists() else None
    data = json.loads(raw, object_pairs_hook=_unique_object) if raw is not None else {}
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ValueError("Config must be a JSON object with an mcpServers object")
    return data, raw


def write_config(path, entry, *, replace=False, original=None):
    """Preserve unrelated content, refuse collisions, back up bytes, replace atomically."""
    path = Path(path)
    data, current = read_config(path)
    if original is not None and current != original:
        raise ValueError("Config changed during installation; retry after reviewing it")
    servers = data.setdefault("mcpServers", {})
    if SERVER_NAME in servers:
        if servers[SERVER_NAME] == entry:
            return None, False
        if not replace:
            raise ValueError("agent-tasker already exists; review it and pass --replace to change only that entry")
    servers[SERVER_NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if current is not None:
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        backup = path.with_name(path.name + ".backup-" + suffix)
        with backup.open("xb") as stream:
            os.chmod(backup, 0o600)
            stream.write(current)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".agent-tasker-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup, True


def target_config(client, config=None, profile=None):
    if config:
        return Path(config).expanduser().absolute()
    if client == "pi":
        return Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser().absolute() / "mcp.json"
    if client == "omp" and profile:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
            raise ValueError("Profile must contain only letters, digits, underscore or hyphen")
        return Path.home() / ".omp" / "profiles" / profile / "agent" / "mcp.json"
    return None


def _remote_path(value, name):
    if not value or not posixpath.isabs(value) or any(c in value for c in "\x00\n\r"):
        raise ValueError(f"{name} must be an absolute POSIX path on the SSH host")
    return value


def make_entry(args, python):
    if args.workers < 1 or args.workers > 256:
        raise ValueError("--workers must be between 1 and 256")
    command_args = ["-m", "agent_tasker_mcp.server", "--workers", str(args.workers)]
    if args.allow_shell:
        if not args.cwd:
            raise ValueError("--allow-shell requires --cwd; explicitly choose where commands run")
        command_args.append("--allow-shell")
    if args.transport == "local":
        if any((args.ssh_host, args.ssh_config, args.ssh_port, args.remote_python)):
            raise ValueError("SSH options require --transport ssh")
        if args.allow_shell and os.name != "posix":
            raise ValueError("Local Bash tasks require Linux/macOS; use WSL or SSH to a POSIX host")
        if args.cwd:
            cwd = Path(args.cwd).expanduser().resolve()
            if not cwd.is_dir():
                raise ValueError("--cwd must be an existing local directory")
            command_args.extend(["--shell-cwd", str(cwd)])
        entry = {"type": "stdio", "command": str(python), "args": command_args}
    else:
        if not args.ssh_host or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:\[\]-]*", args.ssh_host):
            raise ValueError("--ssh-host must be an SSH alias or user@host, not a shell command or option")
        remote_python = _remote_path(args.remote_python, "--remote-python")
        if args.cwd:
            command_args.extend(["--shell-cwd", _remote_path(args.cwd, "--cwd")])
        ssh = shutil.which("ssh")
        if not ssh:
            raise ValueError("SSH executable not found; install OpenSSH on the client")
        ssh_args = ["-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", "PermitLocalCommand=no", "-o", "ControlMaster=no", "-o", "ControlPath=none"]
        if args.ssh_config:
            config = Path(args.ssh_config).expanduser().resolve()
            if not config.is_file():
                raise ValueError("--ssh-config must be an existing file on the client")
            ssh_args.extend(["-F", str(config)])
        if args.ssh_port:
            if not 1 <= args.ssh_port <= 65535:
                raise ValueError("--ssh-port must be between 1 and 65535")
            ssh_args.extend(["-p", str(args.ssh_port)])
        # SSH concatenates command arguments through the remote login shell.
        # Quote the entire remote argv explicitly, including paths with spaces.
        ssh_args.extend([args.ssh_host, shlex.join([remote_python, *command_args])])
        entry = {"type": "stdio", "command": str(Path(ssh).resolve()), "args": ssh_args}
    if args.client == "pi":
        entry["exposure"] = "direct"
    return entry


def parser():
    p = argparse.ArgumentParser(description="Install AgentTasker and print/merge a Pi or OMP MCP entry. No config changes without --apply.")
    p.add_argument("--client", choices=["pi", "omp", "generic"], default="generic")
    p.add_argument("--config", help="Exact active profile mcp.json on this client; required to apply OMP default/custom profiles")
    p.add_argument("--profile", help="Named OMP profile; alternatively pass --config (never guessed from the current shell)")
    p.add_argument("--transport", choices=["local", "ssh"], default="local")
    p.add_argument("--cwd", help="Command directory on the selected execution host")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--allow-shell", action="store_true", help="Explicitly enable arbitrary Bash commands; not a sandbox")
    p.add_argument("--apply", action="store_true", help="Merge only agent-tasker into the selected config; back up existing bytes")
    p.add_argument("--replace", action="store_true", help="Allow replacing an existing, different agent-tasker entry")
    p.add_argument("--venv", default=str(ROOT / ".venv"), help="Local virtual environment (local transport only)")
    p.add_argument("--skip-install", action="store_true", help="Generate/merge config only; local --venv must already contain Python")
    p.add_argument("--ssh-host", help="Already authorized SSH alias or user@host; never probes the network automatically")
    p.add_argument("--ssh-config", help="Existing client SSH config (optional)")
    p.add_argument("--ssh-port", type=int)
    p.add_argument("--remote-python", help="Absolute installed Python/venv executable on the remote POSIX host")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.profile and args.config:
            raise ValueError("Choose either --profile or --config, not both")
        if args.profile and args.client != "omp":
            raise ValueError("--profile requires --client omp")
        if args.cwd and not args.allow_shell:
            raise ValueError("--cwd requires --allow-shell")
        if args.replace and not args.apply:
            raise ValueError("--replace requires --apply")
        target = target_config(args.client, args.config, args.profile)
        if args.apply and target is None:
            raise ValueError("--apply needs --config, or Pi --client pi, or an explicit OMP --profile")
        venv = Path(args.venv).expanduser().absolute()
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        entry = make_entry(args, python)
        original = None
        if target:
            data, original = read_config(target)
            existing = data.get("mcpServers", {}).get(SERVER_NAME)
            if args.apply and existing is not None and existing != entry and not args.replace:
                raise ValueError("agent-tasker already exists; use --replace only after reviewing it")
        if args.transport == "local":
            if args.skip_install:
                if not python.is_file():
                    raise ValueError("--skip-install requires an existing virtual environment Python")
            else:
                if not (ROOT / "pyproject.toml").is_file():
                    raise ValueError("Run install.py from a cloned checkout, or use --skip-install with an installed venv")
                if not python.exists():
                    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, stdout=sys.stderr)
                subprocess.run([str(python), "-m", "pip", "install", str(ROOT)], check=True, stdout=sys.stderr)
                subprocess.run([str(python), "-m", "agent_tasker_mcp.server", "--help"], check=True,
                               stdout=subprocess.DEVNULL)
        if args.apply:
            # A new file may have appeared while pip was running. Never clobber it.
            if original is None and target.exists():
                raise ValueError("Config appeared during installation; review it and retry")
            backup, changed = write_config(target, entry, replace=args.replace, original=original)
            print(f"{'Updated' if changed else 'Already configured'}: {target}", file=sys.stderr)
            if backup:
                print(f"Backup (private): {backup}", file=sys.stderr)
        print(json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2))
        print("Restart/reload the selected client, then run the doctor and a real model-session test. No model, policy or AGENTS.md settings were changed.", file=sys.stderr)
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
