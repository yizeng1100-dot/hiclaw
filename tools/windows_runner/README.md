# HiClaw Windows Runner

Pull-model runner that executes `shell_kind=windows` scheduled tasks
on a Windows machine. See `custom/docs/command_scheduler/DESIGN.md`
ADR-05 for the architecture decision.

## What it does

1. Every N seconds, polls HiClaw for fires stuck in `pending_runner`
2. For each one: claims it (`/start`), runs the command with `cmd.exe`,
   then reports exit code + stdout + stderr (`/complete`)
3. Sends a heartbeat on every cycle so HiClaw knows it's alive

All traffic is **outbound HTTP from Windows → HiClaw**. The runner
works behind any NAT / firewall as long as HiClaw is reachable.

---

## Setup on Windows

### 1. Install Python 3.9+ and `requests`

Download Python from <https://www.python.org/downloads/> (tick
"Add python.exe to PATH" during install). Then:

```cmd
python -m pip install requests
```

### 2. Copy the runner script

Place `hiclaw_windows_runner.py` somewhere stable, e.g. `C:\tools\`.

### 3. Create the default scripts directory

```cmd
mkdir D:\hiclaw_scripts
```

This is the default `working_dir` for tasks that don't specify one.
Put your `.py` / `.bat` files in subfolders here.

### 4. (Recommended) Generate and set an API key

On HiClaw's Linux machine, pick a random key:

```bash
python -c "import secrets;print(secrets.token_hex(24))"
```

Then on the HiClaw machine, add to its environment (e.g. systemd
unit, shell rc, or however you start the backend):

```bash
export HICLAW_WINDOWS_RUNNER_KEY=<the-generated-key>
```

Restart the HiClaw backend so it picks up the key.

If you skip this step, the runner endpoints accept any request (dev
mode). That's OK if your HiClaw is reachable only from inside your
network.

### 5. Test the runner manually

```cmd
cd C:\tools
python hiclaw_windows_runner.py ^
  --hiclaw-url http://<hiclaw-host>:12000 ^
  --api-key <the-generated-key> ^
  --runner-id my-pc ^
  --workdir D:\hiclaw_scripts ^
  --interval 10 ^
  --log-level INFO
```

You should see `HiClaw Windows runner starting: ...` and then
`heartbeat ok` lines. Leave the terminal open and create a Windows
task in HiClaw UI — you should see the runner pick it up.

### 6. Make it auto-start on boot

Two options.

#### Option A: Windows Task Scheduler (simplest)

1. Open **Task Scheduler** → Create Task
2. General tab:
   - Name: `HiClawRunner`
   - "Run whether user is logged on or not"
   - "Run with highest privileges"
3. Triggers tab → New → "At startup"
4. Actions tab → New:
   - Program: `python`
   - Arguments: `C:\tools\hiclaw_windows_runner.py --hiclaw-url http://<host>:12000 --api-key <key>`
   - Start in: `C:\tools`
5. Conditions: uncheck "Stop if the computer switches to battery"
6. Save — it'll prompt for your password (used for "run when not
   logged in")

#### Option B: NSSM (Non-Sucking Service Manager, cleanest)

```cmd
choco install nssm   :: or download from https://nssm.cc
nssm install HiClawRunner "C:\Python312\python.exe" "C:\tools\hiclaw_windows_runner.py --hiclaw-url http://<host>:12000 --api-key <key>"
nssm set HiClawRunner AppDirectory C:\tools
nssm set HiClawRunner Start SERVICE_AUTO_START
nssm start HiClawRunner
```

Logs go to Windows Event Log (Application → HiClawRunner).

---

## Troubleshooting

### The runner says "heartbeat failed: Connection refused"
HiClaw backend isn't reachable at `--hiclaw-url`. Check the URL, test
with `curl http://<host>:12000/api/v1/command-schedules` from the
Windows machine.

### The runner says "401 Unauthorized" or "Invalid runner key"
The `--api-key` doesn't match `HICLAW_WINDOWS_RUNNER_KEY` on the
server. Either fix it or remove the env var on the server (dev mode
with no auth).

### Tasks never get picked up
- Check the task actually has `shell_kind=windows` (the UI should
  show "Windows 待执行" on the card)
- Check that the fire's status is `pending_runner`:
  ```bash
  sqlite3 ~/.openhands/openhands.db \
    "SELECT id, status FROM command_fires ORDER BY started_at DESC LIMIT 5;"
  ```
- Is the runner online? `GET /api/v1/command-scheduler/windows-runner/status`

### The command runs on Windows but fails with "'xxx' is not recognized"
Your `PATH` on Windows doesn't include that tool's directory, or the
command expects a different shell (PowerShell vs cmd.exe). The runner
uses `cmd.exe` by default via `shell=True`. Explicitly:

```cmd
powershell -Command "Your-Script.ps1"
```

or activate a venv in-line:

```cmd
D:\hiclaw_scripts\myenv\Scripts\python.exe D:\hiclaw_scripts\myscript.py --prod
```

### Commands time out that shouldn't
Raise `max_duration_sec` on the task in the HiClaw UI. Default is
300 seconds. The runner kills the subprocess at that cutoff.

### I want more logs
Add `--log-level DEBUG`.

---

## Uninstall

### Task Scheduler
```cmd
schtasks /delete /tn HiClawRunner /f
```

### NSSM
```cmd
nssm stop HiClawRunner
nssm remove HiClawRunner confirm
```

Then delete `C:\tools\hiclaw_windows_runner.py` and optionally
`D:\hiclaw_scripts\` (if you're sure you don't need the scripts
anymore).
