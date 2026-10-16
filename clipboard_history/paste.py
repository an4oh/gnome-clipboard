"""Thin wrappers around xdotool. Every failure is logged to stderr, never raised."""
import ctypes
import ctypes.util
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


def get_window_position(xid):
    """Return (x, y) of the window in root coordinates, or None."""
    out = _run("getwindowgeometry", "--shell", str(xid))
    if not out:
        return None
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    try:
        return int(values["X"]), int(values["Y"])
    except (KeyError, ValueError):
        _log(f"unexpected getwindowgeometry output: {out!r}")
        return None


def move_window(xid, x, y, sync=False):
    args = ["windowmove"]
    if sync:
        args.append("--sync")
    _run(*args, str(xid), str(x), str(y))


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


_BUTTON1_MASK = 1 << 8
_x11 = None  # (libX11, Display*, root) once opened, False if unavailable


def button1_pressed():
    """Real state of mouse button 1 via XQueryPointer (valid even while the
    window manager holds a grab), or None if X11 is not reachable."""
    global _x11
    if _x11 is None:
        _x11 = False
        try:
            lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_void_p] * 7
            display = lib.XOpenDisplay(None)
            if display:
                _x11 = (lib, display, lib.XDefaultRootWindow(display))
            else:
                _log("XOpenDisplay failed")
        except (OSError, AttributeError) as e:
            _log(f"libX11 not available: {e}")
    if not _x11:
        return None
    lib, display, root = _x11
    win = ctypes.c_ulong()
    coord = ctypes.c_int()
    mask = ctypes.c_uint()
    ref = ctypes.byref
    if not lib.XQueryPointer(display, root, ref(win), ref(win), ref(coord), ref(coord),
                             ref(coord), ref(coord), ref(mask)):
        return None
    return bool(mask.value & _BUTTON1_MASK)
