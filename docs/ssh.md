# SSH execution: commands stay on the chosen remote host

Use this when investigation/build workloads must not run on the client computer.
Install the server on the authorized VM and launch it through SSH. Nothing here
assumes your username, IP, keys, operating-system image or profile layout.

## 1. Prepare the remote host

Confirm the host with the user and use their already-authorized SSH/remote tools.
Establish known-host trust through their normal workflow, not an automated
`StrictHostKeyChecking=no`. The remote host needs Python 3.10+, Bash and Git.

On that host, clone to a stable location and install locally there:

```bash
git clone https://github.com/S3bRR/AgentTasker-for-Pi-OMP.git
cd AgentTasker-for-Pi-OMP
python3 install.py --client generic --cwd /absolute/remote/workspace --allow-shell
```

This creates a venv **on the remote host** and prints its installed Python path
under `command`. Do not pass `--apply` on the VM unless Pi/OMP itself runs there.
Keep that absolute Python path and the installation in place.

## 2. Generate the client transport

The client also needs a checkout and Python to run the config generator, but SSH
mode does **not** create a local venv or install a local command-execution server.
On the client, from the checkout:

```bash
python3 install.py --client pi --transport ssh \
  --ssh-host YOUR_AUTHORIZED_SSH_ALIAS \
  --remote-python /absolute/remote/AgentTasker-for-Pi-OMP/.venv/bin/python \
  --cwd /absolute/remote/workspace --allow-shell
```

Use your authorized SSH alias or `user@host`. Optional flags:

- `--ssh-config /absolute/client/ssh_config` for an existing config/key/jump setup.
- `--ssh-port 2222` for a non-default port.
- `--config /absolute/client/profile/mcp.json` for the exact active profile.
- OMP: `--client omp --profile NAME` or an explicit `--config`.

Review the generated entry; re-run with `--apply` to merge it. The generated remote
argv is quoted through the SSH login shell, including paths with spaces. Batch
mode and strict host-key checking stay enabled. There is no fallback host or local
launcher. Your SSH config/executable is trusted infrastructure and may include
user-chosen proxy commands; review it under the existing security policy.

## 3. Verify both ends

From the client checkout:

```bash
python3 -m agent_tasker_mcp.doctor --config /absolute/client/profile/mcp.json --shell-test
```

Confirm the returned host and directory are the remote VM, not the client.
Reload/restart the chosen Pi/OMP profile and run the real four-job model-session
test described in [INSTALL.md](../INSTALL.md). A custom VM-only guard may need
separate approval even when this transport works. Do not bypass it.

SSH transports are per-client server processes. Losing the SSH/client/server
session loses the batch state; no automatic side-effectful retry is attempted.
For durable logs, redirect output to a file **on the remote host** and inspect a
bounded tail using an authorized tool. Do not leave daemons running through this
scheduler or assume the command shares the client's current remote directory.
