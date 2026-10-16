"""Thin wrappers around xdotool. Every failure is logged to stderr, never raised."""
import subprocess
import sys

XDOTOOL = "xdotool"
TIMEOUT = 3


def _log(msg):
    print(f"clipboard-history: {msg}", file=sys.stderr, flush=True)


def _run(*args):
    """Run xdotool and return stdout, or None on any error."""
    try:
        res = subprocess.run(
            [XDOTOOL, *args], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        _log(f"xdotool {' '.join(args)} failed: {e}")
        return None
    if res.returncode != 0:
        _log(f"xdotool {' '.join(args)} exited {res.returncode}: {res.stderr.strip()}")
        return None
    return res.stdout


def get_active_window():
    out = _run("getactivewindow")
    return out.strip() if out and out.strip() else None


def get_mouse_location():
    """Return (x, y) of the pointer in root coordinates, or None."""
    out = _run("getmouselocation", "--shell")
    if not out:
        return None
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    try:
        return int(values["X"]), int(values["Y"])
    except (KeyError, ValueError):
        _log(f"unexpected getmouselocation output: {out!r}")
        return None


def move_window(xid, x, y):
    _run("windowmove", str(xid), str(x), str(y))


def activate_window(xid, sync=False):
    args = ["windowactivate"]
    if sync:
        args.append("--sync")
    _run(*args, str(xid))


def send_paste(target_window):
    """Give focus back to target_window (if known) and send Ctrl+V."""
    if target_window:
        activate_window(target_window, sync=True)
    _run("key", "--clearmodifiers", "ctrl+v")
