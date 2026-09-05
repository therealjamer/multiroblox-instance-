"""
MultiRoblox (Python / tkinter version)  --  v2
==============================================

Dark-mode desktop app to run multiple Roblox instances at once.

WHAT'S IN THE WINDOW
  - Header with an airplane-mode-style ON/OFF switch for the WATCHER.
    While it is ON, a background thread frees Roblox's single-instance
    lock the moment any new Roblox window opens, so you don't have to
    click Launch again. It stays ON until you turn it off (there is an
    optional "one-shot" mode in Settings if you want the old behaviour
    where it switched itself back off after the first instance).
  - Launcher tab: account saver (name + Roblox session cookie per
    account, stored encrypted on this PC), multi-select launch, and a
    guest launch button.
  - Instances tab: live list of running Roblox clients with window
    title, memory, CPU, core limit and unlock status, plus the
    per-instance CPU core limiter.
  - Settings tab: cores per instance, core spreading, watcher poll
    interval, one-shot mode, auto-start, launch stagger, unlock retry
    settings, dependency/administrator status and master-password
    change.
  - Activity log docked at the bottom, always visible, with Clear/Copy.

SECURITY NOTE:
  A saved "cookie" is your Roblox .ROBLOSECURITY session token - it is
  equivalent to your password. Saved profiles are encrypted at rest
  using a master password you set on first run (stored at
  %AppData%\\MultiRobloxGUI\\profiles.enc, unreadable without that
  password). Still - never share this file, your master password, or
  your cookie with anyone. Only save profiles for accounts you
  personally own. Roblox's private sign-in endpoints can change
  without notice; if direct sign-in stops working, the app falls back
  to a guest launch you log into by hand.

IMPORTANT - nothing here reads the screen or sends input into the
game. On its own the tool does exactly ONE thing to a running client:
just before starting a new one it closes that client's single-instance
lock handle. That is unavoidable - whichever client created the lock
owns it, and a new client quits instantly while it is held - and it is
harmless: the running client keeps playing, and nothing else about it
is read or altered.

Clients CAN be closed, but only from the Close Selected / Close All
buttons, only the ones you picked, and never automatically. A close
you asked for does not count as a crash, so auto-rejoin ignores it.

REQUIREMENTS (Windows only):
  pip install psutil requests cryptography pyinstaller

RUN DIRECTLY (for testing):
  python multi_roblox.py

COMMAND-LINE FLAGS (for a desktop shortcut or Task Scheduler):
  --launch-all         launch every saved profile, then behave normally
  --launch "Name"       launch one saved profile by its exact name
  --minimized           start minimized (implied by the two flags above)
  --doctor               print why a dependency won't load, then exit
  These start minimized/unattended-ish, but NOT fully headless: if you have
  a master password set, MultiRoblox still has to ask for it - there is no
  flag that reads it from a config file, since that would defeat the point
  of encrypting the profile store.

BUILD INTO A SINGLE .EXE:
  pyinstaller --onefile --windowed --name MultiRoblox multi_roblox.py
  -> the finished file is at:  dist\\MultiRoblox.exe
  (PyInstaller must be run on Windows to produce a Windows .exe.)
"""

import base64
import ctypes
import traceback
import glob
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from urllib.parse import quote
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser, font as tkfont

# Optional dependencies. The exact import failure is kept so the app can
# say WHY a package is unavailable - "not installed" and "installed but
# broken / installed for a different Python" look identical otherwise.
IMPORT_ERRORS = {}


def _import_error(name, ex):
    IMPORT_ERRORS[name] = "%s: %s" % (type(ex).__name__, ex)


try:
    import psutil
except Exception as _ex:            # noqa: BLE001 - report anything, don't crash
    _import_error("psutil", _ex)
    psutil = None

try:
    import requests
except Exception as _ex:            # noqa: BLE001
    _import_error("requests", _ex)
    requests = None

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except Exception as _ex:            # noqa: BLE001
    # A broken install (wrong architecture, missing _rust extension) raises
    # something other than ImportError, so catch everything here.
    _import_error("cryptography", _ex)
    Fernet = None

    class InvalidToken(Exception):
        pass

    PBKDF2HMAC = None
    hashes = None


def python_description():
    """Which interpreter is actually running this - the usual reason a
    'pip install' didn't take effect."""
    bits = ctypes.sizeof(ctypes.c_void_p) * 8
    if getattr(sys, "frozen", False):
        return "bundled build: %s (%d-bit)" % (
            os.path.basename(sys.executable), bits)
    return "%s\n  Python %d.%d.%d (%d-bit)" % (
        sys.executable, sys.version_info[0], sys.version_info[1],
        sys.version_info[2], bits)


def install_hint(package):
    """The exact command that installs into THIS interpreter."""
    if getattr(sys, "frozen", False):
        return ("This is a built .exe, so installing a package now changes "
                "nothing - the package has to be present when you BUILD it:\n"
                "    pip install %s\n"
                "    pyinstaller --onefile --windowed --collect-all %s "
                "--name MultiRoblox multi_roblox.py" % (package, package))
    return '    "%s" -m pip install %s' % (sys.executable, package)

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception as _ex:            # noqa: BLE001
    _import_error("pystray", _ex)
    pystray = None
    Image = None
    ImageDraw = None

try:
    from pycaw.pycaw import AudioUtilities
except Exception as _ex:            # noqa: BLE001
    _import_error("pycaw", _ex)
    AudioUtilities = None

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------
# Colors (dark theme)
# ---------------------------------------------------------------------
BG = "#18181b"
PANEL = "#202024"
CONTROL = "#2d2d32"
BORDER = "#3c3c42"
TEXT = "#e6e6e6"
SUBTEXT = "#aaaaaa"
GREEN = "#57c785"
BLUE = "#5a9beb"     # also the "accent color" - overwritten from settings
                     # by apply_appearance_settings() before any widget is
                     # built, so every widget picks it up through this same
                     # name. Background/text stay fixed on purpose - letting
                     # those be freely recolored risks illegible combinations
                     # (e.g. white text on white background); the accent only
                     # touches buttons/highlights/borders, which can't do that.
RED = "#dc6464"
AMBER = "#d8a657"
FONT_FAMILY = "Segoe UI"   # overwritten the same way, before any widget exists

MAX_LOG_LINES = 800
APP_VERSION = "3.4"
_LOG_FILE_LOCK = threading.Lock()
MAX_LOG_FILE_BYTES = 1024 * 1024

# "owner/repo" - fill in once you've pushed to GitHub to turn on the update
# checker. Left blank, check_for_update() always returns None, so this has
# no effect until you deliberately set it.
GITHUB_REPO = ""

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
def config_dir():
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    d = os.path.join(appdata, "MultiRobloxGUI")
    os.makedirs(d, exist_ok=True)
    return d


def auth_path():
    return os.path.join(config_dir(), "auth.json")


def profiles_path():
    return os.path.join(config_dir(), "profiles.enc")


def settings_path():
    return os.path.join(config_dir(), "settings.json")


def layouts_path():
    return os.path.join(config_dir(), "layouts.json")


def load_layouts():
    try:
        with open(layouts_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_layouts(layouts):
    try:
        atomic_write(layouts_path(), json.dumps(layouts, indent=2), binary=False)
    except Exception:
        pass


def game_cache_path():
    return os.path.join(config_dir(), "games.json")


def icon_dir():
    d = os.path.join(config_dir(), "icons")
    os.makedirs(d, exist_ok=True)
    return d


def icon_cache_path(place_id):
    return os.path.join(icon_dir(), "%s.png" % place_id)


def load_game_cache():
    try:
        with open(game_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_game_cache(cache):
    try:
        atomic_write(game_cache_path(), json.dumps(cache, indent=2), binary=False)
    except Exception:
        pass


def fetch_game_info(place_id):
    """Looks up a game's name and icon from Roblox's public endpoints.
    Returns (name, png_bytes); either may be None."""
    if requests is None or not place_id:
        return None, None
    name = None
    icon = None
    try:
        r = requests.get(
            "https://apis.roblox.com/universes/v1/places/%s/universe" % place_id,
            timeout=15)
        universe_id = r.json().get("universeId") if r.ok else None
        if universe_id:
            g = requests.get(
                "https://games.roblox.com/v1/games?universeIds=%s" % universe_id,
                timeout=15)
            if g.ok:
                rows = g.json().get("data") or []
                if rows:
                    name = rows[0].get("name")
    except Exception:
        pass
    try:
        t = requests.get(
            "https://thumbnails.roblox.com/v1/places/gameicons"
            "?placeIds=%s&size=150x150&format=Png&isCircular=false" % place_id,
            timeout=15)
        if t.ok:
            rows = t.json().get("data") or []
            url = rows[0].get("imageUrl") if rows else None
            if url:
                img = requests.get(url, timeout=20)
                if img.ok and img.content[:4] == b"\x89PNG":
                    icon = img.content
    except Exception:
        pass
    return name, icon


def sessions_path():
    return os.path.join(config_dir(), "sessions.csv")


def append_session(profile, pid, started, ended, reason):
    """One row per play session, so you can see which account keeps dropping."""
    try:
        new = not os.path.exists(sessions_path())
        minutes = max(0, int((ended - started) // 60)) if started else 0
        with open(sessions_path(), "a", encoding="utf-8", newline="") as f:
            if new:
                f.write("started,ended,profile,pid,minutes,reason\n")
            f.write("%s,%s,%s,%d,%d,%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started or ended)),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ended)),
                str(profile).replace(",", " "), pid, minutes,
                str(reason or "closed").replace(",", " ")))
    except Exception:
        pass


def read_sessions(limit=200):
    rows = []
    try:
        with open(sessions_path(), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return rows
    for line in lines[1:][-limit:]:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append(parts[:5] + [",".join(parts[5:])])
    return rows


def report_crash(where, exc_info=None):
    """Writes a full traceback to the log file. Anything unexpected should end
    up here rather than closing the window with no explanation."""
    text = "".join(traceback.format_exception(*(exc_info or sys.exc_info())))
    append_log_file("!! ERROR in %s\n%s" % (where, text.rstrip()))
    return text


def log_file_path():
    return os.path.join(config_dir(), "log.txt")


def append_log_file(line):
    """Mirrors the activity log to disk so a problem on someone else's PC can
    be diagnosed from a file instead of a screenshot."""
    with _LOG_FILE_LOCK:
        try:
            path = log_file_path()
            if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_FILE_BYTES:
                try:
                    os.replace(path, path + ".1")
                except Exception:
                    pass
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def atomic_write(path, data, binary=True):
    """Write via a temp file + os.replace so a crash mid-write can never
    leave a half-written (unreadable) profile store behind."""
    tmp = path + ".tmp"
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8"}
    with open(tmp, mode, **kwargs) as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------
# Plain (non-secret) settings
# ---------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "cores": min(2, os.cpu_count() or 1),
    "auto_apply_cores": True,
    "spread_affinity": True,
    "cpu_percent_limit": 0,
    "watch_interval": 2.0,
    "watcher_one_shot": False,
    "watcher_autostart": False,
    "launch_stagger": 3.0,
    "unlock_attempts": 8,
    "unlock_delay": 1.0,
    "launch_timeout": 40,
    "launch_method": "auto",
    "launch_method_learned": "",
    "check_cookies_on_start": True,
    "check_for_updates": True,
    "rejoin_max_attempts": 5,
    "rejoin_cooldown": 60.0,
    "rejoin_reset_after": 300.0,
    "notify_mode": "off",
    "notify_target": "",
    "notify_on_drop": False,
    "notify_on_giveup": True,
    "sound_on_drop": True,
    "background_priority": False,
    "minimize_to_tray": False,
    "fps_cap": "off",
    "start_with_windows": False,
    "start_minimised": False,
    "window_geometry": "",
    "last_tab": 0,
    "ticket_spacing": 5.0,
    "mute_background": False,
    "global_hotkeys": False,
    "restore_layout": True,
    "use_exit_reason": True,
    "tile_monitor": 0,
    "ui_accent_color": "#5a9beb",
    "ui_font_family": "Segoe UI",
    "ui_scale": 1.0,
    "screenshot_enabled": False,
    "screenshot_interval_minutes": 10,
    "refresh_interval_seconds": 3.0,
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            for k, v in stored.items():
                if k in s and isinstance(v, type(s[k])):
                    s[k] = v
                elif k in s and isinstance(s[k], float) and isinstance(v, int):
                    s[k] = float(v)
    except Exception:
        pass
    return s


def save_settings(settings):
    try:
        atomic_write(settings_path(), json.dumps(settings, indent=2), binary=False)
    except Exception:
        pass


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def apply_appearance_settings(root):
    """Overwrites the BLUE / FONT_FAMILY globals from saved settings, and
    sets Tk's own display scaling - all BEFORE any widget exists.

    This has to run before MultiRobloxApp (or any dialog) is constructed:
    every widget in this file reads BLUE/FONT_FAMILY by name at the moment
    it's created, so reassigning these globals first is enough to reskin
    the whole app with no per-widget plumbing - but only for widgets built
    AFTER this runs. There is no live/in-place re-theme; changing these
    settings while already running requires a restart (see restart_app())."""
    global BLUE, FONT_FAMILY
    s = load_settings()

    accent = str(s.get("ui_accent_color") or "").strip()
    if _HEX_COLOR_RE.match(accent):
        BLUE = accent

    family = str(s.get("ui_font_family") or "").strip()
    if family:
        FONT_FAMILY = family

    try:
        scale = float(s.get("ui_scale", 1.0) or 1.0)
        scale = max(0.75, min(2.0, scale))
        root.tk.call("tk", "scaling", scale)
    except Exception:
        pass


# ---------------------------------------------------------------------
# Profile storage (account saver) - encrypted with a master password
# ---------------------------------------------------------------------
CHECK_PLAINTEXT = b"multiroblox-password-check"


def has_master_password():
    return os.path.exists(auth_path())


def derive_key(password, salt):
    """Turns a password + salt into a Fernet-compatible key."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000)
    key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def _write_auth(salt, fernet):
    """Stores the salt plus a small encrypted 'check' blob, so a wrong
    password can be detected even when no profiles are saved yet."""
    payload = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "check": fernet.encrypt(CHECK_PLAINTEXT).decode("ascii"),
        "version": 2,
    }
    atomic_write(auth_path(), json.dumps(payload), binary=False)


def create_master_password(password):
    """First-time setup: generates a salt, saves it, and initializes an
    empty encrypted profile store. Returns a Fernet instance."""
    salt = os.urandom(16)
    fernet = Fernet(derive_key(password, salt))
    _write_auth(salt, fernet)
    save_profiles([], fernet)
    return fernet


def try_unlock(password):
    """Attempts to unlock the existing profile store with a password.
    Returns a Fernet instance on success, or None if the password is wrong."""
    try:
        with open(auth_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        salt = base64.b64decode(data["salt"])
    except Exception:
        return None

    fernet = Fernet(derive_key(password, salt))

    check = data.get("check")
    if check:
        try:
            if fernet.decrypt(check.encode("ascii")) != CHECK_PLAINTEXT:
                return None
        except Exception:
            return None
        return fernet

    # Legacy auth.json (no check blob): fall back to decrypting the store.
    try:
        load_profiles(fernet)
    except Exception:
        return None
    # Upgrade the file in place so future unlocks are verifiable even if
    # the profile store is empty or missing.
    try:
        _write_auth(salt, fernet)
    except Exception:
        pass
    return fernet


def change_master_password(old_fernet, new_password):
    """Re-encrypts the profile store under a brand new password/salt.
    The old store is kept as profiles.enc.bak until the new one has been
    read back successfully."""
    profiles = load_profiles(old_fernet)
    salt = os.urandom(16)
    new_fernet = Fernet(derive_key(new_password, salt))

    if os.path.exists(profiles_path()):
        try:
            with open(profiles_path(), "rb") as f:
                atomic_write(profiles_path() + ".bak", f.read())
        except Exception:
            pass

    save_profiles(profiles, new_fernet)
    _write_auth(salt, new_fernet)
    load_profiles(new_fernet)  # read-back check; raises if something went wrong
    return new_fernet


EXPORT_MAGIC = "multiroblox-profiles-v1"


def export_profiles(profiles, password, path):
    """Writes an encrypted backup under its OWN password. Never plaintext -
    the file holds live account cookies."""
    salt = os.urandom(16)
    fernet = Fernet(derive_key(password, salt))
    clean = [{k: v for k, v in p.items() if not k.startswith("_")}
             for p in profiles]
    payload = {
        "magic": EXPORT_MAGIC,
        "salt": base64.b64encode(salt).decode("ascii"),
        "data": fernet.encrypt(json.dumps(clean).encode("utf-8")).decode("ascii"),
    }
    atomic_write(path, json.dumps(payload, indent=2), binary=False)
    return len(clean)


def import_profiles(password, path):
    """Reads a backup written by export_profiles. Raises on a wrong password."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("magic") != EXPORT_MAGIC:
        raise ValueError("that file is not a MultiRoblox profile backup")
    salt = base64.b64decode(payload["salt"])
    fernet = Fernet(derive_key(password, salt))
    data = json.loads(fernet.decrypt(payload["data"].encode("ascii")).decode("utf-8"))
    return data if isinstance(data, list) else []


def load_profiles(fernet):
    path = profiles_path()
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        token = f.read()
    if not token:
        return []
    decrypted = fernet.decrypt(token)
    data = json.loads(decrypted.decode("utf-8"))
    return data if isinstance(data, list) else []


def save_profiles(profiles, fernet):
    # Keys beginning with "_" are runtime state (cookie health, etc) and are
    # deliberately not written to disk.
    clean = [{k: v for k, v in p.items() if not k.startswith("_")}
             for p in profiles]
    token = fernet.encrypt(json.dumps(clean).encode("utf-8"))
    atomic_write(profiles_path(), token)


# ---------------------------------------------------------------------
# Windows internals: closing the ROBLOX_singletonEvent lock handle
#
# Only plain ctypes types are used here (no ctypes.wintypes) so the file
# can at least be imported on non-Windows machines for editing/linting.
# ---------------------------------------------------------------------
# Fixed-width types on purpose: ctypes.c_ulong is 32-bit on Windows but
# 64-bit on Linux, and a wrong width here silently corrupts every struct.
HANDLE = ctypes.c_void_p
DWORD = ctypes.c_uint32
ULONG = ctypes.c_uint32
NTSTATUS = ctypes.c_int32
BOOL = ctypes.c_int32
USHORT = ctypes.c_uint16
ULONG_PTR = ctypes.c_size_t

class RECT(ctypes.Structure):
    """Defined up here, not next to the window helpers: the argtypes block
    below runs at import time on Windows and needs it already."""
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


ntdll = ctypes.WinDLL("ntdll") if IS_WINDOWS else None
kernel32 = ctypes.WinDLL("kernel32") if IS_WINDOWS else None
user32 = ctypes.WinDLL("user32") if IS_WINDOWS else None
gdi32 = ctypes.WinDLL("gdi32") if IS_WINDOWS else None

if IS_WINDOWS:
    # Explicit argument/return types are essential here: without them,
    # ctypes defaults to 32-bit ints, which silently truncates 64-bit
    # handle values on modern Windows and can cause the wrong handle
    # (or no handle at all) to be duplicated/closed. This is what makes
    # the singleton-handle closing reliable.
    kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
    kernel32.OpenProcess.restype = HANDLE

    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.CloseHandle.restype = BOOL

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = HANDLE

    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = DWORD

    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, BOOL, BOOL, ctypes.c_wchar_p]
    kernel32.CreateEventW.restype = HANDLE

    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, BOOL, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = HANDLE

    # Job objects: how the hard CPU-rate cap is enforced (see
    # apply_cpu_rate_cap below). Unlike everything else in this block, these
    # touch a process only after the user has explicitly turned the cap on.
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD
    ]
    kernel32.SetInformationJobObject.restype = BOOL
    kernel32.AssignProcessToJobObject.argtypes = [HANDLE, HANDLE]
    kernel32.AssignProcessToJobObject.restype = BOOL

    ntdll.NtQuerySystemInformation.argtypes = [
        ULONG, ctypes.c_void_p, ULONG, ctypes.POINTER(ULONG)
    ]
    ntdll.NtQuerySystemInformation.restype = NTSTATUS

    ntdll.NtDuplicateObject.argtypes = [
        HANDLE, HANDLE, HANDLE, ctypes.POINTER(HANDLE), ULONG, ULONG, ULONG
    ]
    ntdll.NtDuplicateObject.restype = NTSTATUS

    ntdll.NtQueryObject.argtypes = [
        HANDLE, ctypes.c_int, ctypes.c_void_p, ULONG, ctypes.POINTER(ULONG)
    ]
    ntdll.NtQueryObject.restype = NTSTATUS

    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_uint]
    user32.SetWindowPos.restype = BOOL
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_void_p, ctypes.c_void_p]
    user32.PostMessageW.restype = BOOL
    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                             ctypes.c_void_p, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = BOOL
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = BOOL
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = BOOL
    user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_uint, ctypes.c_uint]
    user32.RegisterHotKey.restype = BOOL
    user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.UnregisterHotKey.restype = BOOL

    # Window screenshotting (periodic screenshot-to-webhook feature). Uses
    # PrintWindow with PW_RENDERFULLCONTENT, not a screen-region grab - a
    # plain grab only sees whatever is actually on top on screen right now,
    # so a game window that's minimized, covered by something else, or off
    # a visible monitor would come back blank or (worse) capture whatever
    # unrelated window happens to be on top instead. PrintWindow asks the
    # window itself to render its content, which also works for GPU/DirectX
    # surfaces (RENDERFULLCONTENT exists specifically for that - Roblox's
    # client is exactly this kind of window).
    user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
    user32.GetClientRect.restype = BOOL
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.GetDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.PrintWindow.restype = BOOL

    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject.restype = BOOL
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.restype = BOOL
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint]
    gdi32.GetDIBits.restype = ctypes.c_int

SystemHandleInformation = 16
SystemExtendedHandleInformation = 64
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
PROCESS_DUP_HANDLE = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
ObjectNameInformation = 1
ObjectTypeInformation = 2
DUPLICATE_CLOSE_SOURCE = 0x0001

# --- CPU rate cap (Job Objects) ---------------------------------------
JobObjectCpuRateControlInformation = 15
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004


class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    """CpuRate is hundredths of a percent (10000 = 100%) of the WHOLE
    machine's combined capacity, not of one core - see cpu_rate_value()."""
    _fields_ = [("ControlFlags", DWORD), ("CpuRate", DWORD)]
# Handles with exactly this access mask can be synchronous named pipes;
# asking the kernel for their name can block forever. Only relevant on
# the fallback path (the fast path filters by object type first).
DANGEROUS_ACCESS = 0x0012019F

SINGLETON_SUFFIXES = ("_singletonevent", "_singletonmutex")


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", USHORT),
        ("MaximumLength", USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


class SYSTEM_HANDLE_ENTRY(ctypes.Structure):
    """Legacy SystemHandleInformation entry (PIDs are truncated to 16 bits
    in this structure, which is why the extended class below is preferred)."""
    _fields_ = [
        ("OwnerPid", USHORT),
        ("CreatorBackTraceIndex", USHORT),
        ("ObjectType", ctypes.c_ubyte),
        ("HandleFlags", ctypes.c_ubyte),
        ("HandleValue", USHORT),
        ("ObjectPointer", ctypes.c_void_p),
        ("AccessMask", ULONG),
    ]


class SYSTEM_HANDLE_ENTRY_EX(ctypes.Structure):
    """SystemExtendedHandleInformation entry - full-width PIDs and handles."""
    _fields_ = [
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ULONG_PTR),
        ("HandleValue", ULONG_PTR),
        ("GrantedAccess", ULONG),
        ("CreatorBackTraceIndex", USHORT),
        ("ObjectTypeIndex", USHORT),
        ("HandleAttributes", ULONG),
        ("Reserved", ULONG),
    ]


class SYSTEM_HANDLE_INFORMATION_EX(ctypes.Structure):
    _fields_ = [("NumberOfHandles", ULONG_PTR), ("Reserved", ULONG_PTR)]


def _nt_status_bad(status):
    return (status & 0xFFFFFFFF) != 0


def _query_system_information(info_class):
    """Calls NtQuerySystemInformation, growing the buffer until it fits.
    Returns (buffer, status)."""
    length = 0x20000
    buf = None
    status = -1
    for _ in range(32):
        buf = ctypes.create_string_buffer(length)
        return_length = ULONG(0)
        status = ntdll.NtQuerySystemInformation(
            info_class, buf, length, ctypes.byref(return_length)
        ) & 0xFFFFFFFF
        if status == STATUS_INFO_LENGTH_MISMATCH:
            length = max(length * 2, int(return_length.value) + 0x10000)
            continue
        break
    return buf, status


def collect_handles(pids):
    """Returns {pid: [(handle_value, type_index, access_mask), ...]} for the
    given set of PIDs, from a single system-wide handle snapshot."""
    wanted = set(int(p) for p in pids)
    result = {p: [] for p in wanted}
    if not IS_WINDOWS:
        return result

    # --- preferred: extended info class (full 64-bit PIDs and handles) ---
    buf, status = _query_system_information(SystemExtendedHandleInformation)
    if status == 0:
        header = SYSTEM_HANDLE_INFORMATION_EX.from_buffer(buf)
        entry_size = ctypes.sizeof(SYSTEM_HANDLE_ENTRY_EX)
        head_size = ctypes.sizeof(SYSTEM_HANDLE_INFORMATION_EX)
        count = int(header.NumberOfHandles)
        max_count = max(0, (len(buf) - head_size) // entry_size)
        count = min(count, max_count)
        entries = (SYSTEM_HANDLE_ENTRY_EX * count).from_buffer(buf, head_size)
        for e in entries:
            pid = int(e.UniqueProcessId)
            if pid in wanted:
                result[pid].append(
                    (int(e.HandleValue), int(e.ObjectTypeIndex), int(e.GrantedAccess))
                )
        return result

    # --- fallback: legacy info class ---
    buf, status = _query_system_information(SystemHandleInformation)
    if status != 0:
        raise OSError("NtQuerySystemInformation failed: 0x%08X" % status)

    # The legacy structure stores PIDs in 16 bits, so anything above 65535
    # cannot be matched reliably. Better to say so than to silently find
    # nothing and blame the user's permissions.
    for wanted_pid in wanted:
        if wanted_pid > 0xFFFF:
            raise OSError(
                "this Windows build only offers the legacy handle table, which "
                "cannot represent PID %d (it stores PIDs in 16 bits). Restarting "
                "Roblox usually gives it a smaller PID." % wanted_pid)

    count = int(ctypes.cast(buf, ctypes.POINTER(ULONG)).contents.value)
    entry_size = ctypes.sizeof(SYSTEM_HANDLE_ENTRY)
    # The entry array is 8-byte aligned on x64 because of the pointer field.
    head_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
    max_count = max(0, (len(buf) - head_size) // entry_size)
    count = min(count, max_count)
    entries = (SYSTEM_HANDLE_ENTRY * count).from_buffer(buf, head_size)
    for e in entries:
        pid = int(e.OwnerPid)
        if pid in wanted:
            result[pid].append(
                (int(e.HandleValue), int(e.ObjectType), int(e.AccessMask))
            )
    return result


def _query_unicode_string(handle, info_class):
    """Reads an OBJECT_NAME_INFORMATION / OBJECT_TYPE_INFORMATION string.
    Both structures start with a UNICODE_STRING."""
    length = 0x1000
    for _ in range(3):
        buf = ctypes.create_string_buffer(length)
        return_length = ULONG(0)
        status = ntdll.NtQueryObject(
            handle, info_class, buf, length, ctypes.byref(return_length)
        ) & 0xFFFFFFFF
        if status == STATUS_INFO_LENGTH_MISMATCH:
            length = max(length * 2, int(return_length.value) + 0x100)
            continue
        if status != 0:
            return None
        us = UNICODE_STRING.from_buffer(buf)
        if not us.Buffer or us.Length < 2:
            return None
        try:
            return ctypes.wstring_at(us.Buffer, us.Length // 2)
        except Exception:
            return None
    return None


def _get_object_name(handle):
    return _query_unicode_string(handle, ObjectNameInformation)


def _get_object_type(handle):
    return _query_unicode_string(handle, ObjectTypeInformation)


def _probe_type_indices(own_pid):
    """Creates one Event and one Mutant in this process and looks them up in
    the handle table to learn their object-type indices. Filtering the target
    process's handles by those indices makes the scan much faster and avoids
    ever calling NtQueryObject(Name) on a handle type that could hang."""
    handles = []
    try:
        ev = kernel32.CreateEventW(None, True, False, None)
        mu = kernel32.CreateMutexW(None, False, None)
        for h in (ev, mu):
            if h:
                handles.append(int(h))
        if not handles:
            return set()
        table = collect_handles([own_pid]).get(own_pid, [])
        by_value = {hv: ti for hv, ti, _ in table}
        return {by_value[h] for h in handles if h in by_value}
    except Exception:
        return set()
    finally:
        for h in handles:
            try:
                kernel32.CloseHandle(HANDLE(h))
            except Exception:
                pass


_TYPE_INDEX_CACHE = {"value": None}


def close_singleton_mutex(pid, log=print):
    """Finds and closes the Roblox singleton lock handle in the given PID.

    Returns True only if a singleton handle was actually found and closed.
    This never touches any process other than `pid`.
    """
    if not IS_WINDOWS:
        log("Not on Windows - skipping.")
        return False

    own_pid = os.getpid()
    target_process = kernel32.OpenProcess(
        PROCESS_DUP_HANDLE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not target_process:
        target_process = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not target_process:
        err = kernel32.GetLastError()
        if err == 5:
            log("Access denied opening PID %d - try running as Administrator." % pid)
        else:
            log("Failed to open PID %d (error %d)." % (pid, err))
        return False

    try:
        if _TYPE_INDEX_CACHE["value"] is None:
            _TYPE_INDEX_CACHE["value"] = _probe_type_indices(own_pid)
        type_filter = _TYPE_INDEX_CACHE["value"]

        try:
            table = collect_handles([pid]).get(pid, [])
        except OSError as ex:
            log(str(ex))
            return False

        current_process = HANDLE(-1)  # pseudo-handle for "this process"

        for handle_value, type_index, access in table:
            if type_filter:
                if type_index not in type_filter:
                    continue
            elif access == DANGEROUS_ACCESS:
                # No type filter available: skip the handles that are known
                # to be able to hang a name query.
                continue

            source_handle = HANDLE(handle_value)
            dup_handle = HANDLE()
            dup_status = ntdll.NtDuplicateObject(
                target_process, source_handle, current_process,
                ctypes.byref(dup_handle), 0, 0, 0
            )
            if _nt_status_bad(dup_status) or not dup_handle.value:
                continue

            try:
                if not type_filter:
                    kind = (_get_object_type(dup_handle) or "").lower()
                    if kind not in ("event", "mutant"):
                        continue
                name = _get_object_name(dup_handle)
            finally:
                kernel32.CloseHandle(dup_handle)

            if name and name.lower().endswith(SINGLETON_SUFFIXES):
                final_handle = HANDLE()
                ntdll.NtDuplicateObject(
                    target_process, source_handle, current_process,
                    ctypes.byref(final_handle), 0, 0, DUPLICATE_CLOSE_SOURCE
                )
                if final_handle.value:
                    kernel32.CloseHandle(final_handle)
                log("Closed handle: " + name)
                return True

        return False
    finally:
        kernel32.CloseHandle(HANDLE(target_process))


def unlock_with_retry(pid, attempts, delay, log, stop_event=None):
    """Roblox creates its singleton lock a moment AFTER the process starts,
    so a single attempt right after launch often finds nothing. Retries
    quietly and only logs on the final attempt."""
    attempts = max(1, int(attempts))
    quiet = lambda _msg: None  # noqa: E731
    for i in range(attempts):
        if stop_event is not None and stop_event.is_set():
            return False
        if not process_alive(pid):
            return False
        if close_singleton_mutex(pid, log if i == attempts - 1 else quiet):
            return True
        if i < attempts - 1:
            time.sleep(max(0.2, float(delay)))
    return False


def cpu_rate_value(percent_of_core, total_cores):
    """Converts 'X% of ONE core' - the number shown in the UI - into what
    SetInformationJobObject actually wants: hundredths of a percent of the
    WHOLE machine's combined capacity (10000 = every core at 100%)."""
    total_cores = max(1, int(total_cores))
    percent_of_core = max(1, min(100, int(percent_of_core)))
    value = int(round(percent_of_core * 10000 / (100 * total_cores)))
    return max(1, min(10000, value))


def apply_cpu_rate_cap(pid, percent_of_core, log=print):
    """Hard-caps a process's CPU usage with a Windows Job Object.

    This is a stronger limit than CPU affinity: affinity only says WHICH
    cores a process may run on, so a client 'limited' to 2 cores can still
    peg both of them at 100%. A job object's CPU-rate control caps HOW MUCH
    of them it may use, enforced by the Windows scheduler itself, so it
    applies on top of (not instead of) whatever affinity is already set.

    percent_of_core is relative to a single core - 50 means 'never more than
    half of one core's worth', whatever affinity the process has.
    Returns True only if the cap was actually applied.
    """
    if not IS_WINDOWS:
        return False
    hprocess = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not hprocess:
        err = kernel32.GetLastError()
        log("Could not open PID %d to cap its CPU usage (error %d)%s."
            % (pid, err, " - try running as Administrator" if err == 5 else ""))
        return False
    hjob = None
    try:
        hjob = kernel32.CreateJobObjectW(None, None)
        if not hjob:
            log("Could not create a job object to cap PID %d's CPU usage "
                "(error %d)." % (pid, kernel32.GetLastError()))
            return False
        info = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        info.ControlFlags = (JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
                             | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP)
        info.CpuRate = cpu_rate_value(percent_of_core, os.cpu_count() or 1)
        if not kernel32.SetInformationJobObject(
                hjob, JobObjectCpuRateControlInformation,
                ctypes.byref(info), ctypes.sizeof(info)):
            log("Could not set the CPU cap for PID %d (error %d)."
                % (pid, kernel32.GetLastError()))
            return False
        if not kernel32.AssignProcessToJobObject(hjob, hprocess):
            err = kernel32.GetLastError()
            log("Could not apply the CPU cap to PID %d (error %d)%s."
                % (pid, err,
                   " - it may already belong to another job" if err == 5 else ""))
            return False
        return True
    finally:
        # The cap stays in effect for the rest of the process's life once
        # assigned - AssignProcessToJobObject keeps its own reference to
        # both. Closing these handles here only stops us leaking them.
        if hjob:
            kernel32.CloseHandle(HANDLE(hjob))
        kernel32.CloseHandle(HANDLE(hprocess))


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MultiRoblox"


def set_run_at_startup(enabled):
    """Adds or removes this app from the current user's Run key."""
    if not IS_WINDOWS:
        return False, "Windows only"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = '"%s"' % sys.executable
                else:
                    cmd = '"%s" "%s"' % (sys.executable,
                                         os.path.abspath(sys.argv[0]))
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, cmd)
                return True, "will start with Windows"
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
            return True, "will no longer start with Windows"
    except Exception as ex:
        return False, "%s: %s" % (type(ex).__name__, ex)


def can_open_process(pid):
    """Checks whether we could duplicate handles out of a client, without
    touching anything. Used by the diagnostics report."""
    if not IS_WINDOWS:
        return False, "not Windows"
    h = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if h:
        kernel32.CloseHandle(HANDLE(h))
        return True, "ok"
    err = kernel32.GetLastError()
    return False, ("access denied - try running as Administrator" if err == 5
                   else "error %d" % err)


def is_admin():
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Restarts this app with an elevation prompt."""
    if not IS_WINDOWS:
        return False
    try:
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            exe = sys.executable
            params = '"%s"' % os.path.abspath(sys.argv[0])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


# ---------------------------------------------------------------------
# Roblox helpers
# ---------------------------------------------------------------------
ROBLOX_PROCESS_NAMES = ("robloxplayerbeta.exe",)


PLACE_LAUNCHER = ("https://assetgame.roblox.com/game/PlaceLauncher.ashx"
                  "?request=RequestGame&browserTrackerId=%d&placeId=%s"
                  "&isPlayTogetherGame=false")
PRIVATE_LAUNCHER = ("https://assetgame.roblox.com/game/PlaceLauncher.ashx"
                    "?request=RequestPrivateGame&browserTrackerId=%d&placeId=%s"
                    "&accessCode=&linkCode=%s")
JOB_LAUNCHER = ("https://assetgame.roblox.com/game/PlaceLauncher.ashx"
                "?request=RequestGameJob&browserTrackerId=%d&placeId=%s"
                "&gameId=%s&isPlayTogetherGame=false")

# Ways to start an already-signed-in client, tried in this order until one
# produces a client that stays alive. Roblox changes what it accepts without
# notice, so this is deliberately a list rather than one hard-coded guess.
LAUNCH_METHODS = ("handler", "uri", "legacy", "redeem")
LAUNCH_METHOD_LABELS = {
    "handler": "hand the launch URI to the installed bootstrapper",
    "uri": "launch URI handed straight to the client",
    "legacy": "--app -t <ticket>",
    "redeem": "--play with the ticket-redeem endpoint",
}


def handler_exe_from_command(cmd):
    """Pulls the program path out of a registry command string such as
    '"C:\\...\\Bloxstrap.exe" -player "%1"'."""
    if not cmd:
        return None
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end > 1:
            return cmd[1:end]
    return cmd.split(" ")[0] or None


JOB_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def parse_join_target(text):
    """Accepts a bare place ID, a game URL, a private-server link, or a link to
    one specific server, and returns (place_id, link_code, job_id)."""
    t = (text or "").strip()
    if not t:
        return None, None, None
    if t.isdigit():
        return t, None, None

    place = None
    code = None
    job = None
    m = JOB_ID_RE.search(t)
    if m:
        job = m.group(0)
    m = re.search(r"/games/(\d+)", t)
    if m:
        place = m.group(1)
    if not place:
        m = re.search(r"[?&]placeId=(\d+)", t, re.I)
        if m:
            place = m.group(1)
    m = re.search(r"[?&]privateServerLinkCode=([A-Za-z0-9_\-]+)", t, re.I)
    if m:
        code = m.group(1)
    if not code:
        m = re.search(r"[?&]linkCode=([A-Za-z0-9_\-]+)", t, re.I)
        if m:
            code = m.group(1)
    return place, code, job


def build_launch_uri(ticket, place_id=None, link_code=None, job_id=None):
    """The same roblox-player: string the website builds, but handed directly
    to RobloxPlayerBeta.exe so it never touches the protocol handler (and so
    never goes through Bloxstrap)."""
    launchtime = int(time.time() * 1000)
    tracker = random.randint(100000, 175000)
    if place_id and job_id:
        launcher = JOB_LAUNCHER % (tracker, place_id, job_id)
        return ("roblox-player:1+launchmode:play+gameinfo:%s+launchtime:%d"
                "+placelauncherurl:%s+browsertrackerid:%d+robloxLocale:en_us"
                "+gameLocale:en_us"
                % (ticket, launchtime, quote(launcher, safe=""), tracker))
    if place_id and link_code:
        launcher = PRIVATE_LAUNCHER % (tracker, place_id, link_code)
        return ("roblox-player:1+launchmode:play+gameinfo:%s+launchtime:%d"
                "+placelauncherurl:%s+browsertrackerid:%d+robloxLocale:en_us"
                "+gameLocale:en_us"
                % (ticket, launchtime, quote(launcher, safe=""), tracker))
    if place_id:
        launcher = PLACE_LAUNCHER % (tracker, place_id)
        return ("roblox-player:1+launchmode:play+gameinfo:%s+launchtime:%d"
                "+placelauncherurl:%s+browsertrackerid:%d+robloxLocale:en_us"
                "+gameLocale:en_us"
                % (ticket, launchtime, quote(launcher, safe=""), tracker))
    return ("roblox-player:1+launchmode:app+gameinfo:%s+launchtime:%d"
            "+browsertrackerid:%d+robloxLocale:en_us+gameLocale:en_us"
            % (ticket, launchtime, tracker))


def build_launch_command(exe, ticket, method, place_id=None, handler_exe=None,
                         link_code=None, job_id=None):
    if method == "handler":
        # Bloxstrap/Fishstrap accept the same roblox-player: URI the website
        # produces, so the signed-in ticket goes through the bootstrapper the
        # user already chose instead of fighting it.
        if not handler_exe:
            return None
        return [handler_exe, "-player",
                build_launch_uri(ticket, place_id, link_code, job_id)]
    if method == "uri":
        return [exe, build_launch_uri(ticket, place_id, link_code, job_id)]
    if method == "legacy":
        return [exe, "--app", "-t", ticket]
    cmd = [exe, "--play", "-a",
           "https://auth.roblox.com/v1/authentication-ticket/redeem",
           "-t", ticket, "-b", "0"]
    if place_id and job_id:
        cmd += ["-j", JOB_LAUNCHER % (random.randint(100000, 175000),
                                      place_id, job_id)]
    elif place_id and link_code:
        cmd += ["-j", PRIVATE_LAUNCHER % (random.randint(100000, 175000),
                                          place_id, link_code)]
    elif place_id:
        cmd += ["-j", PLACE_LAUNCHER % (random.randint(100000, 175000), place_id)]
    return cmd


FPS_CAP_CHOICES = ("off", "30", "60", "120", "144", "240")


def client_settings_path():
    r"""Roblox reads per-version overrides from
    <version folder>\ClientSettings\ClientAppSettings.json."""
    exe = find_roblox_exe()
    if not exe:
        return None
    return os.path.join(os.path.dirname(exe), "ClientSettings",
                        "ClientAppSettings.json")


def apply_fps_cap(cap):
    """Writes (or clears) Roblox's own frame-rate target. This is the same
    settings file Roblox itself reads - nothing is injected into a running
    client. Returns (ok, message).

    Note it applies to every client started from that version folder, not to
    one instance, and Roblox recreates the folder when it updates - so this is
    re-applied before each launch."""
    path = client_settings_path()
    if not path:
        return False, "couldn't find the Roblox version folder"
    try:
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}

        if not cap or str(cap).lower() in ("off", "0"):
            existing.pop("DFIntTaskSchedulerTargetFps", None)
            if not existing:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                return True, "frame-rate cap removed"
        else:
            existing["DFIntTaskSchedulerTargetFps"] = int(cap)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write(path, json.dumps(existing, indent=2), binary=False)
        return True, ("frame rate capped at %s fps" % cap if cap
                      else "frame-rate cap removed")
    except Exception as ex:
        return False, "%s: %s" % (type(ex).__name__, ex)


def fps_cap_matches(cap):
    """Cheap read-only check: does the on-disk ClientAppSettings.json already
    hold the frame-rate cap this session wants? Lets the caller avoid
    rewriting the file every few seconds just to confirm nothing changed."""
    path = client_settings_path()
    if not path:
        return True  # nothing we could do about it either way
    want = None if not cap or str(cap).lower() in ("off", "0") else int(cap)
    try:
        if not os.path.exists(path):
            return want is None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        have = data.get("DFIntTaskSchedulerTargetFps") if isinstance(data, dict) else None
        return have == want
    except Exception:
        return False  # unreadable/corrupt - treat as drifted so it gets fixed


def detect_launch_handler():
    """Reports which program owns the roblox-player: protocol. Third-party
    bootstrappers (Bloxstrap, Fishstrap) register themselves here, which
    changes how a launch behaves and is worth knowing about when a launch
    starts a process that immediately exits."""
    if not IS_WINDOWS:
        return None, None
    try:
        import winreg
    except Exception:
        return None, None
    key_path = r"Software\Classes\roblox-player\shell\open\command"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key_path) as key:
                cmd = winreg.QueryValueEx(key, "")[0]
        except OSError:
            continue
        except Exception:
            continue
        low = (cmd or "").lower()
        for marker, label in (("bloxstrap", "Bloxstrap"),
                              ("fishstrap", "Fishstrap"),
                              ("robloxplayerbeta", "Roblox (official)"),
                              ("roblox", "Roblox (official)")):
            if marker in low:
                return label, cmd
        return "unknown", cmd
    return None, None


ROBLOX_LOG_DIR_NAME = os.path.join("Roblox", "logs")

# Each entry: (what to look for in the log, a human label, is it worth
# rejoining afterwards). Order matters - the first match wins.
DISCONNECT_PATTERNS = (
    ("moderat", "the account was moderated or banned", False),
    ("banned", "the account was banned", False),
    ("kick", "the account was kicked from the game", False),
    ("teleport", "a teleport between places", True),
    ("idle", "kicked for being idle", False),
    ("afk", "kicked for being idle", False),
    ("crash", "the client crashed", True),
    ("connection lost", "the connection dropped", True),
    ("disconnect", "the client was disconnected", True),
    ("error code: 277", "connection lost (error 277)", True),
    ("timeout", "the connection timed out", True),
)


def roblox_log_dir():
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, ROBLOX_LOG_DIR_NAME) if local else None


def recent_client_log(within_seconds=180):
    """Newest Roblox client log touched recently. Roblox does not put the PID
    in the filename, so the most recently written log is the best match for a
    client that just closed."""
    folder = roblox_log_dir()
    if not folder or not os.path.isdir(folder):
        return None
    newest, newest_time = None, 0
    cutoff = time.time() - within_seconds
    try:
        for name in os.listdir(folder):
            if not name.lower().endswith(".log"):
                continue
            path = os.path.join(folder, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime >= cutoff and mtime > newest_time:
                newest, newest_time = path, mtime
    except Exception:
        return None
    return newest


def unknown_exits_path():
    return os.path.join(config_dir(), "unknown_exits.log")


def explain_exit(path=None, tail_lines=400, capture_unknown=True):
    """Reads the tail of a client log and reports why the client stopped.
    Returns (reason, worth_rejoining). Purely reading files Roblox wrote.

    The patterns below are best guesses at Roblox's wording. When none match,
    the tail is saved to unknown_exits.log so the list can be corrected from
    real evidence instead of more guessing."""
    path = path or recent_client_log()
    if not path:
        return None, True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-tail_lines:]
    except Exception:
        return None, True
    blob = "".join(lines).lower()
    for needle, label, rejoin in DISCONNECT_PATTERNS:
        if needle in blob:
            return label, rejoin

    if capture_unknown:
        try:
            if os.path.getsize(unknown_exits_path()) > 512 * 1024:
                os.replace(unknown_exits_path(), unknown_exits_path() + ".1")
        except OSError:
            pass
        try:
            with open(unknown_exits_path(), "a", encoding="utf-8") as f:
                f.write("\n=== %s  (no pattern matched)  from %s ===\n"
                        % (time.strftime("%Y-%m-%d %H:%M:%S"),
                           os.path.basename(path)))
                f.writelines(lines[-40:])
        except Exception:
            pass
    return None, True


def find_roblox_exe():
    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(local, "Roblox", "Versions", "*", "RobloxPlayerBeta.exe")
    matches = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
    return matches[0] if matches else None


AUTH_TICKET_URL = "https://auth.roblox.com/v1/authentication-ticket"
WHOAMI_URL = "https://users.roblox.com/v1/users/authenticated"


NOTIFY_MODES = ("off", "ntfy", "discord")


def send_phone_alert(mode, target, title, message):
    """Pushes a short alert to a phone. Two zero-account options:
      ntfy    - target is a topic name; install the ntfy app and subscribe
      discord - target is a channel webhook URL
    Returns (ok, detail)."""
    mode = (mode or "off").strip().lower()
    target = (target or "").strip()
    if mode == "off" or not target:
        return False, "phone alerts are off"
    if requests is None:
        return False, "requests is not installed"
    try:
        if mode == "ntfy":
            topic = target.rstrip("/").split("/")[-1]
            r = requests.post(
                "https://ntfy.sh/" + topic,
                data=message.encode("utf-8"),
                headers={"Title": title.encode("ascii", "replace").decode("ascii"),
                         "Tags": "video_game"},
                timeout=15)
            return bool(r.ok), "HTTP %d" % r.status_code
        if mode == "discord":
            r = requests.post(target,
                              json={"content": "**%s**\n%s" % (title, message)},
                              timeout=15)
            return r.status_code in (200, 201, 204), "HTTP %d" % r.status_code
    except Exception as ex:
        return False, "%s: %s" % (type(ex).__name__, ex)
    return False, "unknown alert type '%s'" % mode


def send_discord_screenshots(webhook_url, images):
    """Sends up to 10 images (Discord's own attachment limit per message) in
    ONE webhook request - images: [(filename, png_bytes, caption), ...].
    Reuses the same Discord webhook the text phone-alerts use; there is no
    separate config for this. Returns (ok, detail)."""
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return False, "no Discord webhook configured"
    if requests is None:
        return False, "requests is not installed"
    images = images[:10]
    if not images:
        return False, "nothing to send"
    files = {}
    captions = []
    for i, (filename, data, caption) in enumerate(images):
        files["file%d" % i] = (filename, data, "image/png")
        if caption:
            captions.append(caption)
    payload = {"content": "\n".join(captions)} if captions else {}
    try:
        r = requests.post(webhook_url, data=payload, files=files, timeout=30)
        return r.status_code in (200, 201, 204), "HTTP %d" % r.status_code
    except Exception as ex:
        return False, "%s: %s" % (type(ex).__name__, ex)


def beep(ok=True):
    """A local ping, separate from the phone alert."""
    if not IS_WINDOWS:
        return
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK if ok
                             else winsound.MB_ICONHAND)
    except Exception:
        pass


def _version_tuple(v):
    """'3.10.2' -> (3, 10, 2). Tolerant of a stray non-numeric part (a
    tag like '3.1-beta') by stopping there, so an odd release tag can't
    crash the comparison - it just sorts low."""
    parts = []
    for p in (v or "").strip().lstrip("vV").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts) or (0,)


def check_for_update(timeout=8):
    """Checks GitHub Releases for a version newer than APP_VERSION.
    Returns (latest_version, release_url) if a newer one exists, or None -
    including on any failure (no GITHUB_REPO set, no internet, rate
    limited, etc). Safe to call from a background thread; makes exactly
    one network request."""
    if not GITHUB_REPO or requests is None:
        return None
    try:
        r = requests.get(
            "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO,
            headers={"Accept": "application/vnd.github+json"}, timeout=timeout)
        if not r.ok:
            return None
        data = r.json()
        tag = data.get("tag_name") or ""
        url = data.get("html_url") or ("https://github.com/%s/releases" % GITHUB_REPO)
        if tag and _version_tuple(tag) > _version_tuple(APP_VERSION):
            return tag.lstrip("vV"), url
    except Exception:
        pass
    return None


def set_session_mute(pids_to_mute, pids_to_unmute):
    """Per-application mute, the same thing Windows' volume mixer does.
    Needs pycaw; without it this is simply unavailable."""
    if AudioUtilities is None or not IS_WINDOWS:
        return 0
    changed = 0
    try:
        for session in AudioUtilities.GetAllSessions():
            if not session.Process:
                continue
            pid = session.Process.pid
            volume = session.SimpleAudioVolume
            if volume is None:
                continue
            if pid in pids_to_mute and not volume.GetMute():
                volume.SetMute(1, None)
                changed += 1
            elif pid in pids_to_unmute and volume.GetMute():
                volume.SetMute(0, None)
                changed += 1
    except Exception:
        return changed
    return changed


def foreground_pid():
    """PID owning the window the user is actually looking at."""
    if not IS_WINDOWS:
        return None
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def clean_cookie(raw):
    """Tidies a pasted cookie: strips quotes, a leading '.ROBLOSECURITY=',
    and any line breaks a wrapped paste introduced."""
    c = (raw or "").strip()
    if len(c) > 1 and c[0] == c[-1] and c[0] in "\"'":
        c = c[1:-1].strip()
    if c.lower().startswith(".roblosecurity="):
        c = c.split("=", 1)[1].strip()
    c = "".join(c.split())
    # Copying the whole row out of dev tools brings the cookie's NAME along
    # with the value. The real value always begins at this marker, so drop
    # anything sitting in front of it.
    marker = c.find("_|WARNING:")
    if marker > 0:
        c = c[marker:]
    return c


def cookie_warning(cookie):
    """Catches the copy-paste mistakes before they turn into a 401."""
    if not cookie:
        return None
    if len(cookie) < 200:
        return ("That cookie is only %d characters. A real .ROBLOSECURITY is "
                "usually 800 or more, so it looks like the copy was cut short - "
                "double-click the Value cell in dev tools, then Ctrl+A and "
                "Ctrl+C to get all of it." % len(cookie))
    if not cookie.startswith("_|WARNING:"):
        return ("That doesn't start with '_|WARNING:' the way a .ROBLOSECURITY "
                "value does, so part of the front may be missing.")
    return None


def roblox_headers(cookie):
    return {
        "Cookie": ".ROBLOSECURITY=" + cookie.strip(),
        "Referer": "https://www.roblox.com/",
        "Origin": "https://www.roblox.com",
        "User-Agent": "Roblox/WinInet",
        "Accept": "application/json",
    }


def avatar_cache_path(user_id):
    return os.path.join(icon_dir(), "user_%s.png" % user_id)


def fetch_avatar(user_id):
    """Public headshot endpoint - no authentication needed."""
    if requests is None or not user_id:
        return None
    try:
        r = requests.get(
            "https://thumbnails.roblox.com/v1/users/avatar-headshot"
            "?userIds=%s&size=48x48&format=Png&isCircular=true" % user_id,
            timeout=15)
        if not r.ok:
            return None
        rows = r.json().get("data") or []
        url = rows[0].get("imageUrl") if rows else None
        if not url:
            return None
        img = requests.get(url, timeout=20)
        if img.ok and img.content[:4] == b"\x89PNG":
            return img.content
    except Exception:
        pass
    return None


def with_backoff(call, attempts=3, log=None, what="request"):
    """Retries a Roblox call that comes back 429. Their auth endpoints throttle
    hard, and a throttled reply used to look exactly like a dead cookie."""
    delay = 0.0
    response = None
    for i in range(max(1, attempts)):
        if delay:
            if log:
                log("Roblox is rate limiting the %s - waiting %.0fs before "
                    "trying again." % (what, delay))
            time.sleep(delay)
        response = call()
        if response is None or getattr(response, "status_code", 0) != 429:
            return response
        header = response.headers.get("Retry-After") if hasattr(
            response, "headers") else None
        try:
            delay = min(90.0, float(header)) if header else min(60.0, 5 * (2 ** i))
        except Exception:
            delay = min(60.0, 5 * (2 ** i))
    return response


def validate_cookie(cookie, log=None):
    """Asks Roblox who this cookie belongs to. Returns (ok, message).
    This separates 'the cookie is dead' from 'the ticket endpoint refused
    us' - two very different problems that looked identical before."""
    if requests is None:
        return False, "requests is not installed"
    cookie = (cookie or "").strip()
    if not cookie:
        return False, "no cookie saved (guest profile)"
    try:
        r = with_backoff(
            lambda: requests.get(WHOAMI_URL, headers=roblox_headers(cookie),
                                 timeout=15),
            log=log, what="account check")
        if r is None:
            return False, "no response from Roblox"
        if r.status_code == 429:
            return False, "Roblox is rate limiting - try again shortly"
        if r.status_code == 200:
            data = r.json()
            validate_cookie.last_user = (data.get("id"), data.get("name"))
            return True, "valid - signed in as %s (id %s)" % (
                data.get("name", "?"), data.get("id", "?"))
        if r.status_code in (401, 403):
            return False, ("cookie rejected (HTTP %d) - it has expired, or you "
                           "clicked Log Out in the browser after copying it"
                           % r.status_code)
        return False, "unexpected HTTP %d from Roblox" % r.status_code
    except Exception as ex:
        return False, "%s: %s" % (type(ex).__name__, ex)


validate_cookie.last_user = (None, None)


def get_auth_ticket(cookie, log=None):
    """Returns (ticket, detail). detail explains any failure."""
    if requests is None:
        return None, "requests is not installed"
    cookie = (cookie or "").strip()
    if not cookie:
        return None, "no cookie saved"

    headers = roblox_headers(cookie)
    try:
        session = requests.Session()
        # The first POST is expected to fail with 403 and hand back the CSRF
        # token that the real request needs.
        r1 = with_backoff(
            lambda: session.post(AUTH_TICKET_URL, headers=headers, json={},
                                 timeout=15),
            log=log, what="sign-in request")
        if r1 is None:
            return None, "no response from Roblox"
        if r1.status_code == 429:
            return None, ("Roblox is rate limiting sign-ins - wait a minute and "
                          "try again (launching many accounts at once does this)")
        csrf = r1.headers.get("x-csrf-token")
        if not csrf:
            return None, ("Roblox did not return a CSRF token (HTTP %d). The "
                          "cookie is probably not being accepted." % r1.status_code)
        headers["X-CSRF-TOKEN"] = csrf
        r2 = with_backoff(
            lambda: session.post(AUTH_TICKET_URL, headers=headers, json={},
                                 timeout=15),
            log=log, what="sign-in request")
        if r2 is None:
            return None, "no response from Roblox"
        ticket = r2.headers.get("rbx-authentication-ticket")
        if ticket:
            return ticket, "ok"
        return None, ("no ticket in the response (HTTP %d)" % r2.status_code)
    except Exception as ex:
        return None, "%s: %s" % (type(ex).__name__, ex)


def get_roblox_processes():
    """Returns list of psutil.Process for running Roblox client instances."""
    if psutil is None:
        return []
    result = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info.get("name") or "").lower()
            if name in ROBLOX_PROCESS_NAMES:
                result.append(p)
        except Exception:
            continue
    return result


def process_alive(pid):
    if psutil is None:
        return True
    try:
        p = psutil.Process(pid)
        return p.is_running() and (p.name() or "").lower() in ROBLOX_PROCESS_NAMES
    except Exception:
        return False


def get_window_map():
    """Returns {pid: (hwnd, title)} for visible top-level windows."""
    result = {}
    if not IS_WINDOWS:
        return result
    try:
        proc_type = ctypes.WINFUNCTYPE(BOOL, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value or pid.value in result:
                    return True
                n = user32.GetWindowTextLengthW(hwnd)
                if n <= 0:
                    return True
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, b, n + 1)
                if b.value.strip():
                    result[pid.value] = (hwnd, b.value.strip())
            except Exception:
                pass
            return True

        user32.EnumWindows(proc_type(callback), 0)
    except Exception:
        pass
    return result


SPI_GETWORKAREA = 0x0030
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
SW_RESTORE = 9
WM_CLOSE = 0x0010


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", ctypes.c_uint32)]


MONITORINFOF_PRIMARY = 0x1


def list_monitors():
    """Returns [{'index', 'primary', 'x', 'y', 'w', 'h'}] using each monitor's
    work area, so tiled windows never sit under the taskbar."""
    found = []
    if not IS_WINDOWS:
        return [{"index": 0, "primary": True, "x": 0, "y": 0,
                 "w": 1920, "h": 1040}]
    try:
        proto = ctypes.WINFUNCTYPE(BOOL, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(RECT), ctypes.c_void_p)

        def callback(hmon, _hdc, _rect, _data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                w = info.rcWork
                found.append({
                    "index": len(found),
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    "x": w.left, "y": w.top,
                    "w": w.right - w.left, "h": w.bottom - w.top,
                })
            return True

        user32.EnumDisplayMonitors(None, None, proto(callback), 0)
    except Exception:
        pass
    if not found:
        x, y, w, h = work_area()
        found = [{"index": 0, "primary": True, "x": x, "y": y, "w": w, "h": h}]
    # primary first, then left to right - so "monitor 1" means the main one
    found.sort(key=lambda m: (not m["primary"], m["x"]))
    for i, m in enumerate(found):
        m["index"] = i
    return found


def window_rect(hwnd):
    if not IS_WINDOWS or not hwnd:
        return None
    try:
        r = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return [int(r.left), int(r.top), int(r.right - r.left),
                    int(r.bottom - r.top)]
    except Exception:
        pass
    return None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


PW_RENDERFULLCONTENT = 2
DIB_RGB_COLORS = 0


def capture_window_png(hwnd):
    """Captures a window's own content (see the note above the PrintWindow
    bindings for why this, not a screen-region grab) and returns it as PNG
    bytes, or None on failure. Needs Pillow (bundled with pystray)."""
    if not IS_WINDOWS or not hwnd or Image is None:
        return None
    hwnd_dc = mem_dc = bitmap = None
    try:
        rect = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0 or width * height > 64_000_000:
            return None  # sanity cap - a bogus rect shouldn't try to alloc gigabytes

        hwnd_dc = user32.GetDC(hwnd)
        if not hwnd_dc:
            return None
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        if not mem_dc or not bitmap:
            return None
        old_obj = gdi32.SelectObject(mem_dc, bitmap)
        try:
            if not user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT):
                return None

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height   # negative = top-down rows (matches screen order)
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0    # BI_RGB
            buf = (ctypes.c_ubyte * (width * height * 4))()
            got = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf,
                                 ctypes.byref(bmi), DIB_RGB_COLORS)
            if not got:
                return None
        finally:
            gdi32.SelectObject(mem_dc, old_obj)

        img = Image.frombuffer("RGB", (width, height), bytes(buf),
                               "raw", "BGRX", 0, 1)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        if hwnd_dc:
            user32.ReleaseDC(hwnd, hwnd_dc)


def place_window(hwnd, rect):
    if not IS_WINDOWS or not hwnd or not rect or len(rect) != 4:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        return bool(user32.SetWindowPos(hwnd, None, int(rect[0]), int(rect[1]),
                                        int(rect[2]), int(rect[3]),
                                        SWP_NOZORDER | SWP_SHOWWINDOW))
    except Exception:
        return False


def work_area():
    """Usable desktop area of the primary monitor (excludes the taskbar)."""
    if not IS_WINDOWS:
        return 0, 0, 1920, 1080
    try:
        r = RECT()
        if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        pass
    return 0, 0, 1920, 1080


def tile_windows(handles, layout="grid", gap=2, monitor=None):
    """Arranges the given windows so they do not overlap, on the given monitor
    (a dict from list_monitors) or the primary one. Returns how many moved."""
    if not IS_WINDOWS or not handles:
        return 0
    if monitor:
        x0, y0, total_w, total_h = (monitor["x"], monitor["y"],
                                    monitor["w"], monitor["h"])
    else:
        x0, y0, total_w, total_h = work_area()
    n = len(handles)
    if layout == "columns":
        cols, rows = n, 1
    elif layout == "rows":
        cols, rows = 1, n
    else:
        cols = int(n ** 0.5)
        if cols * cols < n:
            cols += 1
        rows = (n + cols - 1) // cols

    cell_w = max(320, (total_w - gap * (cols + 1)) // cols)
    cell_h = max(240, (total_h - gap * (rows + 1)) // rows)

    moved = 0
    for index, hwnd in enumerate(handles):
        col, r = index % cols, index // cols
        x = x0 + gap + col * (cell_w + gap)
        y = y0 + gap + r * (cell_h + gap)
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
            if user32.SetWindowPos(hwnd, None, int(x), int(y),
                                   int(cell_w), int(cell_h),
                                   SWP_NOZORDER | SWP_SHOWWINDOW):
                moved += 1
        except Exception:
            continue
    return moved


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_1 = 0x31


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_void_p), ("lParam", ctypes.c_void_p),
                ("time", ctypes.c_uint32), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]


class HotkeyListener(threading.Thread):
    """Ctrl+Alt+1..9 to jump to a client. Hotkeys must be registered and
    pumped on one thread, so this owns both."""

    def __init__(self, on_hotkey, count=9, log=print):
        super().__init__(name="roblox-hotkeys", daemon=True)
        self.on_hotkey = on_hotkey
        self.count = max(1, min(9, count))
        self.log = log
        self.thread_id = None
        self.registered = 0
        self._ready = threading.Event()

    def run(self):
        if not IS_WINDOWS:
            self._ready.set()
            return
        try:
            self.thread_id = int(kernel32.GetCurrentThreadId())
            for i in range(self.count):
                if user32.RegisterHotKey(None, i + 1,
                                         MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                                         VK_1 + i):
                    self.registered += 1
            if not self.registered:
                self.log("Couldn't register any global hotkeys - another app "
                         "probably has Ctrl+Alt+1..9.")
                self._ready.set()
                return
            self._ready.set()

            msg = MSG()
            while True:
                got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got in (0, -1):
                    break
                if msg.message == WM_HOTKEY:
                    try:
                        self.on_hotkey(int(msg.wParam or 0))
                    except Exception:
                        pass
        except Exception as ex:
            self.log("Global hotkeys unavailable: %s" % ex)
        finally:
            self._ready.set()
            try:
                for i in range(self.count):
                    user32.UnregisterHotKey(None, i + 1)
            except Exception:
                pass

    def stop(self):
        if self.thread_id:
            try:
                user32.PostThreadMessageW(self.thread_id, WM_QUIT, None, None)
            except Exception:
                pass


def close_window(hwnd):
    """Asks a window to close, the same as clicking its X."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    except Exception:
        return False


def bring_window_to_front(hwnd):
    if not IS_WINDOWS or not hwnd:
        return
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ---------------------------------------------------------------------
# Airplane-style toggle switch (Canvas based, with a smooth slide animation)
# ---------------------------------------------------------------------
class ToggleSwitch(tk.Canvas):
    def __init__(self, master, command=None, **kwargs):
        super().__init__(master, width=76, height=32, bg=BG,
                         highlightthickness=0, cursor="hand2", **kwargs)
        self.command = command
        self.checked = False
        self.enabled = True
        self._knob_x = 6.0
        self._anim_job = None
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _on_click(self, _event):
        if not self.enabled:
            return
        self.checked = not self.checked
        self._animate_to(46.0 if self.checked else 6.0)
        if self.command:
            self.command(self.checked)

    def set_enabled(self, value):
        self.enabled = bool(value)
        self.configure(cursor="hand2" if self.enabled else "arrow")
        self._draw()

    def set_checked(self, value, animate=True):
        """Programmatically set the switch state without firing the command."""
        self.checked = bool(value)
        target = 46.0 if self.checked else 6.0
        if animate:
            self._animate_to(target)
        else:
            self._knob_x = target
            self._draw()

    def _animate_to(self, target):
        if self._anim_job:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

        def step():
            delta = target - self._knob_x
            if abs(delta) < 1.0:
                self._knob_x = target
                self._draw()
                self._anim_job = None
                return
            self._knob_x += delta * 0.35
            self._draw()
            self._anim_job = self.after(12, step)

        step()

    def _draw(self):
        self.delete("all")
        t = (self._knob_x - 6.0) / 40.0
        t = max(0.0, min(1.0, t))
        off_color = "#42424a" if self.enabled else "#333338"
        track_color = self._blend(off_color, GREEN, t)
        self.create_rounded_rect(2, 2, 74, 30, radius=14, fill=track_color, outline="")

        knob_x = self._knob_x
        knob_color = "white" if self.enabled else "#b8b8bd"
        self.create_oval(knob_x, 6, knob_x + 20, 26, fill=knob_color, outline="")

        cx, cy = knob_x + 10, 16
        plane_color = self._blend("#6b6b72", "#3a9463", t)
        self.create_line(cx - 6, cy, cx + 6, cy, fill=plane_color, width=2)
        self.create_line(cx - 2, cy - 4, cx - 2, cy + 4, fill=plane_color, width=2)
        self.create_line(cx + 3, cy - 2, cx + 3, cy + 2, fill=plane_color, width=2)

        text = "ON" if self.checked else "OFF"
        text_x = 14 if self.checked else 58
        self.create_text(text_x, 16, text=text, fill="white" if self.checked else "#cccccc",
                         font=(FONT_FAMILY, 8, "bold"))

    def create_rounded_rect(self, x1, y1, x2, y2, radius=12, **kwargs):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    @staticmethod
    def _blend(c1, c2, t):
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return "#%02x%02x%02x" % (r, g, b)


# ---------------------------------------------------------------------
# Master password dialogs
# ---------------------------------------------------------------------
class BaseDialog(tk.Toplevel):
    def __init__(self, master, title):
        super().__init__(master)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        # Only make this a transient child if the parent is actually on
        # screen. Tk keeps a transient window hidden whenever its master is
        # withdrawn - and the main window IS withdrawn during the password
        # step, which made these dialogs invisible with no taskbar button.
        try:
            if master is not None and master.winfo_viewable():
                self.transient(master)
        except Exception:
            pass

        self.bind("<Escape>", lambda e: self._cancel())
        self.bring_to_front()

        # grab_set() fails on a window that isn't mapped yet, so it has to
        # come after bring_to_front(). Modality is a nicety; never fatal.
        try:
            self.grab_set()
        except Exception:
            pass

    def bring_to_front(self):
        """The main window is hidden while these dialogs run, so without this
        a dialog can open BEHIND whatever else is on screen with no taskbar
        button of its own - it looks like the app never started."""
        try:
            self.update_idletasks()
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
            # Centre once the widgets exist (nothing has been laid out yet at
            # this point, so the size isn't known until the next idle pass).
            self.after(1, self._centre_on_screen)
            self.after(600, self._drop_topmost)
        except Exception:
            pass

    def _centre_on_screen(self):
        try:
            self.update_idletasks()
            w = max(self.winfo_width(), self.winfo_reqwidth())
            h = max(self.winfo_height(), self.winfo_reqheight())
            x = max(0, (self.winfo_screenwidth() - w) // 2)
            y = max(0, (self.winfo_screenheight() - h) // 3)
            self.geometry("+%d+%d" % (x, y))
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _drop_topmost(self):
        try:
            self.attributes("-topmost", False)
        except Exception:
            pass

    def _cancel(self):
        self.result = None
        self.destroy()


class CreatePasswordDialog(BaseDialog):
    """Shown on first run to set up a master password."""
    def __init__(self, master, title="Set a Master Password"):
        super().__init__(master, title)

        tk.Label(self, text="Create a master password to protect your saved accounts.",
                 bg=BG, fg=TEXT, wraplength=340, justify="left").grid(
            row=0, column=0, padx=14, pady=(14, 2), sticky="w"
        )
        tk.Label(self, text="There is no recovery - if you forget it, saved cookies are gone.",
                 bg=BG, fg=AMBER, wraplength=340, justify="left",
                 font=(FONT_FAMILY, 8)).grid(row=1, column=0, padx=14, pady=(0, 8), sticky="w")

        tk.Label(self, text="Password:", bg=BG, fg=TEXT).grid(row=2, column=0, sticky="w", padx=14)
        self.pw1 = tk.Entry(self, show="*", width=40, bg=CONTROL, fg=TEXT,
                            insertbackground=TEXT, relief="flat")
        self.pw1.grid(row=3, column=0, padx=14, pady=(2, 8))

        tk.Label(self, text="Confirm password:", bg=BG, fg=TEXT).grid(row=4, column=0, sticky="w", padx=14)
        self.pw2 = tk.Entry(self, show="*", width=40, bg=CONTROL, fg=TEXT,
                            insertbackground=TEXT, relief="flat")
        self.pw2.grid(row=5, column=0, padx=14, pady=(2, 8))

        self.error_label = tk.Label(self, text="", bg=BG, fg=RED, wraplength=340, justify="left")
        self.error_label.grid(row=6, column=0, sticky="w", padx=14)

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=7, column=0, sticky="e", padx=14, pady=(6, 14))
        tk.Button(btn_frame, text="Create", command=self._submit, bg=CONTROL, fg=TEXT,
                  relief="flat", padx=10).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, bg=CONTROL, fg=TEXT,
                  relief="flat", padx=10).pack(side="left")

        self.pw1.focus_set()
        self.bind("<Return>", lambda e: self._submit())

    def _submit(self):
        p1, p2 = self.pw1.get(), self.pw2.get()
        if not p1:
            self.error_label.configure(text="Password can't be empty.")
            return
        if len(p1) < 6:
            self.error_label.configure(text="Use at least 6 characters.")
            return
        if p1 != p2:
            self.error_label.configure(text="Passwords don't match.")
            return
        self.result = p1
        self.destroy()


class EnterPasswordDialog(BaseDialog):
    """Shown on every launch (after the first) to unlock saved profiles."""
    def __init__(self, master, error_text="", title="Unlock MultiRoblox",
                 prompt="Enter your master password:"):
        super().__init__(master, title)

        tk.Label(self, text=prompt, bg=BG, fg=TEXT).grid(
            row=0, column=0, padx=14, pady=(14, 4), sticky="w"
        )
        self.pw = tk.Entry(self, show="*", width=40, bg=CONTROL, fg=TEXT,
                           insertbackground=TEXT, relief="flat")
        self.pw.grid(row=1, column=0, padx=14, pady=(0, 6))

        self.error_label = tk.Label(self, text=error_text, bg=BG, fg=RED)
        self.error_label.grid(row=2, column=0, sticky="w", padx=14)

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=3, column=0, sticky="e", padx=14, pady=(8, 14))
        tk.Button(btn_frame, text="Unlock", command=self._submit, bg=CONTROL, fg=TEXT,
                  relief="flat", padx=10).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, bg=CONTROL, fg=TEXT,
                  relief="flat", padx=10).pack(side="left")

        self.pw.focus_set()
        self.bind("<Return>", lambda e: self._submit())

    def _submit(self):
        self.result = self.pw.get()
        self.destroy()


def authenticate(root):
    """Runs the master-password flow before the main window is shown.
    Returns (fernet, ok):
      fernet - Fernet instance for reading/writing profiles, or None if the
               account saver is unavailable / not set up
      ok     - False if the user cancelled and the app should exit."""
    if Fernet is None:
        keep_going = messagebox.askyesno(
            "Can't load 'cryptography'",
            "The 'cryptography' package is required for password-protected "
            "profiles, and it could not be imported.\n\n"
            "Reason:\n    %s\n\n"
            "Running from:\n  %s\n\n"
            "Install it into that exact interpreter:\n%s\n\n"
            "Start anyway without the account saver?"
            % (IMPORT_ERRORS.get("cryptography", "unknown"),
               python_description(),
               install_hint("cryptography"))
        )
        return (None, bool(keep_going))

    if not has_master_password():
        dlg = CreatePasswordDialog(root)
        root.wait_window(dlg)
        if not dlg.result:
            return (None, False)
        try:
            return (create_master_password(dlg.result), True)
        except Exception as ex:
            messagebox.showerror("Setup failed", "Could not create the profile store:\n%s" % ex)
            return (None, False)

    error_text = ""
    while True:
        dlg = EnterPasswordDialog(root, error_text)
        root.wait_window(dlg)
        if dlg.result is None:
            return (None, False)
        fernet = try_unlock(dlg.result)
        if fernet is not None:
            return (fernet, True)
        error_text = "Incorrect password - try again."


# ---------------------------------------------------------------------
# Add/edit profile dialog
# ---------------------------------------------------------------------
class ProfileDialog(BaseDialog):
    def __init__(self, master, name="", cookie="", place_id="", link_code="",
                 auto_rejoin=False, cores=0, allow_guest_fallback=False,
                 monitor=0, job_id=""):
        super().__init__(master, "Account Profile")

        tk.Label(self, text="Profile name:", bg=BG, fg=TEXT).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 0)
        )
        self.name_var = tk.StringVar(value=name)
        self.name_entry = tk.Entry(self, textvariable=self.name_var, width=50, bg=CONTROL,
                                   fg=TEXT, insertbackground=TEXT, relief="flat")
        self.name_entry.grid(row=1, column=0, padx=12, pady=4)

        tk.Label(self, text="Roblox .ROBLOSECURITY cookie (kept only on this PC):",
                 bg=BG, fg=TEXT).grid(row=2, column=0, sticky="w", padx=12, pady=(10, 0))
        self.cookie_text = tk.Text(self, width=50, height=4, bg=CONTROL, fg=TEXT,
                                   insertbackground=TEXT, relief="flat")
        self.cookie_text.insert("1.0", cookie)
        self.cookie_text.grid(row=3, column=0, padx=12, pady=4)

        tk.Label(self, text="Game to join - place ID, game link, private server "
                            "link, or a link to one server (optional):",
                 bg=BG, fg=TEXT).grid(row=4, column=0, sticky="w", padx=12, pady=(10, 0))
        existing_join = place_id or ""
        if place_id and job_id:
            existing_join = ("https://www.roblox.com/games/%s?gameId=%s"
                             % (place_id, job_id))
        elif place_id and link_code:
            existing_join = ("https://www.roblox.com/games/%s/?privateServerLinkCode=%s"
                             % (place_id, link_code))
        self.place_var = tk.StringVar(value=existing_join)
        tk.Entry(self, textvariable=self.place_var, width=50, bg=CONTROL, fg=TEXT,
                 insertbackground=TEXT, relief="flat").grid(row=5, column=0, padx=12, pady=4)

        cores_row = tk.Frame(self, bg=BG)
        cores_row.grid(row=9, column=0, sticky="w", padx=12, pady=(6, 0))
        tk.Label(cores_row, text="CPU cores for this account:", bg=BG,
                 fg=TEXT).pack(side="left")
        self.cores_var = tk.IntVar(value=int(cores or 0))
        tk.Spinbox(cores_row, from_=0, to=os.cpu_count() or 1, width=4,
                   textvariable=self.cores_var, bg=CONTROL, fg=TEXT,
                   relief="flat", buttonbackground=CONTROL, insertbackground=TEXT,
                   highlightthickness=1, highlightbackground=BORDER).pack(
            side="left", padx=(8, 8))
        tk.Label(cores_row, text="0 = global", bg=BG, fg=SUBTEXT,
                 font=(FONT_FAMILY, 8)).pack(side="left")
        tk.Label(cores_row, text="   Monitor:", bg=BG, fg=TEXT).pack(side="left")
        self.monitor_var = tk.IntVar(value=int(monitor or 0))
        tk.Spinbox(cores_row, from_=0, to=8, width=3,
                   textvariable=self.monitor_var, bg=CONTROL, fg=TEXT,
                   relief="flat", buttonbackground=CONTROL, insertbackground=TEXT,
                   highlightthickness=1, highlightbackground=BORDER).pack(
            side="left", padx=(6, 6))
        tk.Label(cores_row, text="0 = any", bg=BG, fg=SUBTEXT,
                 font=(FONT_FAMILY, 8)).pack(side="left")

        self.guest_fallback_var = tk.BooleanVar(value=bool(allow_guest_fallback))
        tk.Checkbutton(self, text="If sign-in fails, fall back to a guest launch "
                                  "(opens whichever account Roblox already has)",
                       variable=self.guest_fallback_var, bg=BG, fg=TEXT,
                       selectcolor=CONTROL, activebackground=BG,
                       activeforeground=TEXT, font=(FONT_FAMILY, 9), anchor="w",
                       highlightthickness=0, bd=0, wraplength=380,
                       justify="left").grid(row=10, column=0, sticky="w",
                                            padx=10, pady=(6, 0))

        self.rejoin_var = tk.BooleanVar(value=bool(auto_rejoin))
        tk.Checkbutton(self, text="Rejoin automatically if this client closes "
                                  "(needs the watcher on)",
                       variable=self.rejoin_var, bg=BG, fg=TEXT, selectcolor=CONTROL,
                       activebackground=BG, activeforeground=TEXT,
                       font=(FONT_FAMILY, 9), anchor="w", highlightthickness=0,
                       bd=0).grid(row=6, column=0, sticky="w", padx=10, pady=(6, 0))

        tk.Label(self,
                 text="Tip: get the cookie from your own browser's dev tools while\n"
                      "logged into roblox.com (Storage > Cookies > .ROBLOSECURITY).\n"
                      "Leave it blank for a guest login. Only use accounts you own.\n"
                      "For the game, paste a place ID, a game URL, a private\n"
                      "server link, or a server link with a gameId - blank opens\n"
                      "the Roblox app home page instead.",
                 bg=BG, fg=SUBTEXT, justify="left", font=(FONT_FAMILY, 8)).grid(
            row=7, column=0, sticky="w", padx=12, pady=(4, 8)
        )

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=8, column=0, sticky="e", padx=12, pady=(0, 12))
        tk.Button(btn_frame, text="Save", command=self._save, bg=CONTROL, fg=TEXT,
                  relief="flat", padx=10).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Cancel", command=self._cancel, bg=CONTROL, fg=TEXT,
                  relief="flat", padx=10).pack(side="left")

        self.name_entry.focus_set()

    def _save(self):
        name = self.name_var.get().strip() or "Unnamed Profile"
        cookie = clean_cookie(self.cookie_text.get("1.0", "end"))
        warn = cookie_warning(cookie)
        if warn:
            try:
                if not messagebox.askyesno("This cookie looks wrong",
                                           warn + "\n\nSave it anyway?", parent=self):
                    return
            except Exception:
                pass
        place, link_code, job_id = parse_join_target(self.place_var.get())
        raw_join = self.place_var.get().strip()
        if raw_join and not place:
            try:
                if not messagebox.askyesno(
                        "Game link not understood",
                        "Couldn't find a place ID in:\n\n%s\n\nPaste a place ID, a "
                        "game URL, or a private server link that contains "
                        "privateServerLinkCode.\n\nSave without a game anyway?"
                        % raw_join[:200], parent=self):
                    return
            except Exception:
                pass
        try:
            cores = max(0, int(self.cores_var.get()))
        except Exception:
            cores = 0
        self.result = {"name": name, "cookie": cookie, "place_id": place or "",
                       "link_code": link_code or "", "job_id": job_id or "",
                       "auto_rejoin": bool(self.rejoin_var.get()),
                       "allow_guest_fallback": bool(self.guest_fallback_var.get()),
                       "cores": cores,
                       "monitor": max(0, int(self.monitor_var.get() or 0))}
        self.destroy()


# ---------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------
class MultiRobloxApp:
    def __init__(self, root, fernet):
        self.root = root
        self.fernet = fernet
        self.storage_enabled = fernet is not None
        self.settings = load_settings()

        self.root.title("MultiRoblox %s" % APP_VERSION)
        self.root.configure(bg=BG)
        self.root.minsize(720, 640)
        # Restore the last size and position, falling back to centred.
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            saved = str(self.settings.get("window_geometry", "") or "")
            usable = False
            if re.match(r"^\d+x\d+\+-?\d+\+-?\d+$", saved):
                size, x, y = saved.split("+", 1)[0], None, None
                parts = saved.split("+")
                x, y = int(parts[1]), int(parts[2])
                gw, gh = (int(v) for v in size.split("x"))
                # ignore a position that would land off every monitor
                usable = (-50 <= x <= sw - 200) and (-20 <= y <= sh - 150) \
                    and gw >= 600 and gh >= 400
            if usable:
                self.root.geometry(saved)
            else:
                w, h = 820, 780
                h = min(h, max(560, sh - 120))
                self.root.geometry("%dx%d+%d+%d"
                                   % (w, h, max(0, (sw - w) // 2),
                                      max(0, (sh - h) // 2 - 20)))
        except Exception:
            self.root.geometry("820x780")

        self.profiles = []
        # profile_listbox row -> index into self.profiles - identity when
        # unfiltered, but the filter box can hide rows, so every place that
        # reads curselection() must translate through this, never index
        # self.profiles with a raw listbox row number directly.
        self._profile_index_map = []
        self.profile_load_error = None
        if self.storage_enabled:
            try:
                self.profiles = load_profiles(self.fernet)
            except Exception as ex:
                self.profile_load_error = str(ex)

        # PID bookkeeping. handled[pid] = timestamp it was first seen.
        self.handled = {}
        self.unlocked_pids = set()
        self.in_progress = set()
        self.attempted = set()
        self.pid_labels = {}      # pid -> which profile this client was launched for
        self.rejoin_counts = {}   # profile name -> consecutive quick rejoins
        self.pid_started = {}     # pid -> when we launched it
        self.drop_counts = {}     # profile name -> times its client has closed
        self._priority_state = {}  # pid -> priority class we last set
        self._tray = None
        self.game_names = load_game_cache()
        self.game_icons = {}
        self._game_lookups = set()
        self._icon_ref = None
        self._avatar_ref = None
        self._transient_until = 0.0
        self._ticket_lock = threading.Lock()
        self._last_ticket_at = 0.0
        self._hotkeys = None
        self._reported_failures = set()
        self._failure_counts = {}
        self.layouts = load_layouts()
        self.pid_lock = threading.RLock()

        self.watcher_stop = threading.Event()
        self.watcher_thread = None
        self.watcher_running = False
        self.watcher_gen = 0
        self.watch_count = 0

        self.busy = False
        self.closing = False
        self._proc_cache = {}
        self._window_cache = {}
        self._affinity_cursor = 0
        self._refresh_job = None
        self._settings_save_job = None
        self._last_fps_check = 0.0
        self._screenshot_job = None

        self._build_ui()

        if self.profile_load_error:
            self.log("Could not read saved profiles: %s" % self.profile_load_error)
        if not self.storage_enabled:
            self.log("Account saver disabled ('cryptography' not installed) - "
                     "guest launches still work.")
        if psutil is None:
            self.log("psutil unavailable (%s) - instance detection and core limits are off. "
                     "See the Settings tab." % IMPORT_ERRORS.get("psutil", "unknown"))
            self.toggle.set_enabled(False)
            self.switch_hint.configure(text="needs psutil", fg=AMBER)
        if requests is None:
            self.log("requests unavailable (%s) - signed-in launches are off. "
                     "See the Settings tab." % IMPORT_ERRORS.get("requests", "unknown"))
        if IS_WINDOWS and not is_admin():
            self.log("Running without Administrator rights - if unlocking fails, "
                     "restart elevated from the Settings tab.")
        handler, _cmd = detect_launch_handler()
        if handler and handler != "Roblox (official)":
            self.log("Launch handler for roblox-player: links is %s, not Roblox "
                     "itself. Guest launches go through it." % handler)

        self.log("MultiRoblox %s started. Log file: %s"
                 % (APP_VERSION, log_file_path()))

        self.refresh_profile_list()
        self.refresh_instances()
        self.refresh_sessions()
        self._schedule_refresh()
        self._schedule_screenshots()
        for p in self.profiles:
            if (p.get("place_id") or "").strip():
                self.ensure_game_info(p["place_id"], refresh_list=False)

        if self.settings.get("check_cookies_on_start", True) and self.storage_enabled:
            self.root.after(800, lambda: self.check_all_cookies(announce_good=False))
        if self.settings.get("check_for_updates", True):
            threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

        if self.settings["watcher_autostart"]:
            self.root.after(500, lambda: self.set_watcher(True))
        if self.settings.get("start_minimised"):
            self.root.after(300, self._start_minimised)
        if self.settings.get("global_hotkeys"):
            self.root.after(700, self.start_hotkeys)

    def _start_minimised(self):
        try:
            if self.settings.get("minimize_to_tray") and (
                    self.start_tray() or self._tray is not None):
                self.root.withdraw()
            else:
                self.root.iconify()
        except Exception:
            pass

    # ---------------- small UI helpers ----------------
    def _card(self, parent, title=None, bg=PANEL):
        """A subtly-bordered panel used to visually group a section.

        The returned `body` is deliberately left EMPTY: Tk allows only one
        geometry manager per container, so if the title label were packed
        into `body`, every caller that grid()s into it would blow up with
        'cannot use geometry manager "grid" ... pack is already managing'.
        The title therefore goes into `inner` alongside `body`.
        """
        outer = tk.Frame(parent, bg=BORDER)
        inner = tk.Frame(outer, bg=bg)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        if title:
            tk.Label(inner, text=title, bg=bg, fg=TEXT,
                     font=(FONT_FAMILY, 11, "bold")).pack(
                anchor="w", padx=14, pady=(12, 6))
            body = tk.Frame(inner, bg=bg)
            body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        else:
            body = tk.Frame(inner, bg=bg)
            body.pack(fill="both", expand=True, padx=14, pady=12)
        return outer, body

    def make_button(self, parent, text, command, accent=CONTROL, primary=False):
        base_bg = accent if primary else CONTROL
        hover_bg = self._blend_hover(base_bg)
        btn = tk.Button(
            parent, text=text, command=command, bg=base_bg, fg=TEXT,
            activebackground=hover_bg, activeforeground=TEXT,
            disabledforeground="#6f6f75",
            relief="flat", bd=0, cursor="hand2",
            font=(FONT_FAMILY, 9, "bold" if primary else "normal"),
            highlightthickness=1, highlightbackground=accent, highlightcolor=accent,
            padx=10, pady=6
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_bg)
                 if str(btn["state"]) != "disabled" else None)
        btn.bind("<Leave>", lambda e: btn.configure(bg=base_bg))
        return btn

    def _check(self, parent, text, variable, command=None):
        return tk.Checkbutton(
            parent, text=text, variable=variable, command=command,
            bg=PANEL, fg=TEXT, selectcolor=CONTROL, activebackground=PANEL,
            activeforeground=TEXT, font=(FONT_FAMILY, 9), anchor="w",
            highlightthickness=0, bd=0
        )

    def _spin(self, parent, var, from_, to, width=5, increment=1):
        return tk.Spinbox(
            parent, from_=from_, to=to, textvariable=var, width=width,
            increment=increment, bg=CONTROL, fg=TEXT, relief="flat",
            buttonbackground=CONTROL, insertbackground=TEXT,
            highlightthickness=1, highlightbackground=BORDER,
            command=self._on_setting_changed
        )

    @staticmethod
    def _blend_hover(hex_color):
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r, g, b = min(255, r + 22), min(255, g + 22), min(255, b + 22)
        return "#%02x%02x%02x" % (r, g, b)

    def _update_summary(self):
        """Keeps the status line describing the current state rather than
        leaving the last transient message sitting there."""
        if self.busy or self.closing or time.time() < self._transient_until:
            return
        clients = list(self.pid_labels)
        tree_pids = set(self.tree.get_children())
        running = len(tree_pids)
        unlocked = len([p for p in self.unlocked_pids if str(p) in tree_pids])
        bad = len([p for p in self.profiles if p.get("_cookie_ok") is False])
        bits = ["%d client%s" % (running, "" if running == 1 else "s")]
        if unlocked:
            bits.append("%d unlocked" % unlocked)
        bits.append("watcher %s" % ("ON" if self.watcher_running else "off"))
        if clients:
            bits.append("%d launched here" % len(clients))
        if bad:
            bits.append("%d cookie%s need attention"
                        % (bad, "" if bad == 1 else "s"))
        try:
            self.status_label.configure(text="  ·  ".join(bits),
                                        fg=RED if bad else SUBTEXT)
        except Exception:
            pass

    def set_busy(self, busy, label=None):
        """Disables the launch buttons while an operation is running, so
        clicks can't overlap and stack up multiple launches at once."""
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_launch_profiles, self.btn_launch_guest,
                  self.btn_launch_all):
            b.configure(state=state, cursor="wait" if busy else "hand2")
        if label:
            self.status_label.configure(text=label, fg=SUBTEXT)
            self._transient_until = time.time() + 6
        elif not busy:
            self._transient_until = 0
            self._update_summary()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=3)   # notebook grows most
        self.root.rowconfigure(3, weight=1)   # log grows a little

        PAD = 16
        self._init_style()

        # ---- Header (always visible: title + watcher switch) ----
        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 6))
        header.columnconfigure(1, weight=1)

        accent_bar = tk.Frame(header, bg=GREEN, width=4)
        accent_bar.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 10))

        tk.Label(header, text="MultiRoblox", bg=BG, fg=TEXT,
                 font=(FONT_FAMILY, 18, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(header, text="Run multiple Roblox clients side-by-side, safely.",
                 bg=BG, fg=SUBTEXT, font=(FONT_FAMILY, 9)).grid(row=1, column=1, sticky="w")

        switch_frame = tk.Frame(header, bg=BG)
        switch_frame.grid(row=0, column=2, rowspan=2, sticky="e")

        label_col = tk.Frame(switch_frame, bg=BG)
        label_col.pack(side="left", padx=(0, 10))
        self.switch_label = tk.Label(label_col, text="Watcher: OFF", bg=BG, fg=SUBTEXT,
                                     font=(FONT_FAMILY, 10, "bold"), anchor="e")
        self.switch_label.pack(anchor="e")
        self.switch_hint = tk.Label(label_col, text="auto-unlock new windows",
                                    bg=BG, fg=SUBTEXT, font=(FONT_FAMILY, 8), anchor="e")
        self.switch_hint.pack(anchor="e")

        self.toggle = ToggleSwitch(switch_frame, command=self.on_toggle)
        self.toggle.pack(side="left")

        self.update_banner = tk.Label(
            header, bg=BG, fg=BLUE, font=(FONT_FAMILY, 9, "underline"),
            cursor="hand2")
        self.update_banner.grid(row=2, column=1, columnspan=2, sticky="w", pady=(4, 0))
        self._update_url = None
        self.update_banner.bind("<Button-1>", self._open_update_url)
        self.update_banner.grid_remove()

        # ---- Tabs ----
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=PAD, pady=6)

        self.tab_launcher = tk.Frame(self.notebook, bg=BG)
        self.tab_instances = tk.Frame(self.notebook, bg=BG)
        self.tab_sessions = tk.Frame(self.notebook, bg=BG)
        self.tab_settings = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_launcher, text="  Launcher  ")
        self.notebook.add(self.tab_instances, text="  Instances  ")
        self.notebook.add(self.tab_sessions, text="  History  ")
        self.notebook.add(self.tab_settings, text="  Settings  ")

        self._build_launcher_tab(self.tab_launcher)
        self._build_instances_tab(self.tab_instances)
        self._build_sessions_tab(self.tab_sessions)
        self._build_settings_tab(self.tab_settings)
        try:
            self.notebook.select(int(self.settings.get("last_tab", 0)))
        except Exception:
            pass

        # ---- Status line ----
        self.status_label = tk.Label(self.root, text="Ready.", bg=BG, fg=SUBTEXT,
                                     font=(FONT_FAMILY, 8, "italic"), anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=PAD + 2, pady=(4, 0))

        # ---- Activity log (always visible) ----
        log_outer, log_body = self._card(self.root, None)
        log_outer.grid(row=3, column=0, sticky="nsew", padx=PAD, pady=(6, PAD))
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(1, weight=1)

        log_head = tk.Frame(log_body, bg=PANEL)
        log_head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        log_head.columnconfigure(0, weight=1)
        tk.Label(log_head, text="Activity Log", bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 11, "bold")).grid(row=0, column=0, sticky="w")
        self.make_button(log_head, "Copy", self.copy_log).grid(row=0, column=1, padx=(6, 0))
        self.make_button(log_head, "Clear", self.clear_log).grid(row=0, column=2, padx=(6, 0))

        log_frame = tk.Frame(log_body, bg=PANEL)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=6, bg=CONTROL, fg=SUBTEXT,
                                relief="flat", state="disabled", wrap="word",
                                font=("Consolas", 9), padx=8, pady=6,
                                highlightthickness=1, highlightbackground=BORDER)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.grid(row=0, column=1, sticky="ns")

        # Without this, any exception inside a Tk callback tears the window
        # down with nothing written anywhere. Log it and keep running.
        def on_callback_error(exc, val, tb):
            text = report_crash("a window callback", (exc, val, tb))
            try:
                self.log("Something went wrong: %s: %s" % (exc.__name__, val))
                self.log("  the full details are in the log file "
                         "(Settings > Open Log File).")
            except Exception:
                pass
            print(text, file=sys.stderr) if sys.stderr else None

        self.root.report_callback_exception = on_callback_error

        self._build_menus()
        self._bind_shortcuts()
        self.profile_listbox.bind("<Button-3>", self._popup_profile_menu)
        self.tree.bind("<Button-3>", self._popup_instance_menu)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Unmap>", self._on_window_state)

    def _init_style(self):
        style = ttk.Style()
        try:
            style.theme_use("default")
        except Exception:
            pass
        style.configure("Treeview", background=CONTROL, fieldbackground=CONTROL,
                        foreground=TEXT, rowheight=24, borderwidth=0, font=(FONT_FAMILY, 9))
        style.configure("Treeview.Heading", background=PANEL, foreground=SUBTEXT,
                        relief="flat", font=(FONT_FAMILY, 9, "bold"))
        style.map("Treeview", background=[("selected", "#3a5c78")])
        style.map("Treeview.Heading", background=[("active", PANEL)])

        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
        style.configure("TNotebook.Tab", background=BG, foreground=SUBTEXT,
                        padding=(16, 8), borderwidth=0, font=(FONT_FAMILY, 9, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", PANEL), ("active", CONTROL)],
                  foreground=[("selected", TEXT)])

        style.configure("Vertical.TScrollbar", background=CONTROL, troughcolor=PANEL,
                        bordercolor=PANEL, arrowcolor=SUBTEXT, borderwidth=0)

    # ---------------- Launcher tab ----------------
    def _build_launcher_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        profiles_outer, profiles_body = self._card(parent, "Saved Accounts")
        profiles_outer.grid(row=0, column=0, sticky="nsew", padx=2, pady=(8, 2))
        profiles_body.columnconfigure(0, weight=1)
        profiles_body.rowconfigure(1, weight=1)

        top_row = tk.Frame(profiles_body, bg=PANEL)
        top_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_row.columnconfigure(0, weight=1)

        tk.Label(top_row,
                 text="Ctrl/Shift-click to pick several. Double-click to edit.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).grid(
            row=0, column=0, sticky="w")

        filter_row = tk.Frame(top_row, bg=PANEL)
        filter_row.grid(row=0, column=1, sticky="e")
        tk.Label(filter_row, text="Filter:", bg=PANEL, fg=SUBTEXT,
                 font=(FONT_FAMILY, 8)).pack(side="left", padx=(0, 4))
        self.profile_filter_var = tk.StringVar(value="")
        self.profile_filter_entry = tk.Entry(
            filter_row, textvariable=self.profile_filter_var, width=18,
            bg=CONTROL, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=BORDER)
        self.profile_filter_entry.pack(side="left")
        self.profile_filter_var.trace_add(
            "write", lambda *_: self.refresh_profile_list())

        list_row = tk.Frame(profiles_body, bg=PANEL)
        list_row.grid(row=1, column=0, sticky="nsew")
        list_row.columnconfigure(0, weight=1)
        list_row.rowconfigure(0, weight=1)

        list_wrap = tk.Frame(list_row, bg=PANEL)
        list_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)

        self.profile_listbox = tk.Listbox(
            list_wrap, selectmode=tk.EXTENDED, bg=CONTROL, fg=TEXT,
            highlightthickness=1, highlightbackground=BORDER, relief="flat",
            activestyle="none", height=8, selectbackground="#3a5c78",
            font=(FONT_FAMILY, 9)
        )
        self.profile_listbox.grid(row=0, column=0, sticky="nsew")
        plist_scroll = ttk.Scrollbar(list_wrap, orient="vertical",
                                     command=self.profile_listbox.yview)
        self.profile_listbox.configure(yscrollcommand=plist_scroll.set)
        plist_scroll.grid(row=0, column=1, sticky="ns")
        self.profile_listbox.bind("<Double-Button-1>", lambda e: self.edit_profile())

        btn_col = tk.Frame(list_row, bg=PANEL)
        btn_col.grid(row=0, column=1, sticky="n")
        self.btn_add = self.make_button(btn_col, "Add", self.add_profile)
        self.btn_add.pack(fill="x", pady=2)
        self.btn_edit = self.make_button(btn_col, "Edit", self.edit_profile)
        self.btn_edit.pack(fill="x", pady=2)
        self.btn_remove = self.make_button(btn_col, "Remove", self.remove_profile)
        self.btn_remove.pack(fill="x", pady=2)
        self.btn_test = self.make_button(btn_col, "Test Cookie", self.test_cookie)
        self.btn_test.pack(fill="x", pady=(10, 2))
        self.btn_test_all = self.make_button(btn_col, "Check All",
                                             lambda: self.check_all_cookies(True))
        self.btn_test_all.pack(fill="x", pady=2)
        self.btn_up = self.make_button(btn_col, "Move Up", lambda: self.move_profile(-1))
        self.btn_up.pack(fill="x", pady=(10, 2))
        self.btn_down = self.make_button(btn_col, "Move Down", lambda: self.move_profile(1))
        self.btn_down.pack(fill="x", pady=2)

        if not self.storage_enabled:
            for b in (self.btn_add, self.btn_edit, self.btn_remove,
                      self.btn_up, self.btn_down):
                b.configure(state="disabled")

        launch_row = tk.Frame(profiles_body, bg=PANEL)
        launch_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.btn_launch_profiles = self.make_button(
            launch_row, "▶  Launch Selected Profiles", self.launch_selected_profiles,
            accent=BLUE, primary=True
        )
        self.btn_launch_profiles.pack(side="left")
        self.btn_launch_all = self.make_button(
            launch_row, "▶▶  Launch All", self.launch_all_profiles, accent=BLUE
        )
        self.btn_launch_all.pack(side="left", padx=(10, 0))
        self.btn_launch_guest = self.make_button(
            launch_row, "▶  Launch Guest Instance", self.launch_guest,
            accent=GREEN, primary=True
        )
        self.btn_launch_guest.pack(side="left", padx=(10, 0))

        # ---- game preview for the selected profile ----
        preview = tk.Frame(profiles_body, bg=PANEL)
        preview.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        preview.columnconfigure(1, weight=1)
        preview.columnconfigure(3, weight=1)

        self.avatar_label = tk.Label(preview, bg=CONTROL, width=6, height=3,
                                     highlightthickness=1,
                                     highlightbackground=BORDER)
        self.avatar_label.grid(row=0, column=0, rowspan=2, sticky="nw")

        self.account_label = tk.Label(preview, text="", bg=PANEL, fg=TEXT,
                                      font=(FONT_FAMILY, 10, "bold"), anchor="w")
        self.account_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.account_detail_label = tk.Label(preview, text="", bg=PANEL, fg=SUBTEXT,
                                             font=(FONT_FAMILY, 8), anchor="w",
                                             justify="left")
        self.account_detail_label.grid(row=1, column=1, sticky="nw", padx=(10, 0))

        self.game_icon_label = tk.Label(preview, bg=CONTROL, width=10, height=5,
                                        highlightthickness=1,
                                        highlightbackground=BORDER)
        self.game_icon_label.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(20, 0))

        self.game_name_label = tk.Label(preview, text="Select a profile to see its game",
                                        bg=PANEL, fg=TEXT, font=(FONT_FAMILY, 10, "bold"),
                                        anchor="w", justify="left")
        self.game_name_label.grid(row=0, column=3, sticky="w", padx=(12, 0))

        self.game_detail_label = tk.Label(preview, text="", bg=PANEL, fg=SUBTEXT,
                                          font=(FONT_FAMILY, 8), anchor="w",
                                          justify="left")
        self.game_detail_label.grid(row=1, column=3, sticky="nw", padx=(12, 0))

        self.profile_listbox.bind("<<ListboxSelect>>",
                                  lambda e: self.update_game_preview())

        tk.Label(profiles_body,
                 text="Already-running Roblox windows are never closed or modified.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).grid(
            row=4, column=0, sticky="w", pady=(10, 0))

    # ---------------- Instances tab ----------------
    def _build_instances_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        instances_outer, instances_body = self._card(parent, "Running Instances")
        instances_outer.grid(row=0, column=0, sticky="nsew", padx=2, pady=(8, 2))
        instances_body.columnconfigure(0, weight=1)
        instances_body.rowconfigure(0, weight=1)

        tree_frame = tk.Frame(instances_body, bg=PANEL)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ("pid", "account", "title", "up", "drops", "cores", "mem",
                   "cpu", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8)
        for col, label, w, anchor in [
            ("pid", "PID", 62, "center"),
            ("account", "Account", 120, "w"),
            ("title", "Window Title", 180, "w"),
            ("up", "Uptime", 70, "center"),
            ("drops", "Drops", 55, "center"),
            ("cores", "Cores", 70, "center"),
            ("mem", "Memory", 75, "center"),
            ("cpu", "CPU", 55, "center"),
            ("status", "Status", 90, "center"),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=w, anchor=anchor, stretch=(col == "title"))
        self.tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-Button-1>", lambda e: self.focus_selected())

        controls_row = tk.Frame(instances_body, bg=PANEL)
        controls_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        tk.Label(controls_row, text="Cores per instance:", bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.cores_var = tk.IntVar(value=int(self.settings["cores"]))
        self.cores_spin = self._spin(controls_row, self.cores_var, 1, os.cpu_count() or 1, width=4)
        self.cores_spin.pack(side="left", padx=(8, 16))

        self.auto_limit_var = tk.BooleanVar(value=bool(self.settings["auto_apply_cores"]))
        self._check(controls_row, "Auto-apply to new instances",
                    self.auto_limit_var, self._on_setting_changed).pack(side="left")

        btns_row2 = tk.Frame(instances_body, bg=PANEL)
        btns_row2.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.make_button(btns_row2, "Refresh List", self.refresh_instances).pack(side="left")
        self.make_button(btns_row2, "Apply Core Limit to Selected",
                         self.apply_limit_selected, accent=BLUE).pack(side="left", padx=(10, 0))
        self.make_button(btns_row2, "Unlock Selected",
                         self.unlock_selected).pack(side="left", padx=(10, 0))
        self.make_button(btns_row2, "Bring to Front",
                         self.focus_selected).pack(side="left", padx=(10, 0))

        btns_row3 = tk.Frame(instances_body, bg=PANEL)
        btns_row3.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        tk.Label(btns_row3, text="Arrange:", bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.make_button(btns_row3, "Tile Grid",
                         lambda: self.tile_clients("grid")).pack(side="left", padx=(8, 0))
        self.make_button(btns_row3, "Columns",
                         lambda: self.tile_clients("columns")).pack(side="left", padx=(6, 0))
        self.make_button(btns_row3, "Rows",
                         lambda: self.tile_clients("rows")).pack(side="left", padx=(6, 0))
        self.make_button(btns_row3, "Close Selected", self.close_selected,
                         accent=RED).pack(side="left", padx=(24, 0))
        self.make_button(btns_row3, "Close All", self.close_all_clients,
                         accent=RED).pack(side="left", padx=(6, 0))

        btns_row4 = tk.Frame(instances_body, bg=PANEL)
        btns_row4.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        tk.Label(btns_row4, text="Layout:", bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 9)).pack(side="left")
        self.make_button(btns_row4, "Save Positions",
                         self.save_layout).pack(side="left", padx=(8, 0))
        self.make_button(btns_row4, "Restore Positions",
                         self.restore_layout).pack(side="left", padx=(6, 0))
        tk.Label(btns_row4, text="drag your windows where you want them, then "
                                 "save - each account is put back on launch",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).pack(side="left",
                                                                  padx=(12, 0))

        tk.Label(instances_body,
                 text="Clients are only ever closed when you ask - never "
                      "automatically, and never one you did not pick.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).grid(
            row=5, column=0, sticky="w", pady=(10, 0))

    # ---------------- History tab ----------------
    def _build_sessions_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        outer, body = self._card(parent, "Play History")
        outer.grid(row=0, column=0, sticky="nsew", padx=2, pady=(8, 2))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        self.sessions_summary = tk.Label(body, text="", bg=PANEL, fg=TEXT,
                                         font=(FONT_FAMILY, 9), anchor="w",
                                         justify="left")
        self.sessions_summary.grid(row=0, column=0, sticky="w", pady=(0, 8))

        frame = tk.Frame(body, bg=PANEL)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("started", "profile", "minutes", "reason")
        self.sessions_tree = ttk.Treeview(frame, columns=cols, show="headings",
                                          height=12)
        for col, label, w, anchor in [("started", "Started", 150, "w"),
                                      ("profile", "Account", 140, "w"),
                                      ("minutes", "Minutes", 70, "center"),
                                      ("reason", "How it ended", 280, "w")]:
            self.sessions_tree.heading(col, text=label)
            self.sessions_tree.column(col, width=w, anchor=anchor,
                                      stretch=(col == "reason"))
        self.sessions_tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical",
                            command=self.sessions_tree.yview)
        self.sessions_tree.configure(yscrollcommand=bar.set)
        bar.grid(row=0, column=1, sticky="ns")

        row = tk.Frame(body, bg=PANEL)
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.make_button(row, "Refresh", self.refresh_sessions).pack(side="left")
        self.make_button(row, "Open CSV", self.open_sessions_csv).pack(
            side="left", padx=(10, 0))
        tk.Label(row, text="one row per play session, newest last",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).pack(side="left",
                                                                  padx=(12, 0))

    def refresh_sessions(self):
        try:
            for iid in self.sessions_tree.get_children():
                self.sessions_tree.delete(iid)
        except Exception:
            return
        rows = read_sessions()
        totals = {}
        for r in rows:
            started, _ended, profile, _pid, minutes, reason = r
            try:
                mins = int(minutes)
            except Exception:
                mins = 0
            totals[profile] = totals.get(profile, 0) + mins
            self.sessions_tree.insert("", "end",
                                      values=(started, profile, mins, reason))
        if totals:
            parts = ["%s %dh %02dm" % (name, mins // 60, mins % 60)
                     for name, mins in sorted(totals.items(),
                                              key=lambda kv: -kv[1])]
            self.sessions_summary.configure(
                text="%d session(s) recorded   ·   " % len(rows)
                     + "   ·   ".join(parts[:6]))
        else:
            self.sessions_summary.configure(
                text="No sessions recorded yet - they appear here once a "
                     "launched client closes.")

    def open_sessions_csv(self):
        path = sessions_path()
        if not os.path.exists(path):
            self.log("No session history yet.")
            return
        try:
            if IS_WINDOWS:
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            self.log("Couldn't open %s: %s" % (path, ex))

    # ---------------- Settings tab ----------------
    def _build_settings_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        outer, holder = self._card(parent, "Settings")
        outer.grid(row=0, column=0, sticky="nsew", padx=2, pady=(8, 2))
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        # The settings list is taller than the window, so it lives on a
        # scrollable canvas: canvas holds a frame, the frame holds the rows.
        canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        sbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        sbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=sbar.set)

        body = tk.Frame(canvas, bg=PANEL)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def _resize_scrollregion(_event=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

        def _match_width(event):
            try:
                canvas.itemconfigure(body_id, width=event.width)
            except Exception:
                pass

        body.bind("<Configure>", _resize_scrollregion)
        canvas.bind("<Configure>", _match_width)

        def _wheel(event):
            try:
                if event.delta:
                    canvas.yview_scroll(-1 * int(event.delta / 120), "units")
                elif event.num in (4, 5):          # X11 style
                    canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
            except Exception:
                pass

        def _grab_wheel(_event=None):
            canvas.bind_all("<MouseWheel>", _wheel)
            canvas.bind_all("<Button-4>", _wheel)
            canvas.bind_all("<Button-5>", _wheel)

        def _release_wheel(_event=None):
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                try:
                    canvas.unbind_all(seq)
                except Exception:
                    pass

        # Only steal the wheel while the pointer is actually over Settings,
        # so the activity log keeps scrolling normally.
        canvas.bind("<Enter>", _grab_wheel)
        canvas.bind("<Leave>", _release_wheel)
        body.bind("<Enter>", _grab_wheel)
        body.bind("<Leave>", _release_wheel)

        body.columnconfigure(1, weight=1)

        row = 0

        def section(text):
            nonlocal row
            tk.Label(body, text=text, bg=PANEL, fg=BLUE,
                     font=(FONT_FAMILY, 9, "bold")).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(10, 4))
            row += 1

        def labelled(text, widget, hint=None):
            nonlocal row
            tk.Label(body, text=text, bg=PANEL, fg=TEXT, font=(FONT_FAMILY, 9)).grid(
                row=row, column=0, sticky="w", pady=3)
            widget.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=3)
            if hint:
                tk.Label(body, text=hint, bg=PANEL, fg=SUBTEXT,
                         font=(FONT_FAMILY, 8)).grid(row=row, column=2, sticky="w", padx=(10, 0))
            row += 1

        def full(widget):
            nonlocal row
            widget.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
            row += 1

        # --- appearance ---
        section("Appearance")

        accent_frame = tk.Frame(body, bg=PANEL)
        self.accent_swatch = tk.Button(
            accent_frame, text="   ", width=3,
            bg=str(self.settings.get("ui_accent_color") or BLUE),
            relief="flat", cursor="hand2", command=self._pick_accent_color)
        self.accent_swatch.pack(side="left")
        tk.Button(accent_frame, text="Reset", command=self._reset_accent_color,
                 bg=CONTROL, fg=TEXT, relief="flat", padx=8,
                 cursor="hand2").pack(side="left", padx=(6, 0))
        labelled("Accent color:", accent_frame,
                 "buttons/highlights/borders only - restart to apply")

        installed_fonts = sorted(set(tkfont.families()), key=str.lower)
        current_font = str(self.settings.get("ui_font_family") or FONT_FAMILY)
        if current_font not in installed_fonts:
            installed_fonts = [current_font] + installed_fonts
        self.font_family_var = tk.StringVar(value=current_font)
        font_menu = tk.OptionMenu(body, self.font_family_var, *installed_fonts)
        try:
            font_menu.configure(bg=CONTROL, fg=TEXT, activebackground=BORDER,
                               activeforeground=TEXT, relief="flat",
                               highlightthickness=1, highlightbackground=BORDER,
                               font=(FONT_FAMILY, 9), width=18)
            font_menu["menu"].configure(bg=CONTROL, fg=TEXT, relief="flat")
        except Exception:
            pass
        labelled("Font:", font_menu, "restart to apply")
        self.font_family_var.trace_add("write", lambda *_: self._on_setting_changed())

        self.ui_scale_var = tk.DoubleVar(value=float(self.settings.get("ui_scale", 1.0)))
        labelled("UI scale:",
                 self._spin(body, self.ui_scale_var, 0.75, 2.0, width=6, increment=0.05),
                 "bigger/smaller everything - restart to apply")

        full(self.make_button(body, "Restart Now to Apply Appearance",
                              self.restart_app, accent=AMBER))

        # --- watcher ---
        section("Watcher")
        self.interval_var = tk.DoubleVar(value=float(self.settings["watch_interval"]))
        labelled("Poll interval (seconds):",
                 self._spin(body, self.interval_var, 0.5, 30.0, width=6, increment=0.5),
                 "how often to look for new Roblox windows")

        self.one_shot_var = tk.BooleanVar(value=bool(self.settings["watcher_one_shot"]))
        full(self._check(body, "One-shot mode (switch the watcher off after the first "
                               "instance it handles)", self.one_shot_var,
                         self._on_setting_changed))

        self.autostart_var = tk.BooleanVar(value=bool(self.settings["watcher_autostart"]))
        full(self._check(body, "Turn the watcher on automatically when MultiRoblox starts",
                         self.autostart_var, self._on_setting_changed))

        # --- unlocking ---
        section("Unlocking")
        self.attempts_var = tk.IntVar(value=int(self.settings["unlock_attempts"]))
        labelled("Unlock attempts:", self._spin(body, self.attempts_var, 1, 30, width=6),
                 "Roblox creates its lock a moment after starting")
        self.unlock_delay_var = tk.DoubleVar(value=float(self.settings["unlock_delay"]))
        labelled("Delay between attempts (s):",
                 self._spin(body, self.unlock_delay_var, 0.2, 10.0, width=6, increment=0.2))

        # --- launching ---
        section("Launching")
        self.stagger_var = tk.DoubleVar(value=float(self.settings["launch_stagger"]))
        labelled("Stagger between profiles (s):",
                 self._spin(body, self.stagger_var, 0.0, 30.0, width=6, increment=0.5),
                 "keeps two launches from racing for the lock")
        self.timeout_var = tk.IntVar(value=int(self.settings["launch_timeout"]))
        labelled("Wait for new window (s):", self._spin(body, self.timeout_var, 5, 180, width=6))
        self.ticket_gap_var = tk.DoubleVar(
            value=float(self.settings.get("ticket_spacing", 5.0)))
        labelled("Gap between sign-ins (s):",
                 self._spin(body, self.ticket_gap_var, 0, 60, width=6, increment=1),
                 "stops Roblox rate limiting during Launch All")

        self.method_var = tk.StringVar(
            value=str(self.settings.get("launch_method", "auto")))
        method_menu = tk.OptionMenu(body, self.method_var, "auto", *LAUNCH_METHODS)  # noqa: E501
        try:
            method_menu.configure(bg=CONTROL, fg=TEXT, activebackground=BORDER,
                                  activeforeground=TEXT, relief="flat",
                                  highlightthickness=1, highlightbackground=BORDER,
                                  font=(FONT_FAMILY, 9), width=10)
            method_menu["menu"].configure(bg=CONTROL, fg=TEXT, relief="flat")
        except Exception:
            pass
        labelled("Signed-in launch method:", method_menu,
                 "auto tries each until one keeps a client open")
        self.method_var.trace_add("write", lambda *_: self._on_setting_changed())

        self.check_cookies_var = tk.BooleanVar(
            value=bool(self.settings.get("check_cookies_on_start", True)))
        full(self._check(body, "Check saved cookies when MultiRoblox starts",
                         self.check_cookies_var, self._on_setting_changed))

        self.check_updates_var = tk.BooleanVar(
            value=bool(self.settings.get("check_for_updates", True)))
        full(self._check(body, "Check for a newer version on startup",
                         self.check_updates_var, self._on_setting_changed))

        # --- auto-rejoin ---
        section("Auto-rejoin")
        self.rejoin_max_var = tk.IntVar(
            value=int(self.settings.get("rejoin_max_attempts", 5)))
        labelled("Max rejoins per profile:",
                 self._spin(body, self.rejoin_max_var, 0, 50, width=6),
                 "per session; a manual launch resets it")
        self.rejoin_cooldown_var = tk.DoubleVar(
            value=float(self.settings.get("rejoin_cooldown", 60.0)))
        labelled("Wait before rejoining (s):",
                 self._spin(body, self.rejoin_cooldown_var, 5, 600, width=6, increment=5))
        self.rejoin_reset_var = tk.DoubleVar(
            value=float(self.settings.get("rejoin_reset_after", 300.0)))
        labelled("A session this long resets the count (s):",
                 self._spin(body, self.rejoin_reset_var, 30, 3600, width=6, increment=30),
                 "so only rapid repeat failures count against the limit")
        tk.Label(body, text="Turn rejoining on per profile (Edit > Rejoin "
                            "automatically). It only runs while the watcher is on.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8), justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row += 1

        # --- cpu ---
        section("CPU")
        self.spread_var = tk.BooleanVar(value=bool(self.settings["spread_affinity"]))
        full(self._check(body, "Spread instances across different cores "
                               "(instead of pinning them all to cores 0..N)",
                         self.spread_var, self._on_setting_changed))
        self.cpu_cap_var = tk.IntVar(
            value=int(self.settings.get("cpu_percent_limit", 0) or 0))
        labelled("Hard-cap CPU per instance (% of one core, 0 = off):",
                 self._spin(body, self.cpu_cap_var, 0, 100, width=6),
                 "enforced by Windows - affinity alone still lets a client "
                 "peg the cores it has")
        tk.Label(body, text="    Affinity (above/on the Instances tab) picks WHICH "
                            "cores a client may use; this caps HOW MUCH of them "
                            "it may actually use.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8), justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1

        # --- alerts ---
        section("Alerts")
        self.notify_mode_var = tk.StringVar(
            value=str(self.settings.get("notify_mode", "off")))
        alert_menu = tk.OptionMenu(body, self.notify_mode_var, *NOTIFY_MODES)
        try:
            alert_menu.configure(bg=CONTROL, fg=TEXT, activebackground=BORDER,
                                 activeforeground=TEXT, relief="flat",
                                 highlightthickness=1, highlightbackground=BORDER,
                                 font=(FONT_FAMILY, 9), width=10)
            alert_menu["menu"].configure(bg=CONTROL, fg=TEXT, relief="flat")
        except Exception:
            pass
        labelled("Phone alerts:", alert_menu, "ntfy topic, or a Discord webhook")
        self.notify_mode_var.trace_add("write", lambda *_: self._on_setting_changed())

        self.notify_target_var = tk.StringVar(
            value=str(self.settings.get("notify_target", "")))
        target_entry = tk.Entry(body, textvariable=self.notify_target_var, width=46,
                                bg=CONTROL, fg=TEXT, insertbackground=TEXT,
                                relief="flat", highlightthickness=1,
                                highlightbackground=BORDER)
        labelled("Topic / webhook URL:", target_entry)
        self.notify_target_var.trace_add("write", lambda *_: self._on_setting_changed())

        self.notify_drop_var = tk.BooleanVar(
            value=bool(self.settings.get("notify_on_drop", False)))
        full(self._check(body, "Alert me every time a client closes",
                         self.notify_drop_var, self._on_setting_changed))
        self.notify_giveup_var = tk.BooleanVar(
            value=bool(self.settings.get("notify_on_giveup", True)))
        full(self._check(body, "Alert me when a profile gives up rejoining "
                               "(recommended)",
                         self.notify_giveup_var, self._on_setting_changed))
        self.sound_var = tk.BooleanVar(
            value=bool(self.settings.get("sound_on_drop", True)))
        full(self._check(body, "Play a sound on this PC when a client closes",
                         self.sound_var, self._on_setting_changed))
        test_row = tk.Frame(body, bg=PANEL)
        test_row.grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 0))
        row += 1
        self.make_button(test_row, "Send Test Alert",
                         self.send_test_alert).pack(side="left")
        tk.Label(test_row, text="ntfy: pick any hard-to-guess topic name, then "
                                "subscribe to it in the ntfy phone app.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).pack(side="left", padx=(10, 0))

        self.screenshot_enabled_var = tk.BooleanVar(
            value=bool(self.settings.get("screenshot_enabled", False)))
        full(self._check(body, "Send periodic screenshots of each running "
                               "Roblox window to the Discord webhook above",
                         self.screenshot_enabled_var, self._on_setting_changed))
        self.screenshot_interval_var = tk.IntVar(
            value=int(self.settings.get("screenshot_interval_minutes", 10)))
        labelled("Every (minutes):",
                 self._spin(body, self.screenshot_interval_var, 1, 180, width=6),
                 "needs 'Discord' selected above, with a webhook URL set")

        # --- window / performance ---
        section("Window and performance")
        preset_row = tk.Frame(body, bg=PANEL)
        preset_row.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1
        self.make_button(preset_row, "Optimize for a Low-End PC",
                         self._apply_low_end_preset, accent=AMBER).pack(side="left")
        tk.Label(preset_row, text="   sets the options below to sensible values for "
                                  "a weak CPU - you can still change any of them after",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).pack(side="left")

        self.refresh_interval_var = tk.DoubleVar(
            value=float(self.settings.get("refresh_interval_seconds", 3.0)))
        labelled("Instance list refresh (seconds):",
                 self._spin(body, self.refresh_interval_var, 1.0, 30.0,
                           width=6, increment=0.5),
                 "how often MultiRoblox itself re-scans - higher uses less CPU")

        self.fps_var = tk.StringVar(value=str(self.settings.get("fps_cap", "off")))
        fps_menu = tk.OptionMenu(body, self.fps_var, *FPS_CAP_CHOICES)
        try:
            fps_menu.configure(bg=CONTROL, fg=TEXT, activebackground=BORDER,
                               activeforeground=TEXT, relief="flat",
                               highlightthickness=1, highlightbackground=BORDER,
                               font=(FONT_FAMILY, 9), width=10)
            fps_menu["menu"].configure(bg=CONTROL, fg=TEXT, relief="flat")
        except Exception:
            pass
        labelled("Frame rate cap:", fps_menu,
                 "30 saves a lot of CPU/GPU when several clients are open")
        self.fps_var.trace_add("write", lambda *_: self._on_fps_changed())
        tk.Label(body, text="    Applies to every Roblox client on this PC, not "
                            "one instance, and is re-applied at each launch.",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.bg_priority_var = tk.BooleanVar(
            value=bool(self.settings.get("background_priority", False)))
        full(self._check(body, "Run background clients at below-normal priority "
                               "(helps the window you are playing)",
                         self.bg_priority_var, self._on_setting_changed))
        self.tray_var = tk.BooleanVar(
            value=bool(self.settings.get("minimize_to_tray", False)))
        tray_check = self._check(body, "Minimise to the notification area "
                                       "instead of the taskbar",
                                 self.tray_var, self._on_setting_changed)
        full(tray_check)
        if pystray is None:
            try:
                tray_check.configure(state="disabled")
                tk.Label(body, text="    (needs pystray + Pillow in the build)",
                         bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).grid(
                    row=row, column=0, columnspan=3, sticky="w")
                row += 1
            except Exception:
                pass

        self.mute_var = tk.BooleanVar(
            value=bool(self.settings.get("mute_background", False)))
        mute_check = self._check(body, "Mute every client except the one you "
                                       "are looking at",
                                self.mute_var, self._on_setting_changed)
        full(mute_check)
        if AudioUtilities is None:
            try:
                mute_check.configure(state="disabled")
                tk.Label(body, text="    (needs pycaw in the build)",
                         bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).grid(
                    row=row, column=0, columnspan=3, sticky="w")
                row += 1
            except Exception:
                pass

        self.hotkeys_var = tk.BooleanVar(
            value=bool(self.settings.get("global_hotkeys", False)))
        full(self._check(body, "Global hotkeys: Ctrl+Alt+1..9 jump to a client",
                         self.hotkeys_var, self._on_hotkeys_changed))

        self.restore_layout_var = tk.BooleanVar(
            value=bool(self.settings.get("restore_layout", True)))
        full(self._check(body, "Put each account's window back where you saved it",
                         self.restore_layout_var, self._on_setting_changed))

        self.exit_reason_var = tk.BooleanVar(
            value=bool(self.settings.get("use_exit_reason", True)))
        full(self._check(body, "Read Roblox's own log to find out why a client "
                               "closed (and skip pointless rejoins)",
                         self.exit_reason_var, self._on_setting_changed))

        monitors = list_monitors()
        self.tile_monitor_var = tk.IntVar(
            value=int(self.settings.get("tile_monitor", 0)))
        labelled("Tile on monitor:",
                 self._spin(body, self.tile_monitor_var, 0, max(1, len(monitors)),
                            width=6),
                 "0 = primary; %d detected" % len(monitors))

        self.startup_var = tk.BooleanVar(
            value=bool(self.settings.get("start_with_windows", False)))
        full(self._check(body, "Start MultiRoblox when Windows starts",
                         self.startup_var, self._on_startup_changed))
        self.start_min_var = tk.BooleanVar(
            value=bool(self.settings.get("start_minimised", False)))
        full(self._check(body, "Start minimised", self.start_min_var,
                         self._on_setting_changed))

        # --- status / maintenance ---
        section("Status")
        self.env_label = tk.Label(body, text=self._env_summary(), bg=PANEL, fg=SUBTEXT,
                                  font=("Consolas", 8), justify="left", anchor="w")
        self.env_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1

        maint = tk.Frame(body, bg=PANEL)
        maint.grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))
        row += 1
        self.btn_change_pw = self.make_button(maint, "Change Master Password",
                                              self.change_password)
        self.btn_change_pw.pack(side="left")
        if not self.storage_enabled:
            self.btn_change_pw.configure(state="disabled")
        self.make_button(maint, "Open Config Folder",
                         self.open_config_folder).pack(side="left", padx=(10, 0))
        self.make_button(maint, "Open Log File",
                         self.open_log_file).pack(side="left", padx=(10, 0))
        self.make_button(maint, "Diagnose", self.diagnose,
                         accent=BLUE).pack(side="left", padx=(10, 0))

        backup_row = tk.Frame(body, bg=PANEL)
        backup_row.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        row += 1
        self.btn_export = self.make_button(backup_row, "Export Profiles...",
                                           self.export_profiles_dialog)
        self.btn_export.pack(side="left")
        self.btn_import = self.make_button(backup_row, "Import Profiles...",
                                           self.import_profiles_dialog)
        self.btn_import.pack(side="left", padx=(10, 0))
        tk.Label(backup_row, text="encrypted with a password you choose",
                 bg=PANEL, fg=SUBTEXT, font=(FONT_FAMILY, 8)).pack(side="left",
                                                                  padx=(10, 0))
        if not self.storage_enabled:
            self.btn_export.configure(state="disabled")
            self.btn_import.configure(state="disabled")
        if IS_WINDOWS and not is_admin():
            self.make_button(maint, "Restart as Administrator", self.restart_elevated,
                             accent=AMBER).pack(side="left", padx=(10, 0))

        # keep settings in sync when values are typed rather than clicked
        for var in (self.cores_var, self.interval_var, self.attempts_var,
                    self.unlock_delay_var, self.stagger_var, self.timeout_var,
                    self.rejoin_max_var, self.rejoin_cooldown_var,
                    self.rejoin_reset_var, self.ticket_gap_var,
                    self.tile_monitor_var, self.cpu_cap_var, self.ui_scale_var,
                    self.screenshot_interval_var, self.refresh_interval_var):
            var.trace_add("write", lambda *_: self._on_setting_changed())

        self.root.after(120, _resize_scrollregion)

    def _env_summary(self):
        def mark(ok):
            return "OK  " if ok else "--  "

        lines = []
        for name, obj, what in (
            ("psutil", psutil, "instance list, core limits"),
            ("requests", requests, "signed-in launches"),
            ("cryptography", Fernet, "encrypted account saver"),
        ):
            lines.append("%s%-14s (%s)" % (mark(obj is not None), name, what))
            if obj is None:
                lines.append("      why: %s" % IMPORT_ERRORS.get(name, "unknown"))
                for hint_line in install_hint(name).splitlines():
                    lines.append("      " + hint_line.strip())

        lines.append("%s%-14s (%s)" % (mark(IS_WINDOWS), "Windows", os.name))
        lines.append("%s%-14s (needed on some systems to unlock)"
                     % (mark(is_admin()), "Administrator"))
        lines.append("")
        lines.append("running from: " + python_description().replace("\n  ", " / "))
        lines.append("config: %s" % config_dir())
        return "\n".join(lines)

    # ---------------- update check ----------------
    def _check_for_updates_worker(self):
        result = check_for_update()
        if result:
            self.root.after(0, lambda: self._show_update_banner(*result))

    def _show_update_banner(self, version, url):
        if self.closing:
            return
        self._update_url = url
        self.update_banner.configure(
            text="MultiRoblox %s is available (you have %s) - click to download"
                 % (version, APP_VERSION))
        self.update_banner.grid()

    def _open_update_url(self, _event=None):
        if self._update_url:
            try:
                os.startfile(self._update_url)
            except Exception:
                pass

    # ---------------- settings plumbing ----------------
    def _on_setting_changed(self, *_args):
        if self.closing:
            return
        try:
            self.settings["cores"] = int(self.cores_var.get())
            self.settings["auto_apply_cores"] = bool(self.auto_limit_var.get())
            self.settings["spread_affinity"] = bool(self.spread_var.get())
            self.settings["cpu_percent_limit"] = max(0, int(self.cpu_cap_var.get()))
            self.settings["watch_interval"] = float(self.interval_var.get())
            self.settings["watcher_one_shot"] = bool(self.one_shot_var.get())
            self.settings["watcher_autostart"] = bool(self.autostart_var.get())
            self.settings["launch_stagger"] = float(self.stagger_var.get())
            self.settings["unlock_attempts"] = int(self.attempts_var.get())
            self.settings["unlock_delay"] = float(self.unlock_delay_var.get())
            self.settings["launch_timeout"] = int(self.timeout_var.get())
            self.settings["launch_method"] = str(self.method_var.get())
            self.settings["ticket_spacing"] = float(self.ticket_gap_var.get())
            self.settings["check_cookies_on_start"] = bool(
                self.check_cookies_var.get())
            self.settings["check_for_updates"] = bool(self.check_updates_var.get())
            self.settings["rejoin_max_attempts"] = int(self.rejoin_max_var.get())
            self.settings["rejoin_cooldown"] = float(self.rejoin_cooldown_var.get())
            self.settings["rejoin_reset_after"] = float(self.rejoin_reset_var.get())
            self.settings["notify_mode"] = str(self.notify_mode_var.get())
            self.settings["notify_target"] = str(self.notify_target_var.get()).strip()
            self.settings["notify_on_drop"] = bool(self.notify_drop_var.get())
            self.settings["notify_on_giveup"] = bool(self.notify_giveup_var.get())
            self.settings["sound_on_drop"] = bool(self.sound_var.get())
            self.settings["background_priority"] = bool(self.bg_priority_var.get())
            self.settings["minimize_to_tray"] = bool(self.tray_var.get())
            self.settings["fps_cap"] = str(self.fps_var.get())
            self.settings["start_minimised"] = bool(self.start_min_var.get())
            self.settings["mute_background"] = bool(self.mute_var.get())
            self.settings["restore_layout"] = bool(self.restore_layout_var.get())
            self.settings["use_exit_reason"] = bool(self.exit_reason_var.get())
            self.settings["tile_monitor"] = int(self.tile_monitor_var.get())
            self.settings["ui_font_family"] = str(self.font_family_var.get())
            self.settings["ui_scale"] = max(0.75, min(2.0, float(self.ui_scale_var.get())))
            self.settings["screenshot_enabled"] = bool(self.screenshot_enabled_var.get())
            self.settings["screenshot_interval_minutes"] = max(
                1, int(self.screenshot_interval_var.get()))
            self.settings["refresh_interval_seconds"] = max(
                1.0, float(self.refresh_interval_var.get()))
        except (ValueError, tk.TclError, AttributeError):
            # a spinbox mid-edit can be empty or partially typed - ignore
            return
        # Writing to disk does a full flush+fsync, which is expensive enough
        # to make typing feel laggy when it runs on every keystroke (e.g. the
        # notify-target Entry). Coalesce a burst of changes into one write a
        # moment after the user stops - on_close() still flushes immediately
        # if they close the window before the delay is up.
        if self._settings_save_job:
            try:
                self.root.after_cancel(self._settings_save_job)
            except Exception:
                pass
        self._settings_save_job = self.root.after(400, self._flush_settings)
        if self.watcher_running:
            self._update_switch_labels()

    def _flush_settings(self):
        self._settings_save_job = None
        if self.closing:
            return
        save_settings(self.settings)

    def _on_fps_changed(self, *_args):
        self._on_setting_changed()
        cap = self.settings.get("fps_cap", "off")

        def worker():
            ok, msg = apply_fps_cap(None if cap in ("off", "0") else cap)
            self.log(("Frame rate: %s" % msg) if ok
                     else ("Couldn't set the frame rate cap: %s" % msg))
            handler, _cmd = detect_launch_handler()
            if ok and handler and handler != "Roblox (official)":
                self.log("  note: %s has its own FPS setting and may overwrite "
                         "this - set it there too, or leave this off." % handler)

        threading.Thread(target=worker, daemon=True).start()

    def _pick_accent_color(self):
        current = str(self.settings.get("ui_accent_color") or BLUE)
        _rgb, hex_color = colorchooser.askcolor(
            color=current, parent=self.root, title="Accent color")
        if not hex_color:
            return
        self.settings["ui_accent_color"] = hex_color
        self.accent_swatch.configure(bg=hex_color)
        save_settings(self.settings)
        self.log("Accent color set - restart to apply.")

    def _reset_accent_color(self):
        default = DEFAULT_SETTINGS["ui_accent_color"]
        self.settings["ui_accent_color"] = default
        self.accent_swatch.configure(bg=default)
        save_settings(self.settings)
        self.log("Accent color reset to default - restart to apply.")

    def restart_app(self):
        """Relaunches as a fresh process so appearance settings (read once,
        before any widget exists) actually take effect. Not a same-process
        Tk teardown/rebuild - recreating a Tk() root mid-process has real
        platform quirks around fonts/images left over from the old one."""
        if self.watcher_running and self.pid_labels:
            if not messagebox.askyesno(
                    "Restart MultiRoblox?",
                    "The watcher is on and %d client(s) launched from here are "
                    "still running.\n\nRestarting leaves them running, but "
                    "nothing will unlock or rejoin them while MultiRoblox is "
                    "restarting.\n\nRestart anyway?" % len(self.pid_labels)):
                return
        save_settings(self.settings)
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable] + sys.argv[1:])
            else:
                subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0])]
                                 + sys.argv[1:])
        except Exception as ex:
            self.log("Couldn't restart automatically (%s) - please close and "
                     "reopen MultiRoblox by hand." % ex)
            return
        self.closing = True
        self.watcher_stop.set()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _apply_low_end_preset(self):
        """One-click bundle of the settings that actually matter on a weak
        CPU, instead of having to know which six knobs to go find and tune
        individually. Writes self.settings directly rather than only
        setting the Tk variables - a BooleanVar's Checkbutton `command` only
        fires on an actual click, not on a programmatic .set(), so relying
        on that here would silently not persist half of these."""
        if not messagebox.askyesno(
                "Optimize for a low-end PC?",
                "This changes several settings at once:\n\n"
                "  - 1 core per instance\n"
                "  - Hard-cap each instance to 50% of one core\n"
                "  - Frame rate capped at 30\n"
                "  - Background clients run at below-normal priority\n"
                "  - Background clients muted\n"
                "  - A bit more delay between launches\n"
                "  - MultiRoblox's own refresh every 6 seconds instead of 3\n\n"
                "You can change any of these again afterward. Continue?"):
            return

        stagger_target = max(5.0, float(self.settings.get("launch_stagger", 3.0)))

        # Reflect the new values in the already-built Settings widgets first.
        # Some of these fire _on_setting_changed() immediately (anything
        # trace_add-bound), which re-derives EVERY setting from ALL its vars
        # each time - so a var not yet updated when an earlier one fires
        # gets re-read from its stale state in the meantime. Harmless: the
        # explicit write below is authoritative and runs after all of these,
        # but it's why stagger_target is a local computed once up front,
        # never read back out of self.settings while this is in progress.
        self.cores_var.set(1)
        self.cpu_cap_var.set(50)
        self.bg_priority_var.set(True)
        self.mute_var.set(True)
        self.spread_var.set(True)
        self.refresh_interval_var.set(6.0)
        self.stagger_var.set(stagger_target)
        self.fps_var.set("30")   # also re-triggers _on_fps_changed via its
                                 # trace, which writes Roblox's own FPS file

        # Authoritative final write - correct regardless of how the partial
        # syncs above landed in the meantime.
        self.settings["cores"] = 1
        self.settings["cpu_percent_limit"] = 50
        self.settings["fps_cap"] = "30"
        self.settings["background_priority"] = True
        self.settings["mute_background"] = True
        self.settings["spread_affinity"] = True
        self.settings["refresh_interval_seconds"] = 6.0
        self.settings["launch_stagger"] = stagger_target
        save_settings(self.settings)

        self.log("Applied the low-end PC preset. Cores/CPU-cap take effect on "
                 "each account's next launch; the rest applies immediately.")

    def _on_hotkeys_changed(self, *_args):
        want = bool(self.hotkeys_var.get())
        self.settings["global_hotkeys"] = want
        save_settings(self.settings)
        if want:
            self.start_hotkeys()
        else:
            self.stop_hotkeys()
            self.log("Global hotkeys off.")

    def _on_startup_changed(self, *_args):
        want = bool(self.startup_var.get())
        ok, msg = set_run_at_startup(want)
        self.settings["start_with_windows"] = want if ok else False
        save_settings(self.settings)
        self.log(("MultiRoblox %s." % msg) if ok
                 else ("Couldn't change the Windows startup entry: %s" % msg))

    def open_config_folder(self):
        path = config_dir()
        try:
            if IS_WINDOWS:
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
            self.log("Opened config folder: " + path)
        except Exception as ex:
            self.log("Couldn't open %s: %s" % (path, ex))

    # ---------------- tray ----------------
    def _tray_image(self):
        img = Image.new("RGB", (64, 64), "#18181b")
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((6, 20, 58, 44), radius=12, fill="#57c785")
        d.ellipse((38, 24, 54, 40), fill="white")
        return img

    def start_tray(self):
        """Optional: needs pystray + Pillow. Without them the option is simply
        unavailable rather than breaking anything."""
        if pystray is None or self._tray is not None:
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show MultiRoblox", lambda *_: self._tray_show(),
                                 default=True),
                pystray.MenuItem("Hide", lambda *_: self._tray_hide()),
                pystray.MenuItem("Quit", lambda *_: self._tray_quit()),
            )
            self._tray = pystray.Icon("MultiRoblox", self._tray_image(),
                                      "MultiRoblox %s" % APP_VERSION, menu)
            threading.Thread(target=self._tray.run, name="roblox-tray",
                             daemon=True).start()
            return True
        except Exception as ex:
            self.log("Tray icon unavailable: %s" % ex)
            self._tray = None
            return False

    def stop_tray(self):
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None

    def _tray_show(self):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

    def _tray_hide(self):
        self.root.after(0, self.root.withdraw)

    def _tray_quit(self):
        self.root.after(0, self.on_close)

    def _on_window_state(self, _event=None):
        """Hide to the tray instead of the taskbar when minimised."""
        if not self.settings.get("minimize_to_tray") or self.closing:
            return
        try:
            if self.root.state() == "iconic":
                if self.start_tray() or self._tray is not None:
                    self.root.withdraw()
        except Exception:
            pass

    def diagnose(self):
        """One-click report answering everything support-ish about this PC."""
        self.log("Running diagnostics...")

        def worker():
            lines = ["MultiRoblox %s diagnostics - %s"
                     % (APP_VERSION, time.strftime("%Y-%m-%d %H:%M:%S")),
                     "=" * 58,
                     "running from : %s" % python_description().replace("\n  ", " / "),
                     "windows      : %s   administrator: %s" % (IS_WINDOWS, is_admin()),
                     "config       : %s" % config_dir(),
                     ""]

            lines.append("dependencies")
            for name, obj in (("psutil", psutil), ("requests", requests),
                              ("cryptography", Fernet), ("pystray", pystray)):
                lines.append("  %-14s %s" % (
                    name, "ok" if obj is not None
                    else "MISSING - " + IMPORT_ERRORS.get(name, "unknown")))
            lines.append("")

            exe = find_roblox_exe()
            lines.append("roblox")
            lines.append("  client       : %s" % (exe or "NOT FOUND"))
            handler, cmd = detect_launch_handler()
            lines.append("  launches via : %s" % (handler or "unknown"))
            if cmd:
                lines.append("  handler cmd  : %s" % cmd)
            cfg = client_settings_path()
            lines.append("  fps cap      : %s (file %s)"
                         % (self.settings.get("fps_cap", "off"),
                            "present" if cfg and os.path.exists(cfg) else "absent"))
            clients = get_roblox_processes()
            lines.append("  running now  : %d client(s)" % len(clients))
            for p in clients[:8]:
                ok, why = can_open_process(p.pid)
                lines.append("    PID %-7d handle access: %s"
                             % (p.pid, "ok" if ok else why))
            lines.append("")

            lines.append("settings")
            for key in sorted(self.settings):
                value = self.settings[key]
                if key == "notify_target" and value:
                    value = "(set)"          # never print a webhook URL
                if key == "window_geometry":
                    continue
                lines.append("  %-22s %s" % (key, value))
            lines.append("")

            lines.append("profiles (%d)" % len(self.profiles))
            for prof in self.profiles:
                name = prof.get("name", "Unnamed")
                cookie = (prof.get("cookie") or "").strip()
                if cookie:
                    ok, msg = validate_cookie(cookie, self.log)
                    if ok:
                        try:
                            self._remember_account(prof)
                        except Exception:
                            pass
                    prof["_cookie_ok"] = ok
                else:
                    msg = "guest profile (no cookie)"
                lines.append("  %s" % name)
                lines.append("    cookie   : %s" % msg)
                age = self._cookie_age_text(prof)
                if age:
                    lines.append("    age      : %s" % age)
                if prof.get("user_name"):
                    lines.append("    account  : %s (id %s)"
                                 % (prof["user_name"], prof.get("user_id", "?")))
                lines.append("    game     : %s%s"
                             % (prof.get("place_id") or "none",
                                " (private server)" if prof.get("link_code") else ""))
                lines.append("    cores    : %s   rejoin: %s   guest fallback: %s"
                             % (prof.get("cores") or "global",
                                bool(prof.get("auto_rejoin")),
                                bool(prof.get("allow_guest_fallback"))))

            unknown = unknown_exits_path()
            if os.path.exists(unknown):
                try:
                    size = os.path.getsize(unknown)
                    lines.append("")
                    lines.append("unrecognised client exits captured: %s (%d bytes)"
                                 % (unknown, size))
                    lines.append("  send that file if auto-rejoin is guessing "
                                 "wrong - it holds the real log wording.")
                except Exception:
                    pass

            report = "\n".join(lines)
            path = os.path.join(config_dir(), "diagnostics.txt")
            try:
                atomic_write(path, report, binary=False)
            except Exception:
                path = None

            def finish():
                for line in report.splitlines():
                    self.log(line)
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(report)
                except Exception:
                    pass
                self.refresh_profile_list()
                messagebox.showinfo(
                    "Diagnostics",
                    "The report is in the activity log and on your clipboard."
                    + ("\n\nSaved to:\n%s" % path if path else "")
                    + "\n\nIt contains account names but no cookies, so it is "
                      "safe to share.")

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def send_test_alert(self):
        mode = self.settings.get("notify_mode", "off")
        target = self.settings.get("notify_target", "")
        if mode == "off" or not target:
            self.log("Set an alert type and a topic/webhook first.")
            return
        self.log("Sending a test alert via %s..." % mode)

        def worker():
            ok, detail = send_phone_alert(
                mode, target, "MultiRoblox test",
                "If this reached your phone, alerts are working.")
            self.log("Test alert %s (%s)." % ("sent" if ok else "FAILED", detail))

        threading.Thread(target=worker, daemon=True).start()

    def open_log_file(self):
        path = log_file_path()
        try:
            if not os.path.exists(path):
                append_log_file("(log created)")
            if IS_WINDOWS:
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            self.log("Couldn't open %s: %s" % (path, ex))

    def restart_elevated(self):
        if relaunch_as_admin():
            self.on_close()
        else:
            self.log("Elevation was cancelled or failed.")

    # ---------------- logging ----------------
    def log(self, msg):
        if self.closing:
            return
        append_log_file(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg))

        def _do():
            try:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", time.strftime("[%H:%M:%S] ") + str(msg) + "\n")
                # keep the widget from growing without bound in long sessions
                line_count = int(self.log_text.index("end-1c").split(".")[0])
                if line_count > MAX_LOG_LINES:
                    self.log_text.delete("1.0", "%d.0" % (line_count - MAX_LOG_LINES + 1))
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except Exception:
                pass

        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def copy_log(self):
        try:
            text = self.log_text.get("1.0", "end").strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_label.configure(text="Log copied to clipboard.")
            self._transient_until = time.time() + 4
        except Exception as ex:
            self.log("Couldn't copy the log: %s" % ex)

    # ---------------- watcher ----------------
    def on_toggle(self, checked):
        """Called by the switch widget itself."""
        self.set_watcher(checked, from_widget=True)

    def set_watcher(self, running, from_widget=False):
        running = bool(running)
        if running == self.watcher_running:
            if not from_widget:
                self.toggle.set_checked(running)
            return

        if running and psutil is None:
            self.log("Can't start the watcher: psutil is not installed "
                     "(pip install psutil).")
            self.toggle.set_checked(False)
            return

        self.watcher_running = running
        if not from_widget:
            self.toggle.set_checked(running)

        if running:
            self.watch_count = 0
            seeded = 0
            now = time.time()
            with self.pid_lock:
                for p in get_roblox_processes():
                    if p.pid not in self.handled:
                        self.handled[p.pid] = now
                        seeded += 1
            self.log("Watcher ON - %d existing instance(s) ignored; new Roblox windows "
                     "will be unlocked automatically." % seeded)
            self.watcher_stop.clear()
            self.watcher_gen += 1
            self.watcher_thread = threading.Thread(
                target=self._watcher_loop, args=(self.watcher_gen,),
                name="roblox-watcher", daemon=True)
            self.watcher_thread.start()
        else:
            self.watcher_gen += 1  # retires the running loop
            self.watcher_stop.set()
            self.watcher_thread = None
            self.log("Watcher OFF.")

        self._update_switch_labels()

    def _update_switch_labels(self):
        if self.watcher_running:
            self.switch_label.configure(text="Watcher: ON", fg=GREEN)
            hint = "every %.1fs" % float(self.settings["watch_interval"])
            if self.settings["watcher_one_shot"]:
                hint += " · one-shot"
            if self.watch_count:
                hint += " · %d handled" % self.watch_count
            self.switch_hint.configure(text=hint, fg=SUBTEXT)
        else:
            self.switch_label.configure(text="Watcher: OFF", fg=SUBTEXT)
            self.switch_hint.configure(text="auto-unlock new windows", fg=SUBTEXT)

    def _guarded(self, name, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            report_crash(name)
            self.log("%s failed: see the log file for details." % name)
            return None

    def _watcher_loop(self, generation):
        """Runs on a background thread so a slow process scan can never
        freeze the window. The generation check guarantees that a quick
        OFF-then-ON never leaves two watcher threads running."""
        while not self.watcher_stop.is_set() and generation == self.watcher_gen:
            try:
                self._watcher_scan()
            except Exception as ex:
                report_crash("the watcher")
                self.log("Watcher error: %s (details in the log file)" % ex)
            interval = float(self.settings.get("watch_interval", 2.0) or 2.0)
            self.watcher_stop.wait(max(0.5, interval))

    def _watcher_scan(self):
        now = time.time()
        alive = set()
        new_pids = []
        with self.pid_lock:
            for p in get_roblox_processes():
                alive.add(p.pid)
                if p.pid not in self.handled:
                    self.handled[p.pid] = now
                    new_pids.append(p.pid)
            # forget PIDs that have been gone for a while, so the set can't
            # grow forever in a long session (and PIDs can be reused)
            for pid in [k for k, seen in self.handled.items()
                        if k not in alive and now - seen > 120]:
                self.handled.pop(pid, None)
                self.unlocked_pids.discard(pid)
                self.attempted.discard(pid)

        # A client we launched has vanished - offer it to the rejoin logic
        # before its label is forgotten.
        with self.pid_lock:
            departed = [(pid, label, now - self.pid_started.get(pid, now))
                        for pid, label in self.pid_labels.items()
                        if pid not in alive]
            for pid, _label, _up in departed:
                self.pid_labels.pop(pid, None)
                self.pid_started.pop(pid, None)
        for pid, label, uptime in departed:
            self.drop_counts[label] = self.drop_counts.get(label, 0) + 1
            reason, worth_rejoining = (None, True)
            if self.settings.get("use_exit_reason", True):
                try:
                    reason, worth_rejoining = explain_exit()
                except Exception:
                    reason, worth_rejoining = (None, True)
            self.log("Client for \"%s\" (PID %d) has closed after %d minute(s) "
                     "(drop #%d)%s."
                     % (label, pid, int(uptime // 60), self.drop_counts[label],
                        " - " + reason if reason else ""))
            append_session(label, pid, now - uptime, now, reason or "closed")
            if self.settings.get("notify_on_drop"):
                self.notify("Roblox client closed",
                            "%s dropped after %d minute(s).%s"
                            % (label, int(uptime // 60),
                               " " + reason if reason else ""))
            if not worth_rejoining:
                self.log("  not rejoining \"%s\" - %s. Rejoining would not "
                         "help." % (label, reason))
                if self.settings.get("notify_on_giveup", True):
                    self.notify("Roblox: %s stopped" % label,
                                "Not rejoining - %s." % reason)
                continue
            self._consider_rejoin(label, uptime)

        for pid in new_pids:
            self.log("New Roblox window detected (PID %d)." % pid)
            threading.Thread(target=self._handle_new_instance, args=(pid, True),
                             daemon=True).start()

    def notify(self, title, message, sound=True):
        """Local ping plus a phone alert, both best-effort and off the UI thread."""
        if sound and self.settings.get("sound_on_drop", True):
            beep(ok=False)
        mode = self.settings.get("notify_mode", "off")
        target = self.settings.get("notify_target", "")
        if mode == "off" or not target:
            return

        def worker():
            ok, detail = send_phone_alert(mode, target, title, message)
            if not ok:
                self.log("Phone alert failed (%s): %s" % (mode, detail))

        threading.Thread(target=worker, daemon=True).start()

    def _consider_rejoin(self, label, uptime=0.0):
        """Relaunches a profile whose client closed, if that profile asked for
        it. This only ever re-runs the ordinary launch path - the same thing
        the Launch button does - so nothing is injected into the game."""
        if not self.watcher_running or self.closing or label == "guest":
            return
        profile = next((p for p in self.profiles
                        if p.get("name") == label and p.get("auto_rejoin")), None)
        if profile is None:
            return

        # The limit exists to stop a broken profile flapping, not to cap a
        # working one. A client that stayed up for a decent stretch counts as
        # a healthy session, so the budget starts over.
        reset_after = float(self.settings.get("rejoin_reset_after", 300.0))
        if uptime >= reset_after and self.rejoin_counts.get(label):
            self.rejoin_counts[label] = 0
            self.log("\"%s\" had run for %d minute(s), so its rejoin count is "
                     "back to zero." % (label, int(uptime // 60)))

        limit = int(self.settings.get("rejoin_max_attempts", 5))
        used = self.rejoin_counts.get(label, 0)
        if used >= limit:
            self.log("Not rejoining \"%s\" again - it closed %d times in quick "
                     "succession, so something is wrong. Fix it and launch by "
                     "hand to start over." % (label, used))
            if self.settings.get("notify_on_giveup", True):
                self.notify("Roblox: %s needs you" % label,
                            "It closed %d times in a row, so MultiRoblox has "
                            "stopped rejoining it." % used)
            return
        self.rejoin_counts[label] = used + 1

        cooldown = max(5.0, float(self.settings.get("rejoin_cooldown", 60.0)))
        self.log("Rejoining \"%s\" in %.0f seconds (attempt %d of %d)."
                 % (label, cooldown, used + 1, limit))

        def worker():
            # A stop during the wait cancels the rejoin.
            if self.watcher_stop.wait(cooldown):
                return
            if self.closing or not self.watcher_running:
                return
            if any(self.pid_labels.get(p) == label for p in list(self.pid_labels)):
                return  # it came back on its own
            self._launch_and_unlock(profile)

        threading.Thread(target=worker, name="roblox-rejoin", daemon=True).start()

    def _handle_new_instance(self, pid, from_watcher, force=False):
        # The watcher and the launch path can both spot the same new process,
        # whether at the same moment or one just after the other. Without this
        # guard the PID gets unlocked twice and, worse, given two different
        # core masks - the second silently overwriting the first.
        # Each PID is therefore attempted at most once automatically; only an
        # explicit "Unlock Selected" (force) may repeat it.
        with self.pid_lock:
            if not force and (pid in self.in_progress
                              or pid in self.unlocked_pids
                              or pid in self.attempted):
                return
            self.in_progress.add(pid)
            self.attempted.add(pid)
        try:
            self._handle_new_instance_inner(pid, from_watcher)
        finally:
            with self.pid_lock:
                self.in_progress.discard(pid)

    def _handle_new_instance_inner(self, pid, from_watcher):
        closed = unlock_with_retry(
            pid,
            self.settings["unlock_attempts"],
            self.settings["unlock_delay"],
            self.log,
            self.watcher_stop if from_watcher else None,
        )
        if closed:
            with self.pid_lock:
                self.unlocked_pids.add(pid)
            self.log("Unlocked PID %d - the next Roblox instance can now start." % pid)
        elif process_alive(pid):
            self.log("Could not find the singleton lock in PID %d. "
                     "Try more unlock attempts, or run as Administrator." % pid)

        # Read from self.settings, not from the Tk variables: this runs on a
        # worker thread and Tk objects must only be touched from the main one.
        # Skip a process that has already exited - Roblox's launcher shim
        # starts, hands off and quits, which produced a confusing
        # "process PID not found" error.
        if self.settings["auto_apply_cores"]:
            if process_alive(pid):
                cores = self.settings["cores"]
                label = self.pid_labels.get(pid)
                if label:
                    owner = next((p for p in self.profiles
                                  if p.get("name") == label), None)
                    if owner and int(owner.get("cores") or 0) > 0:
                        cores = int(owner["cores"])
                self._apply_core_limit(pid, cores)
            else:
                self.log("PID %d exited before a core limit could be applied "
                         "(this is normal for Roblox's launcher process)." % pid)

        if from_watcher:
            self.watch_count += 1
            if self.settings["watcher_one_shot"]:
                self.root.after(0, self._one_shot_off)
            else:
                self.root.after(0, self._update_switch_labels)

        self.root.after(0, self.refresh_instances)

    def _one_shot_off(self):
        if not self.watcher_running:
            return
        self.set_watcher(False)
        self.log("One-shot mode: watcher switched itself off after handling "
                 "the new instance.")

    # ---------------- instances ----------------
    def _schedule_refresh(self):
        """Light periodic refresh of the instance list, independent of the
        watcher, so the table stays current."""
        if self.closing:
            return
        interval_ms = max(1.0, float(
            self.settings.get("refresh_interval_seconds", 3.0))) * 1000
        self._refresh_job = self.root.after(int(interval_ms), self._periodic_refresh)

    def _periodic_refresh(self):
        # One process/foreground-window snapshot, shared by every step below,
        # instead of each step scanning the whole system process table on its
        # own - that was three full scans a tick for one round of updates.
        procs = get_roblox_processes()
        front = foreground_pid()

        # Each step is isolated: one failing feature must not stop the others,
        # and none of them may stop the refresh loop rescheduling itself.
        for name, step in (("instance list", lambda: self.refresh_instances(procs)),
                           ("background priority",
                            lambda: self._apply_background_priority(procs, front)),
                           ("audio focus",
                            lambda: self._apply_audio_focus(procs, front)),
                           ("frame-rate cap", lambda: self._reassert_fps_cap(procs)),
                           ("status summary", self._update_summary)):
            try:
                step()
            except Exception:
                report_crash(name)
                if name not in self._reported_failures:
                    self._reported_failures.add(name)
                    self.log("The %s stopped working - details are in the log "
                             "file. Everything else carries on." % name)
                # Two failures in a row means it is broken on this PC, not
                # unlucky. Turn it off rather than throwing every few seconds.
                self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
                if self._failure_counts[name] >= 2:
                    setting = {"background priority": "background_priority",
                               "audio focus": "mute_background"}.get(name)
                    if setting and self.settings.get(setting):
                        self.settings[setting] = False
                        save_settings(self.settings)
                        self.log("Turned '%s' off - it keeps failing on this PC. "
                                 "You can switch it back on in Settings." % name)
        self._schedule_refresh()

    def _schedule_screenshots(self):
        if self.closing:
            return
        interval_ms = max(1, int(self.settings.get(
            "screenshot_interval_minutes", 10))) * 60000
        self._screenshot_job = self.root.after(
            interval_ms, self._take_periodic_screenshots)

    def _take_periodic_screenshots(self):
        # Reschedule first, unconditionally: a failure below must not stop
        # future attempts, and the interval may have changed since this tick
        # was set up.
        self._schedule_screenshots()
        if not self.settings.get("screenshot_enabled"):
            return
        if (self.settings.get("notify_mode") != "discord"
                or not (self.settings.get("notify_target") or "").strip()):
            return  # the Settings hint next to this already explains why

        windows = get_window_map()
        targets = [(p.pid, windows[p.pid][0], windows[p.pid][1])
                   for p in get_roblox_processes() if p.pid in windows]
        if not targets:
            return
        webhook = self.settings.get("notify_target")
        pid_labels = dict(self.pid_labels)

        def worker():
            images = []
            for pid, hwnd, title in targets:
                label = pid_labels.get(pid) or title or ("PID %d" % pid)
                png = capture_window_png(hwnd)
                if png:
                    safe_name = re.sub(r"[^\w\-]+", "_", label)[:60] or "roblox"
                    images.append(("%s.png" % safe_name, png, label))
            if not images:
                self.log("Periodic screenshot: couldn't capture any window "
                         "this time (all minimized/unavailable?).")
                return
            ok, detail = send_discord_screenshots(webhook, images)
            if not ok:
                self.log("Periodic screenshot webhook failed: %s" % detail)

        threading.Thread(target=worker, name="roblox-screenshot",
                         daemon=True).start()

    def _apply_background_priority(self, procs=None, front=None):
        """Everything except the client you are actually looking at runs at
        below-normal priority. Windows then favours the window in front, which
        helps far more than core pinning when several clients are open."""
        if psutil is None or not self.settings.get("background_priority"):
            return
        low = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", None)
        normal = getattr(psutil, "NORMAL_PRIORITY_CLASS", None)
        if low is None or normal is None:
            return
        if front is None:
            front = foreground_pid()
        for p in (get_roblox_processes() if procs is None else procs):
            want = normal if p.pid == front else low
            if self._priority_state.get(p.pid) == want:
                continue
            try:
                p.nice(want)
                self._priority_state[p.pid] = want
            except Exception:
                self._priority_state[p.pid] = want   # don't retry every tick

    def _apply_audio_focus(self, procs=None, front=None):
        """Only the client you are looking at makes noise."""
        if AudioUtilities is None or not self.settings.get("mute_background"):
            return
        pids = {p.pid for p in (get_roblox_processes() if procs is None else procs)}
        if not pids:
            return
        if front is None:
            front = foreground_pid()
        keep = {front} if front in pids else set()
        try:
            set_session_mute(pids - keep, keep)
        except Exception:
            pass

    def _reassert_fps_cap(self, procs=None):
        """Self-heals the frame-rate cap if something has undone it mid-
        session - Roblox recreating the version folder on a self-update, a
        bootstrapper writing its own ClientAppSettings.json, or a stray edit.
        _ensure_fps_cap() already reapplies it before every launch; this
        catches drift for clients that are already running.

        Rate-limited to a read-only check every 20s, and only bothers when
        the file has actually drifted, so this does not add disk I/O to
        every 3-second tick."""
        cap = self.settings.get("fps_cap", "off")
        if cap in ("off", "0", "", None):
            return
        now = time.time()
        if now - self._last_fps_check < 20:
            return
        self._last_fps_check = now
        if not (get_roblox_processes() if procs is None else procs):
            return  # nothing running - nothing to protect right now
        if fps_cap_matches(cap):
            return
        ok, msg = apply_fps_cap(cap)
        if ok:
            self.log("Frame-rate cap had drifted - reapplied: %s" % msg)

    def _unmute_all(self):
        if AudioUtilities is None:
            return
        try:
            set_session_mute(set(), {p.pid for p in get_roblox_processes()})
        except Exception:
            pass

    def _restore_priorities(self):
        if psutil is None or not self._priority_state:
            return
        normal = getattr(psutil, "NORMAL_PRIORITY_CLASS", None)
        if normal is None:
            return
        for pid in list(self._priority_state):
            try:
                psutil.Process(pid).nice(normal)
            except Exception:
                pass
        self._priority_state.clear()

    def refresh_instances(self, procs=None):
        if self.closing:
            return
        windows = get_window_map()
        seen = set()
        total_cores = os.cpu_count() or 1

        for p in (get_roblox_processes() if procs is None else procs):
            pid = p.pid
            seen.add(pid)
            title = "(no window yet)"
            if pid in windows:
                title = windows[pid][1]
            cores = "unlimited"
            mem = "-"
            cpu = "-"
            try:
                aff = p.cpu_affinity()
                if aff and len(aff) < total_cores:
                    cores = "%d (%s)" % (len(aff), ",".join(str(c) for c in sorted(aff)[:4]))
            except Exception:
                pass
            try:
                mem = "%d MB" % (p.memory_info().rss // (1024 * 1024))
            except Exception:
                pass
            try:
                proc = self._proc_cache.get(pid)
                if proc is None or proc.pid != pid:
                    proc = p
                    self._proc_cache[pid] = proc
                    proc.cpu_percent(None)  # prime the counter
                    cpu = "-"
                else:
                    cpu = "%.0f%%" % proc.cpu_percent(None)
            except Exception:
                pass

            status = "Unlocked" if pid in self.unlocked_pids else "Running"
            account = self.pid_labels.get(pid, "-")

            started = self.pid_started.get(pid)
            if started is None:
                try:
                    started = p.create_time()
                except Exception:
                    started = None
            up = "-"
            if started:
                mins = int(max(0, time.time() - started) // 60)
                up = "%dh %02dm" % (mins // 60, mins % 60) if mins >= 60 else "%dm" % mins

            drops = self.drop_counts.get(account, 0) if account != "-" else 0
            values = (pid, account, title, up, drops or "", cores, mem, cpu, status)
            iid = str(pid)
            if self.tree.exists(iid):
                self.tree.item(iid, values=values)
            else:
                self.tree.insert("", "end", iid=iid, values=values)

        for iid in self.tree.get_children():
            if int(iid) not in seen:
                self.tree.delete(iid)
                self._proc_cache.pop(int(iid), None)

        self._window_cache = windows

        if psutil is None:
            self.status_label.configure(
                text="psutil not installed - the instance list can't be shown.")

    def _selected_pid(self):
        sel = self.tree.selection()
        if not sel:
            self.log("Select an instance in the list first.")
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def apply_limit_selected(self):
        pid = self._selected_pid()
        if pid is None:
            return
        self._apply_core_limit(pid, self.cores_var.get())
        self.refresh_instances()

    def unlock_selected(self):
        pid = self._selected_pid()
        if pid is None:
            return
        self.log("Unlocking PID %d on request..." % pid)
        threading.Thread(target=self._handle_new_instance, args=(pid, False),
                         kwargs={"force": True}, daemon=True).start()

    def focus_selected(self):
        pid = self._selected_pid()
        if pid is None:
            return
        entry = self._window_cache.get(pid)
        if not entry:
            self.log("PID %d has no visible window yet." % pid)
            return
        bring_window_to_front(entry[0])

    def start_hotkeys(self):
        if not self.settings.get("global_hotkeys") or self._hotkeys is not None:
            return
        self._hotkeys = HotkeyListener(self._on_hotkey, 9, self.log)
        self._hotkeys.start()
        self.root.after(600, self._report_hotkeys)

    def _report_hotkeys(self):
        if self._hotkeys and self._hotkeys.registered:
            self.log("Global hotkeys on: Ctrl+Alt+1..%d jump to a client."
                     % self._hotkeys.registered)

    def stop_hotkeys(self):
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
            self._hotkeys = None

    def _on_hotkey(self, index):
        """Ctrl+Alt+N focuses the Nth client, ordered as the table shows them."""
        def do():
            rows = self.tree.get_children()
            if 1 <= index <= len(rows):
                pid = int(rows[index - 1])
                entry = self._window_cache.get(pid)
                if entry:
                    bring_window_to_front(entry[0])
                else:
                    self.log("PID %d has no visible window yet." % pid)
        self.root.after(0, do)

    # ---------------- window layout ----------------
    def save_layout(self):
        """Remembers where each account's window currently sits."""
        windows = get_window_map()
        saved = 0
        for pid, label in list(self.pid_labels.items()):
            entry = windows.get(pid)
            if not entry:
                continue
            rect = window_rect(entry[0])
            if rect:
                self.layouts[label] = rect
                saved += 1
        if saved:
            save_layouts(self.layouts)
            self.log("Saved window positions for %d account(s)." % saved)
        else:
            self.log("No positioned client windows to save yet - launch some "
                     "first, drag them where you want them, then save.")

    def restore_layout(self):
        windows = get_window_map()
        moved = 0
        for pid, label in list(self.pid_labels.items()):
            rect = self.layouts.get(label)
            entry = windows.get(pid)
            if rect and entry and place_window(entry[0], rect):
                moved += 1
        self.log("Restored %d window position(s)." % moved
                 if moved else "No saved positions matched the open clients.")

    def _restore_one_layout(self, pid, label):
        rect = self.layouts.get(label)
        if not rect or not self.settings.get("restore_layout", True):
            return
        for _ in range(10):          # the window takes a moment to appear
            time.sleep(1.0)
            entry = get_window_map().get(pid)
            if entry and place_window(entry[0], rect):
                self.log("Put \"%s\" back where you left it." % label)
                return

    def tile_clients(self, layout="grid"):
        windows = get_window_map()
        monitors = list_monitors()
        by_monitor = {}
        for p in get_roblox_processes():
            entry = windows.get(p.pid)
            if not entry:
                continue
            label = self.pid_labels.get(p.pid)
            wanted = 0
            if label:
                owner = next((x for x in self.profiles
                              if x.get("name") == label), None)
                if owner:
                    wanted = int(owner.get("monitor") or 0)
            if not wanted:
                wanted = int(self.settings.get("tile_monitor", 0) or 0)
            index = min(max(0, wanted - 1 if wanted else 0), len(monitors) - 1)
            by_monitor.setdefault(index, []).append(entry[0])

        if not by_monitor:
            self.log("No Roblox windows to arrange yet.")
            return
        moved = 0
        for index, handles in by_monitor.items():
            moved += tile_windows(handles, layout, monitor=monitors[index])
        where = ("across %d monitor(s)" % len(by_monitor)
                 if len(by_monitor) > 1 else "")
        self.log("Arranged %d window(s) as %s %s." % (moved, layout, where))

    def _close_pids(self, pids, what):
        """Closes clients the way clicking their X would. Only ever runs from
        an explicit button press, and never touches a client the user did not
        choose."""
        if not pids:
            return
        try:
            if not messagebox.askyesno(
                    "Close Roblox?",
                    "Close %s?\n\nThis shuts the Roblox window(s) down. Anything "
                    "unsaved in-game is lost." % what):
                return
        except Exception:
            return

        windows = get_window_map()
        closed = 0
        for pid in pids:
            # Forget the label first so auto-rejoin does not treat a
            # deliberate close as a crash and bring it straight back.
            with self.pid_lock:
                self.pid_labels.pop(pid, None)
                self.pid_started.pop(pid, None)
            entry = windows.get(pid)
            if entry and close_window(entry[0]):
                closed += 1
            elif psutil is not None:
                try:
                    psutil.Process(pid).terminate()
                    closed += 1
                except Exception:
                    pass
        self.log("Asked %d client(s) to close." % closed)
        self.root.after(1500, self.refresh_instances)

    def close_selected(self):
        pid = self._selected_pid()
        if pid is None:
            return
        label = self.pid_labels.get(pid)
        self._close_pids([pid], 'the client for "%s" (PID %d)' % (label, pid)
                         if label else "PID %d" % pid)

    def close_all_clients(self):
        pids = [p.pid for p in get_roblox_processes()]
        if not pids:
            self.log("No Roblox clients are running.")
            return
        self._close_pids(pids, "all %d running Roblox client(s)" % len(pids))

    def _smt_ratio(self):
        """Logical processors per physical core (1 if unknown or no SMT).

        os.cpu_count() and the affinity mask both count LOGICAL processors,
        so two hyperthread siblings look like 'different cores' but actually
        share one physical core's real execution resources. Spreading across
        logical IDs alone can quietly put two instances on the same physical
        core anyway - this lets _next_affinity spread across physical cores
        instead. Windows numbers siblings contiguously by convention; there
        is no portable way to ask for the real topology without extra native
        calls, so this is the same assumption other spreading tools make."""
        if psutil is None:
            return 1
        try:
            physical = psutil.cpu_count(logical=False)
            logical = psutil.cpu_count(logical=True)
            if physical and logical and physical > 0:
                return max(1, logical // physical)
        except Exception:
            pass
        return 1

    def _next_affinity(self, cores):
        """Picks which cores this instance gets. With spreading on, each new
        instance starts on a different PHYSICAL core so two clients don't
        fight over the same one - not just a different logical ID, which
        could still be a hyperthread sibling of a core already in use."""
        total = os.cpu_count() or 1
        cores = max(1, min(int(cores), total))
        if not self.settings["spread_affinity"]:
            return list(range(cores))
        ratio = self._smt_ratio()
        start = self._affinity_cursor % total
        # Round the step up to a whole physical core so the cursor stays
        # aligned to physical-core boundaries - otherwise requesting an odd
        # number of logical cores could leave the next instance starting
        # mid-core, right back on a sibling of one already claimed.
        step = ((cores + ratio - 1) // ratio) * ratio if ratio > 1 else cores
        self._affinity_cursor = (start + step) % total
        return sorted({(start + i) % total for i in range(cores)})

    def _apply_core_limit(self, pid, cores):
        if psutil is None:
            self.log("psutil not installed - can't set CPU affinity.")
            return
        try:
            mask = self._next_affinity(cores)
            proc = psutil.Process(pid)
            proc.cpu_affinity(mask)
            self.log("Limited PID %d to %d core(s): %s"
                     % (pid, len(mask), ",".join(str(c) for c in mask)))
        except Exception as ex:
            self.log("Could not set CPU affinity for PID %d: %s" % (pid, ex))

        # Affinity only says WHICH cores are allowed - it does not stop the
        # client fully saturating them. The hard cap below is independent of
        # it and only runs when the user has actually turned it on.
        percent = int(self.settings.get("cpu_percent_limit", 0) or 0)
        if percent > 0:
            if apply_cpu_rate_cap(pid, percent, self.log):
                self.log("Hard-capped PID %d to %d%% of one core."
                         % (pid, percent))

    # ---------------- profiles ----------------
    def refresh_profile_list(self):
        query = ""
        if hasattr(self, "profile_filter_var"):
            query = self.profile_filter_var.get().strip().lower()

        self.profile_listbox.delete(0, tk.END)
        self._profile_index_map = []
        for real_idx, p in enumerate(self.profiles):
            state = p.get("_cookie_ok")           # None = unknown / not checked
            if not p.get("cookie"):
                suffix, colour = "  ·  guest", SUBTEXT
            elif state is True:
                suffix, colour = "  ·  cookie OK", GREEN
            elif state is False:
                suffix, colour = "  ·  COOKIE EXPIRED - re-copy it", RED
            else:
                suffix, colour = "  ·  cookie saved", TEXT
            if p.get("place_id"):
                game = self.game_label(p["place_id"]) or ("place %s" % p["place_id"])
                suffix += "  ·  " + game
                if p.get("link_code"):
                    suffix += " (private)"
                elif p.get("job_id"):
                    suffix += " (one server)"
            if int(p.get("cores") or 0) > 0:
                suffix += "  ·  %d core%s" % (p["cores"],
                                              "" if p["cores"] == 1 else "s")
            if p.get("auto_rejoin"):
                suffix += "  ·  auto-rejoin"
            line = p.get("name", "Unnamed") + suffix
            if query and query not in line.lower():
                continue
            self.profile_listbox.insert(tk.END, line)
            self._profile_index_map.append(real_idx)
            try:
                self.profile_listbox.itemconfig(self.profile_listbox.size() - 1,
                                                foreground=colour)
            except Exception:
                pass

    def _selected_profile_indices(self):
        """The current listbox selection, translated from (possibly
        filtered) row positions into real indices into self.profiles."""
        sel = self.profile_listbox.curselection()
        return [self._profile_index_map[i] for i in sel
                if i < len(self._profile_index_map)]

    def _reselect_profile(self, real_idx):
        """Re-selects a profile by its real index after a refresh, if it's
        still visible under the current filter - a no-op otherwise (e.g.
        the edit changed its name so it no longer matches)."""
        try:
            row = self._profile_index_map.index(real_idx)
        except ValueError:
            return
        self.profile_listbox.selection_clear(0, tk.END)
        self.profile_listbox.selection_set(row)
        self.profile_listbox.activate(row)

    # ---------------- game name / icon ----------------
    def game_label(self, place_id):
        entry = self.game_names.get(str(place_id))
        return entry if isinstance(entry, str) else None

    def ensure_game_info(self, place_id, refresh_list=True):
        """Fetches a game's name and icon once and caches both on disk."""
        place_id = str(place_id or "").strip()
        if not place_id or place_id in self._game_lookups:
            return
        if self.game_label(place_id) and os.path.exists(icon_cache_path(place_id)):
            return
        self._game_lookups.add(place_id)

        def worker():
            name, icon = fetch_game_info(place_id)
            if name:
                self.game_names[place_id] = name
                save_game_cache(self.game_names)
            if icon:
                try:
                    atomic_write(icon_cache_path(place_id), icon)
                except Exception:
                    pass
            self._game_lookups.discard(place_id)
            if name or icon:
                def done():
                    if refresh_list:
                        self.refresh_profile_list()
                    self.update_game_preview()
                self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _photo_for(self, place_id):
        """Tk 8.6 reads PNG straight from base64, so no image library needed."""
        place_id = str(place_id)
        if place_id in self.game_icons:
            return self.game_icons[place_id]
        path = icon_cache_path(place_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            photo = tk.PhotoImage(data=data)
            self.game_icons[place_id] = photo
            return photo
        except Exception:
            return None

    def _avatar_photo(self, user_id):
        key = "user_%s" % user_id
        if key in self.game_icons:
            return self.game_icons[key]
        path = avatar_cache_path(user_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            photo = tk.PhotoImage(data=data)
            self.game_icons[key] = photo
            return photo
        except Exception:
            return None

    def _cookie_age_text(self, profile):
        saved = profile.get("cookie_saved")
        if not saved:
            return None
        days = int(max(0, time.time() - float(saved)) // 86400)
        if days < 1:
            return "cookie saved today"
        note = "cookie saved %d day%s ago" % (days, "" if days == 1 else "s")
        if days >= 30:
            note += " - worth refreshing"
        return note

    def update_game_preview(self):
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.game_icon_label.configure(image="")
            self.avatar_label.configure(image="", width=6, height=3)
            self.account_label.configure(text="")
            self.account_detail_label.configure(text="")
            self.game_name_label.configure(text="Select a profile to see its game")
            self.game_detail_label.configure(text="")
            return
        profile = self.profiles[real_indices[0]]

        # --- account block ---
        user_name = profile.get("user_name")
        user_id = profile.get("user_id")
        self.account_label.configure(
            text=user_name or profile.get("name", "Unnamed"))
        details = []
        if user_id:
            details.append("id %s" % user_id)
        age = self._cookie_age_text(profile)
        if age:
            details.append(age)
        if profile.get("_cookie_ok") is False:
            details.append("cookie rejected")
        self.account_detail_label.configure(
            text="\n".join(details) or "not checked yet",
            fg=RED if profile.get("_cookie_ok") is False else SUBTEXT)
        avatar = self._avatar_photo(user_id) if user_id else None
        if avatar is not None:
            self.avatar_label.configure(image=avatar, width=0, height=0)
            self._avatar_ref = avatar
        else:
            self.avatar_label.configure(image="", width=6, height=3)
        place_id = (profile.get("place_id") or "").strip()

        if not place_id:
            self.game_icon_label.configure(image="")
            self.game_name_label.configure(text="No game set")
            self.game_detail_label.configure(
                text="This profile opens the Roblox app home page.\n"
                     "Edit it and paste a game or private server link to join one.")
            return

        name = self.game_label(place_id)
        self.game_name_label.configure(text=name or "Looking up game %s..." % place_id)
        bits = ["Place ID %s" % place_id]
        if profile.get("link_code"):
            bits.append("private server")
        elif profile.get("job_id"):
            bits.append("specific server %s..." % profile["job_id"][:8])
        self.game_detail_label.configure(text="  ·  ".join(bits))

        photo = self._photo_for(place_id)
        if photo is not None:
            self.game_icon_label.configure(image=photo, width=0, height=0)
            self._icon_ref = photo          # keep a reference or Tk drops it
        else:
            self.game_icon_label.configure(image="", width=12, height=6)
        self.ensure_game_info(place_id)

    # ---------------- context menus & shortcuts ----------------
    def _build_menus(self):
        self.profile_menu = tk.Menu(self.root, tearoff=0, bg=CONTROL, fg=TEXT,
                                    activebackground=BLUE, activeforeground="white",
                                    bd=0)
        self.profile_menu.add_command(label="Launch",
                                      command=self.launch_selected_profiles)
        self.profile_menu.add_separator()
        self.profile_menu.add_command(label="Edit...", command=self.edit_profile)
        self.profile_menu.add_command(label="Duplicate",
                                      command=self.duplicate_profile)
        self.profile_menu.add_command(label="Test Cookie", command=self.test_cookie)
        self.profile_menu.add_command(label="Open Game Page",
                                      command=self.open_game_page)
        self.profile_menu.add_separator()
        self.profile_menu.add_command(label="Remove", command=self.remove_profile)

        self.instance_menu = tk.Menu(self.root, tearoff=0, bg=CONTROL, fg=TEXT,
                                     activebackground=BLUE,
                                     activeforeground="white", bd=0)
        self.instance_menu.add_command(label="Bring to Front",
                                       command=self.focus_selected)
        self.instance_menu.add_command(label="Unlock", command=self.unlock_selected)
        self.instance_menu.add_command(label="Apply Core Limit",
                                       command=self.apply_limit_selected)
        self.instance_menu.add_separator()
        self.instance_menu.add_command(label="Tile Windows",
                                       command=lambda: self.tile_clients("grid"))
        self.instance_menu.add_command(label="Close This Client",
                                       command=self.close_selected)

    def _popup_profile_menu(self, event):
        try:
            index = self.profile_listbox.nearest(event.y)
            if index >= 0 and not self.profile_listbox.selection_includes(index):
                self.profile_listbox.selection_clear(0, tk.END)
                self.profile_listbox.selection_set(index)
                self.profile_listbox.activate(index)
                self.update_game_preview()
            self.profile_menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass
        finally:
            try:
                self.profile_menu.grab_release()
            except Exception:
                pass

    def _popup_instance_menu(self, event):
        try:
            iid = self.tree.identify_row(event.y)
            if iid:
                self.tree.selection_set(iid)
            self.instance_menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass
        finally:
            try:
                self.instance_menu.grab_release()
            except Exception:
                pass

    def _bind_shortcuts(self):
        self.root.bind("<F5>", lambda e: self.refresh_instances())
        self.root.bind("<Control-n>", lambda e: self.add_profile())
        self.root.bind("<Control-N>", lambda e: self.add_profile())
        self.root.bind("<Control-w>", lambda e: self.set_watcher(
            not self.watcher_running))
        self.root.bind("<Control-W>", lambda e: self.set_watcher(
            not self.watcher_running))
        self.profile_listbox.bind("<Return>",
                                  lambda e: self.launch_selected_profiles())

    def duplicate_profile(self):
        if not self.storage_enabled:
            return
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.log("Select a profile to duplicate first.")
            return
        real_idx = real_indices[0]
        source = dict(self.profiles[real_idx])
        source.pop("_cookie_ok", None)
        base = source.get("name", "Unnamed")
        names = {p.get("name") for p in self.profiles}
        n = 2
        while "%s (%d)" % (base, n) in names:
            n += 1
        source["name"] = "%s (%d)" % (base, n)
        self.profiles.insert(real_idx + 1, source)
        if self._persist_profiles():
            self.refresh_profile_list()
            self._reselect_profile(real_idx + 1)
            self.log("Duplicated \"%s\" as \"%s\" - edit it to set the new "
                     "account's cookie." % (base, source["name"]))

    def open_game_page(self):
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.log("Select a profile first.")
            return
        place_id = (self.profiles[real_indices[0]].get("place_id") or "").strip()
        if not place_id:
            self.log("That profile has no game set.")
            return
        try:
            import webbrowser
            webbrowser.open("https://www.roblox.com/games/%s" % place_id)
        except Exception as ex:
            self.log("Couldn't open the game page: %s" % ex)

    def _remember_account(self, profile):
        """Stores who a cookie belongs to and caches their avatar, so a profile
        shows a real face and username rather than only the label you typed."""
        user_id, user_name = getattr(validate_cookie, "last_user", (None, None))
        if not user_id:
            return
        profile["user_id"] = str(user_id)
        if user_name:
            profile["user_name"] = user_name
        path = avatar_cache_path(user_id)
        if not os.path.exists(path):
            png = fetch_avatar(user_id)
            if png:
                try:
                    atomic_write(path, png)
                except Exception:
                    pass
        try:
            if self.storage_enabled:
                save_profiles(self.profiles, self.fernet)
        except Exception:
            pass

    def check_all_cookies(self, announce_good=True):
        """Tests every saved cookie against Roblox in the background and
        colours the list, so a dead cookie is obvious before a launch fails."""
        chosen = [p for p in self.profiles if (p.get("cookie") or "").strip()]
        if not chosen:
            return
        if requests is None:
            self.log("Can't check cookies: requests is not installed.")
            return

        def worker():
            bad = 0
            for p in chosen:
                try:
                    ok, msg = validate_cookie(p.get("cookie", ""))
                except Exception as ex:
                    ok, msg = False, "check failed: %s" % ex
                p["_cookie_ok"] = ok
                if ok:
                    try:
                        self._remember_account(p)
                    except Exception:
                        pass
                if not ok:
                    bad += 1
                    self.log('"%s": %s' % (p.get("name", "Unnamed"), msg))
                elif announce_good:
                    self.log('"%s": %s' % (p.get("name", "Unnamed"), msg))
            if bad:
                self.log("%d saved cookie(s) need re-copying - they are marked "
                         "in red in the list." % bad)
            self.root.after(0, self.refresh_profile_list)

        threading.Thread(target=worker, daemon=True).start()

    def _persist_profiles(self):
        if not self.storage_enabled:
            return False
        try:
            save_profiles(self.profiles, self.fernet)
            return True
        except Exception as ex:
            self.log("Could not save profiles: %s" % ex)
            messagebox.showerror("Save failed", "Could not save your profiles:\n%s" % ex)
            return False

    def add_profile(self):
        if not self.storage_enabled:
            return
        dlg = ProfileDialog(self.root)
        self.root.wait_window(dlg)
        if dlg.result:
            if dlg.result.get("cookie"):
                dlg.result["cookie_saved"] = time.time()
            self.profiles.append(dlg.result)
            if self._persist_profiles():
                self.refresh_profile_list()
                self.log("Saved profile: " + dlg.result["name"])

    def edit_profile(self):
        if not self.storage_enabled:
            return
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.log("Select a profile to edit first.")
            return
        idx = real_indices[0]
        existing = self.profiles[idx]
        dlg = ProfileDialog(self.root, existing.get("name", ""),
                            existing.get("cookie", ""), existing.get("place_id", ""),
                            existing.get("link_code", ""),
                            existing.get("auto_rejoin", False),
                            existing.get("cores", 0),
                            existing.get("allow_guest_fallback", False),
                            existing.get("monitor", 0),
                            existing.get("job_id", ""))
        self.root.wait_window(dlg)
        if dlg.result:
            dlg.result["_cookie_ok"] = None
            if dlg.result.get("cookie") == existing.get("cookie"):
                # unchanged cookie keeps its original date and known account
                for keep in ("cookie_saved", "user_id", "user_name"):
                    if existing.get(keep):
                        dlg.result[keep] = existing[keep]
                dlg.result["_cookie_ok"] = existing.get("_cookie_ok")
            elif dlg.result.get("cookie"):
                dlg.result["cookie_saved"] = time.time()
            self.profiles[idx] = dlg.result
            if self._persist_profiles():
                self.refresh_profile_list()
                self._reselect_profile(idx)
                self.log("Updated profile: " + dlg.result["name"])

    def remove_profile(self):
        if not self.storage_enabled:
            return
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.log("Select one or more profiles to remove first.")
            return
        names = [self.profiles[i].get("name", "Unnamed") for i in real_indices]
        prompt = ('Remove profile "%s"?' % names[0] if len(names) == 1
                  else "Remove %d profiles?\n\n%s" % (len(names), ", ".join(names)))
        if not messagebox.askyesno("Confirm", prompt):
            return
        for idx in sorted(real_indices, reverse=True):
            del self.profiles[idx]
        if self._persist_profiles():
            self.refresh_profile_list()
            self.log("Removed profile(s): " + ", ".join(names))

    def move_profile(self, delta):
        if not self.storage_enabled:
            return
        if self.profile_filter_var.get().strip():
            self.log("Clear the filter box first - reordering while "
                     "filtered would be confusing (up/down works on the "
                     "full list, not just what's visible).")
            return
        sel = self.profile_listbox.curselection()
        if len(sel) != 1:
            self.log("Select exactly one profile to move.")
            return
        idx = sel[0]
        new_idx = idx + delta
        if not (0 <= new_idx < len(self.profiles)):
            return
        self.profiles[idx], self.profiles[new_idx] = self.profiles[new_idx], self.profiles[idx]
        if self._persist_profiles():
            self.refresh_profile_list()
            self.profile_listbox.selection_set(new_idx)
            self.profile_listbox.activate(new_idx)

    def test_cookie(self):
        """Checks the saved cookies against Roblox without launching anything."""
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.log("Select one or more profiles to test first.")
            return
        chosen = [self.profiles[i] for i in real_indices]

        def worker():
            for p in chosen:
                name = p.get("name", "Unnamed")
                cookie = (p.get("cookie") or "").strip()
                ok, msg = validate_cookie(cookie)
                p["_cookie_ok"] = ok if cookie else None
                if ok:
                    self._remember_account(p)
                self.log('"%s": %s  [%d characters saved]' % (name, msg, len(cookie)))
                hint = cookie_warning(cookie)
                if hint:
                    self.log("  " + hint)
                if not ok and (p.get("cookie") or "").strip():
                    self.log("  -> re-copy .ROBLOSECURITY from your browser "
                             "and Edit this profile.")

        threading.Thread(target=worker, daemon=True).start()

    def export_profiles_dialog(self):
        if not self.storage_enabled or not self.profiles:
            self.log("There are no profiles to export.")
            return
        dlg = CreatePasswordDialog(self.root, title="Password for this backup")
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        try:
            path = filedialog.asksaveasfilename(
                parent=self.root, title="Save profile backup",
                defaultextension=".mrprofiles",
                initialfile="multiroblox-profiles.mrprofiles",
                filetypes=[("MultiRoblox backup", "*.mrprofiles"),
                           ("All files", "*.*")])
        except Exception:
            path = None
        if not path:
            return
        try:
            count = export_profiles(self.profiles, dlg.result, path)
        except Exception as ex:
            messagebox.showerror("Export failed", str(ex))
            return
        self.log("Exported %d profile(s) to %s" % (count, path))
        messagebox.showinfo(
            "Backup saved",
            "%d profile(s) saved.\n\nThis file contains live account cookies. "
            "Keep it somewhere private and do not send it to anyone." % count)

    def import_profiles_dialog(self):
        if not self.storage_enabled:
            return
        try:
            path = filedialog.askopenfilename(
                parent=self.root, title="Open profile backup",
                filetypes=[("MultiRoblox backup", "*.mrprofiles"),
                           ("All files", "*.*")])
        except Exception:
            path = None
        if not path:
            return
        dlg = EnterPasswordDialog(self.root, title="Backup password",
                                  prompt="Password for this backup file:")
        self.root.wait_window(dlg)
        if dlg.result is None:
            return
        try:
            incoming = import_profiles(dlg.result, path)
        except Exception as ex:
            messagebox.showerror(
                "Import failed",
                "Could not read that backup:\n%s\n\n(A wrong password looks "
                "exactly like a corrupt file.)" % ex)
            return
        if not incoming:
            self.log("That backup contained no profiles.")
            return

        existing = {p.get("name") for p in self.profiles}
        added = 0
        for p in incoming:
            name = p.get("name", "Imported")
            if name in existing:
                n = 2
                while "%s (%d)" % (name, n) in existing:
                    n += 1
                p["name"] = "%s (%d)" % (name, n)
            existing.add(p["name"])
            self.profiles.append(p)
            added += 1
        if self._persist_profiles():
            self.refresh_profile_list()
            self.log("Imported %d profile(s). Run Check All to see which "
                     "cookies are still valid." % added)

    def change_password(self):
        if not self.storage_enabled:
            return
        current = EnterPasswordDialog(self.root, title="Confirm Current Password",
                                      prompt="Enter your current master password:")
        self.root.wait_window(current)
        if current.result is None:
            return
        if try_unlock(current.result) is None:
            messagebox.showerror("Incorrect password", "That's not your current master password.")
            return

        dlg = CreatePasswordDialog(self.root, title="Set a New Master Password")
        self.root.wait_window(dlg)
        if not dlg.result:
            return

        try:
            self.fernet = change_master_password(self.fernet, dlg.result)
        except Exception as ex:
            messagebox.showerror(
                "Change failed",
                "The master password was NOT changed:\n%s\n\n"
                "A backup of your previous profile store is at:\n%s" % (ex, profiles_path() + ".bak")
            )
            self.log("Master password change failed: %s" % ex)
            return
        self.log("Master password changed. (Backup of the old store: profiles.enc.bak)")

    # ---------------- launching ----------------
    def launch_guest(self):
        if self.busy:
            return
        self._ensure_fps_cap()
        self.set_busy(True, "Launching guest instance...")

        def worker():
            try:
                self._launch_and_unlock(None)
            except Exception as ex:
                self.log("Launch error: %s" % ex)
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def launch_selected_profiles(self):
        if self.busy:
            return
        real_indices = self._selected_profile_indices()
        if not real_indices:
            self.log("Select one or more profiles first (or use Launch All).")
            return
        self._launch_profiles([self.profiles[i] for i in real_indices])

    def launch_all_profiles(self):
        if self.busy:
            return
        if not self.profiles:
            self.log("There are no saved profiles to launch.")
            return
        self._launch_profiles(list(self.profiles))

    def launch_profile_by_name(self, name):
        """Used by the --launch command-line flag - matching launch_all /
        launch_selected's own logic, just selecting by name instead of a
        listbox index."""
        if self.busy:
            return
        matches = [p for p in self.profiles if p.get("name") == name]
        if not matches:
            self.log('No saved profile is named "%s" - check --launch '
                     "matches it exactly (case-sensitive)." % name)
            return
        self._launch_profiles(matches)

    def _ensure_fps_cap(self):
        cap = self.settings.get("fps_cap", "off")
        if cap in ("off", "0", "", None):
            return
        ok, msg = apply_fps_cap(cap)
        if not ok:
            self.log("Frame rate cap not applied: %s" % msg)

    def _launch_profiles(self, selected):
        self._ensure_fps_cap()
        for p in selected:                      # a manual launch clears the budget
            self.rejoin_counts.pop(p.get("name"), None)
        self.set_busy(True, "Launching %d profile(s)..." % len(selected))

        def worker():
            try:
                for i, profile in enumerate(selected):
                    self.log("Launching profile: " + profile.get("name", "Unnamed"))
                    self._launch_and_unlock(profile)
                    if i < len(selected) - 1:
                        time.sleep(max(0.0, float(self.settings["launch_stagger"])))
            except Exception as ex:
                self.log("Launch error: %s" % ex)
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def free_existing_lock(self):
        """Release the single-instance lock BEFORE starting a new client.

        Whichever client created the lock owns it - usually one that was
        already running long before this app started. A new client checks for
        that lock at startup and quits on the spot if it is held, which is why
        launches were dying instantly. Closing that one handle frees the lock;
        the client holding it carries on running and playing, untouched in
        every other way.
        """
        if not IS_WINDOWS:
            return 0
        quiet = lambda _msg: None  # noqa: E731
        freed = 0
        for p in get_roblox_processes():
            try:
                if close_singleton_mutex(p.pid, quiet):
                    freed += 1
                    with self.pid_lock:
                        self.unlocked_pids.add(p.pid)
            except Exception:
                continue
        return freed

    def _launch_and_unlock(self, profile):
        before = {p.pid for p in get_roblox_processes()}
        if before:
            freed = self.free_existing_lock()
            if freed:
                self.log("Released the single-instance lock held by an existing "
                         "client (it keeps running) - a new one can now start.")
            else:
                self.log("%d client(s) already running; none of them was holding "
                         "the lock." % len(before))

        target_pid = None
        if profile and profile.get("cookie"):
            target_pid = self._try_launch_signed_in(profile)
            if target_pid is None:
                name = profile.get("name", "Unnamed")
                if not profile.get("allow_guest_fallback"):
                    # A guest launch signs in as whoever the Roblox app already
                    # has - NOT this profile. Silently opening the wrong account
                    # is worse than opening nothing, so stop here.
                    self.log('Sign-in failed for "%s" - not launching. A guest '
                             'launch would open whichever account the Roblox app '
                             'is already signed into, not this one.' % name)
                    self.log('  Fix the cookie, or tick "fall back to a guest '
                             'launch" on this profile if you want that.')
                    return
                self.log('Direct sign-in failed for "%s" - falling back to a '
                         'guest launch, as this profile allows.' % name)

        if target_pid is None:
            if not self._launch_guest_client():
                return
            target_pid = self._wait_for_new_pid(before)

        if target_pid is None:
            self.log("Timed out waiting for the new Roblox window to appear.")
            return

        with self.pid_lock:
            self.handled[target_pid] = time.time()
            label = profile.get("name", "Unnamed") if profile else "guest"
            self.pid_labels[target_pid] = label
            self.pid_started[target_pid] = time.time()
        if self.layouts.get(label):
            threading.Thread(target=self._restore_one_layout,
                             args=(target_pid, label), daemon=True).start()

        self._handle_new_instance(target_pid, False)

        # If the client we started is gone and nothing replaced it, the launch
        # did not really take - say so instead of leaving the log looking fine.
        if not process_alive(target_pid):
            time.sleep(2.0)
            replacement = {p.pid for p in get_roblox_processes()} - before - {target_pid}
            if not replacement:
                handler, cmd = detect_launch_handler()
                self.log("Roblox started (PID %d) and then closed straight away, "
                         "with no window left behind." % target_pid)
                if handler and handler != "Roblox (official)":
                    self.log("  %s is handling Roblox launches on this PC, which "
                             "can interfere with a direct signed-in launch." % handler)
                    self.log("  command: %s" % cmd)

    def _launch_guest_client(self):
        try:
            os.startfile("roblox-player:1+launchmode:play")
            return True
        except Exception:
            pass
        exe = find_roblox_exe()
        if exe:
            try:
                subprocess.Popen([exe, "--app"])
                return True
            except Exception as ex:
                self.log("Couldn't start Roblox: %s" % ex)
                return False
        self.log("Couldn't auto-launch Roblox. Please open it manually from the website.")
        return False

    def _await_new_client(self, before, seconds):
        """Waits for a new Roblox client that is still alive a moment later,
        so a starter process that immediately hands off isn't mistaken for
        either a success or a failure."""
        deadline = time.time() + max(3, int(seconds))
        while time.time() < deadline:
            time.sleep(0.5)
            candidates = {p.pid for p in get_roblox_processes()} - before
            if not candidates:
                continue
            time.sleep(2.0)
            alive = sorted(p for p in candidates if process_alive(p))
            if alive:
                return alive[-1]
            # everything it started has gone; give the method one more chance
            before = before | candidates
        return None

    def _wait_for_new_pid(self, before):
        deadline = time.time() + max(5, int(self.settings["launch_timeout"]))
        while time.time() < deadline:
            time.sleep(0.5)
            new_pids = {p.pid for p in get_roblox_processes()} - before
            if new_pids:
                # Roblox often starts a short-lived launcher process that hands
                # off to the real client and exits, so give it a moment and then
                # only accept a PID that is still alive.
                time.sleep(1.5)
                alive = sorted(p for p in new_pids if process_alive(p))
                if alive:
                    return alive[-1]
        return None

    def _try_launch_signed_in(self, profile):
        """Returns the launched PID, or None if the signed-in launch failed.

        Roblox has changed its accepted launch arguments more than once, so
        rather than betting on one form this tries each in turn and keeps the
        first that produces a client still running a few seconds later."""
        exe_path = find_roblox_exe()
        if not exe_path:
            self.log("Couldn't find RobloxPlayerBeta.exe - is Roblox installed?")
            return None

        place_id = (profile.get("place_id") or "").strip() or None
        link_code = (profile.get("link_code") or "").strip() or None
        job_id = (profile.get("job_id") or "").strip() or None

        # Keep a gap between sign-in requests: firing several at once is what
        # triggers Roblox's rate limiter during Launch All.
        gap = float(self.settings.get("ticket_spacing", 5.0) or 0)
        with self._ticket_lock:
            wait = gap - (time.time() - self._last_ticket_at)
            if wait > 0:
                time.sleep(wait)
            self._last_ticket_at = time.time()
        preferred = self.settings.get("launch_method", "auto")
        methods = list(LAUNCH_METHODS) if preferred == "auto" else [preferred]

        learned = self.settings.get("launch_method_learned", "")
        if preferred == "auto" and learned in methods:
            methods.remove(learned)
            methods.insert(0, learned)

        handler, handler_cmd = detect_launch_handler()
        handler_exe = handler_exe_from_command(handler_cmd)
        if not handler_exe or handler == "Roblox (official)":
            if "handler" in methods:
                methods.remove("handler")

        for index, method in enumerate(methods):
            # A Roblox auth ticket is single-use, so every attempt needs a
            # fresh one. Reusing the first ticket made methods 2 and 3 fail
            # no matter what they were doing.
            ticket, detail = get_auth_ticket(profile.get("cookie", ""), self.log)
            if not ticket:
                self.log("Couldn't get an auth ticket: %s" % detail)
                if index == 0:
                    ok, msg = validate_cookie(profile.get("cookie", ""))
                    self.log("  cookie check: %s" % msg)
                    if ok:
                        self.log("  the cookie is fine, so Roblox refused the "
                                 "ticket request itself - try again in a minute.")
                    return None
                continue

            before = {p.pid for p in get_roblox_processes()}
            try:
                cmd = build_launch_command(exe_path, ticket, method, place_id,
                                           handler_exe, link_code, job_id)
                if not cmd:
                    continue
                subprocess.Popen(cmd)
            except Exception as ex:
                self.log("Launch method '%s' could not start: %s" % (method, ex))
                continue

            # Roblox's starter process routinely exits and hands off to a
            # different PID, so watching only the PID we spawned reported
            # perfectly good launches as failures. Accept ANY new client that
            # appears and is still alive a moment later.
            found = self._await_new_client(before, seconds=18)
            if found:
                if preferred == "auto" and self.settings.get(
                        "launch_method_learned") != method:
                    # Remember what works on THIS machine, but leave the
                    # setting on "auto" so another PC re-detects for itself.
                    self.settings["launch_method_learned"] = method
                    save_settings(self.settings)
                    self.log("Launch method '%s' worked (%s) - it will be tried "
                             "first from now on."
                             % (method, LAUNCH_METHOD_LABELS[method]))
                return found
            self.log("Launch method '%s' (%s) left no client running."
                     % (method, LAUNCH_METHOD_LABELS[method]))

        self.log("None of the signed-in launch methods kept a client open.")
        return None

    # ---------------- shutdown ----------------
    def on_close(self):
        if not self.closing and self.watcher_running and self.pid_labels:
            try:
                if not messagebox.askyesno(
                        "Close MultiRoblox?",
                        "The watcher is on and %d client(s) launched from here are "
                        "still running.\n\nClosing leaves them running, but nothing "
                        "will unlock or rejoin them any more.\n\nClose anyway?"
                        % len(self.pid_labels)):
                    return
            except Exception:
                pass

        try:
            self.settings["window_geometry"] = self.root.geometry()
            self.settings["last_tab"] = int(
                self.notebook.index(self.notebook.select()))
        except Exception:
            pass

        self.closing = True
        self.watcher_stop.set()
        self.watcher_running = False
        if self._refresh_job:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
        if self._screenshot_job:
            try:
                self.root.after_cancel(self._screenshot_job)
            except Exception:
                pass
        if self._settings_save_job:
            try:
                self.root.after_cancel(self._settings_save_job)
            except Exception:
                pass
        save_settings(self.settings)
        self._restore_priorities()
        self._unmute_all()
        self.stop_hotkeys()
        self.stop_tray()
        try:
            self.root.destroy()
        except Exception:
            pass


def doctor():
    """`python multi_roblox.py --doctor` - prints why a package won't load."""
    print("MultiRoblox environment check")
    print("-----------------------------")
    print("running from: " + python_description())
    print("config dir  : " + config_dir())
    print("windows     : %s   administrator: %s" % (IS_WINDOWS, is_admin()))
    for name, obj in (("psutil", psutil), ("requests", requests),
                      ("cryptography", Fernet)):
        if obj is not None:
            print("OK  %s" % name)
        else:
            print("--  %s\n    why: %s\n%s"
                  % (name, IMPORT_ERRORS.get(name, "unknown"), install_hint(name)))


def _excepthook(exc_type, exc_value, tb):
    report_crash("the main thread", (exc_type, exc_value, tb))
    try:
        messagebox.showerror(
            "MultiRoblox has hit a problem",
            "%s: %s\n\nThe full details were written to:\n%s"
            % (exc_type.__name__, exc_value, log_file_path()))
    except Exception:
        pass


def main():
    sys.excepthook = _excepthook
    try:
        threading.excepthook = lambda args: report_crash(
            "a background thread",
            (args.exc_type, args.exc_value, args.exc_traceback))
    except Exception:
        pass

    argv = sys.argv[1:]
    if "--doctor" in argv:
        doctor()
        return

    # For Task Scheduler / a desktop shortcut, not truly unattended: if a
    # master password is set, authenticate() below still has to ask for it -
    # there is no flag that puts it in a config file, since that would
    # defeat the entire point of encrypting the profile store. What this
    # DOES skip is opening the window and clicking through tabs/selection
    # by hand every time.
    cli_launch_all = "--launch-all" in argv
    cli_launch_name = None
    if "--launch" in argv:
        idx = argv.index("--launch")
        if idx + 1 < len(argv):
            cli_launch_name = argv[idx + 1]
    cli_minimized = "--minimized" in argv or cli_launch_all or cli_launch_name

    # Only prints when a console is attached (a --windowed build has none).
    if sys.stdout is not None:
        try:
            print("MultiRoblox starting... if you don't see a window, it may be "
                  "behind this one - press Alt+Tab.")
        except Exception:
            pass

    root = tk.Tk()
    root.withdraw()
    root.configure(bg=BG)
    apply_appearance_settings(root)

    if not IS_WINDOWS:
        messagebox.showwarning(
            "Windows only",
            "MultiRoblox can only unlock and launch Roblox on Windows.\n\n"
            "The window will still open so you can look around, but launching "
            "and unlocking are disabled."
        )

    fernet, ok = authenticate(root)
    if not ok:
        root.destroy()
        return

    root.deiconify()
    app = MultiRobloxApp(root, fernet)
    if cli_minimized:
        app._start_minimised()
    else:
        try:
            root.lift()
            root.focus_force()
        except Exception:
            pass

    if cli_launch_all:
        root.after(500, app.launch_all_profiles)
    elif cli_launch_name:
        root.after(500, lambda: app.launch_profile_by_name(cli_launch_name))

    root.mainloop()


if __name__ == "__main__":
    main()
