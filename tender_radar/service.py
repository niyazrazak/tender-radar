"""Runs the dashboard as a macOS launchd agent: it starts at login and restarts if it stops."""
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from tender_radar.cli import ROOT

LABEL = "com.tenderradar.dashboard"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = ROOT / "logs" / "tender-radar.log"


def install(config_path: Path):
    LOG.parent.mkdir(exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    _unload()
    PLIST.write_bytes(plistlib.dumps(_agent(config_path)))
    _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
    print(f"Installed {PLIST}\nIt starts at login and restarts if it stops.")
    print(f"Dashboard: http://127.0.0.1:{_port(config_path)}\nLog: {LOG}")


def uninstall(_config_path: Path):
    _unload()
    PLIST.unlink(missing_ok=True)
    print("Service removed. The dashboard no longer runs in the background.")


def status(config_path: Path):
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True
    )
    if result.returncode:
        print("Not installed. Run: .venv/bin/python -m tender_radar install-service")
        return
    state = next((line.strip() for line in result.stdout.splitlines() if line.strip().startswith("state =")), "")
    print(f"{LABEL}: {state}\nDashboard: http://127.0.0.1:{_port(config_path)}\nLog: {LOG}")


def _agent(config_path: Path) -> dict:
    return {
        "Label": LABEL,
        # Keep the venv path: resolving the symlink would lose the venv's packages.
        "ProgramArguments": [sys.executable, "-m", "tender_radar", "serve", "--config", str(config_path)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def _unload():
    if PLIST.exists():
        _launchctl("bootout", f"gui/{os.getuid()}", str(PLIST), check=False)


def _launchctl(*args, check: bool = True):
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    if check and result.returncode:
        sys.exit(f"launchctl {args[0]} failed: {result.stderr.strip()}")


def _port(config_path: Path) -> int:
    return json.loads(config_path.read_text(encoding="utf-8")).get("schedule", {}).get("port", 8765)
