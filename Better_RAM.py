"""
Better RAM - Windows only.
    pip install customtkinter requests psutil playwright
    python Better_RAM.py   (relaunches itself without a console window; add --console to keep it)

Layout: small embedded tiles on the left, the focused instance docked as a real window over the right pane.
Tabs: Dashboard (accounts + log) | Viewer | Settings.
Uses the same accounts file (%APPDATA%\\AltManager.json) as every earlier version.
"""

# =====================================================================================================================
# NOTES FOR WHOEVER EDITS THIS FILE NEXT (a person or a brand new AI chat) - read this first
#  1. Every function and class gets a comment on the line directly above it saying WHAT it does and WHEN it was made,
#     e.g.  "# Shows the GPU % of each account (added v37)."  When you change an existing function later, keep its comment
#     and append what changed, e.g.  "(added v37; changed v39: also shows VRAM)".  New functions: write the comment first.
#     Functions tagged "(v28 or earlier)" existed in the first version this history starts from.
#  2. Bump VERSION on every change you publish: running copies only update when the published file has a higher number.
#  3. Do not touch UPDATE_URL, and keep the data/config file format backward compatible (a new setting goes into DEFAULTS
#     with a default value; old files must keep loading).
#  4. Native dialogs are forbidden while a game window is docked: use self.note / self.confirm / self.ask (in-app prompts).
#  5. Background threads must never touch Tk widgets or self.windows directly: hand the work over with self.after(0, ...).
#  6. Layout rules: the Dashboard columns are locked 60/40 and the summary labels have fixed widths on purpose, so changing
#     numbers never resize the UI. Keep new labels fixed-width and keep the window's minimum size.
#
# CHANGE HISTORY (newest last)
#  v29  GPU column + summary; saved-game 'Accounts will join' line and delete confirmation; status line moved to the top
#  v30  Viewer bottom strip: Anti-AFK now / Anti-AFK / Connection watch stacked on the left, AFK account list on the right
#  v31-32  AFK account list is a grid of equal cells, vertical scrollbar only when more than 3 rows are needed
#  v33  Drag a tile onto the 'Focused' placeholder (or the placeholder onto a tile) to switch; status line removed,
#       hints (say) now go to the log panel
#  v34  'Trim now' button removed (automatic trim stays)
#  v35  Tile repaint nudge (nudge / nudge_all) for tiles stuck on old frames
#  v36  Tighter padding, locked 60/40 columns, fixed-width summary, outdated-Roblox check, Roll call view, 'In game' timer
#  v37  Join-user mode (saved users, error messages), Performance view (VRAM, disk read/write), tile-area limits shown
#       in Settings, saved-games card halved, comments restored and documented
#  v38  Docked game window follows the manager: 200 ms when idle, 10 ms (with a 1 ms Windows timer) while the manager is being
#       moved, instant re-dock on tab change (kick_track / on_move / track_dock)
#  v39  Viewer layout settings: tile size / tile area apply by themselves 0.7 s after typing (layout_changed / live_layout);
#       a custom tile size is never replaced by the automatic one: when it does not fit it is scaled down, same proportions
#  v40  Tiles stack from the top-left corner, the focused window fills all the remaining space; optional animations
#       (Settings > Animations): tiles that only change position slide, a switched tile flashes its border; one shared
#       16 ms ticker that stops by itself (no idle CPU), moves only - never resizes a game window (move_cell / anim_tick)
#  v41  Macros tab: record / edit / save click, hold, swipe, key-combo macros (positions are fractions of the window, so they
#       work on any account) and run them like Anti-AFK on the focused / all / one account, with a configurable global hotkey;
#       Discord bot alerts for crashes and disconnects (REST only, token stored DPAPI-encrypted)
#  v42  Background input: Anti-AFK and macros can post their clicks / swipes / keys straight to the game windows (no cursor movement,
#       no focus change, no tab switching, all accounts at once; Settings > Anti-AFK and Macros tab 'Background input').
#       Visual macro builder (Macros tab > Visual builder): see-through, non-activating overlay over the focused window with numbered,
#       draggable widgets per step + floating panel with [+] / [-], reorder, undo, test and named macro slots (save / load)
# =====================================================================================================================
import atexit, base64, ctypes, ctypes.wintypes as wt, json, os, random, re, shutil, socket, stat, struct, subprocess, sys, tempfile, threading, time
import tkinter as tk
from tkinter import messagebox
from urllib.parse import quote

if os.name == "nt" and os.path.basename(sys.executable).lower() == "python.exe" and "--console" not in sys.argv:
    _pw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")      # same Python, no console window
    if os.path.exists(_pw):
        subprocess.Popen([_pw, os.path.abspath(__file__)], creationflags=0x00000008, close_fds=True); sys.exit()

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)   # real pixels, not scaled (must run before any window exists)
except Exception: pass

try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BetterRAM.App")   # own taskbar identity -> own icon
except Exception: pass

VERSION = 42                       # bump this in the file you publish; running copies update when it is higher
UPDATE_URL = "https://raw.githubusercontent.com/br0dax457-droid/Better-RAM/main/Better_RAM.py"   # built-in update link

# ======================= dependencies: install what's missing, re-check weekly =======================
DEPS = {"customtkinter": "customtkinter", "requests": "requests", "psutil": "psutil", "playwright": "playwright"}   # module -> pip name
CORE = ("customtkinter", "requests", "psutil")           # needed to start (playwright is only for "Add via browser")
DEPS_STAMP = os.path.join(os.getenv("APPDATA", "."), "AltManager.deps.json")

# Startup check: installs or updates missing pip packages in a small progress window before the app loads (v28 or earlier).
def ensure_dependencies():
    import importlib, importlib.util
    try: stamp = json.load(open(DEPS_STAMP))
    except Exception: stamp = {}
    names = sorted(DEPS.values())
    missing = [p for m, p in DEPS.items() if importlib.util.find_spec(m) is None]
    stale = stamp.get("deps") != names or time.time() - stamp.get("checked", 0) > 7 * 86400
    if not missing and not stale: return                 # fast path: straight to the app, no pip, no window
    out = {}
    # Background thread that runs pip install for ensure_dependencies.
    def work():
        try:
            out["r"] = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "-q",
                                       "--timeout", "10", "--retries", "1", *(names if stale else missing)],
                                      capture_output=True, text=True, timeout=900, creationflags=0x08000000)
        except Exception as ex: out["err"] = str(ex)
    t = threading.Thread(target=work, daemon=True); t.start()
    root = tk.Tk(); root.title("Better RAM"); root.configure(bg="#08080a"); root.geometry("380x90"); root.resizable(False, False)
    tk.Label(root, text="Installing required packages..." if missing else "Checking for package updates...",
             bg="#08080a", fg="#ececee", font=("Segoe UI", 11)).pack(expand=True)
    # Polls until pip has finished, then closes the progress window.
    def wait():
        if t.is_alive(): root.after(200, wait)
        else: root.destroy()
    wait(); root.mainloop()
    importlib.invalidate_caches()
    r = out.get("r"); ok = bool(r and r.returncode == 0)
    gone = [m for m in CORE if importlib.util.find_spec(m) is None]
    if gone:
        messagebox.showerror("Better RAM", "Could not install: " + ", ".join(gone) + "\n\n" + ((r.stderr if r else out.get("err", "")) or "")[-500:])
        sys.exit(1)
    try:                                                 # a failed refresh (offline) is retried the next day
        with open(DEPS_STAMP, "w") as fh: json.dump({"checked": time.time() - (0 if ok else 6 * 86400), "deps": names}, fh)
    except Exception: pass

ensure_dependencies()
import customtkinter as ctk
import psutil, requests

APPDATA = os.getenv("APPDATA", ".")
DATA = os.path.join(APPDATA, "AltManager.json")
LOG = os.path.join(APPDATA, "AltManager.log")
SETTINGS = os.path.join(os.getenv("LOCALAPPDATA", "."), "Roblox", "GlobalBasicSettings_13.xml")

user32, kernel32, crypt32, psapi = (ctypes.windll.user32, ctypes.windll.kernel32,
                                    ctypes.windll.crypt32, ctypes.windll.psapi)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
psapi.EmptyWorkingSet.argtypes = [wt.HANDLE]
user32.WindowFromPoint.argtypes = [wt.POINT]
for _fn in ("WindowFromPoint", "GetAncestor", "GetParent", "GetWindow", "SetParent"):
    getattr(user32, _fn).restype = wt.HWND
user32.SetParent.argtypes = [wt.HWND, wt.HWND]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowRgn.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
gdi32 = ctypes.windll.gdi32
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6

# palette: black + deep gray
BG, CARD, FIELD, BTN, BTN_H = "#08080a", "#141518", "#1e2024", "#2a2c32", "#3a3d45"
TXT, MUTED, GREEN, ORANGE, RED = "#ececee", "#8a8d96", "#5fd38d", "#f0a030", "#ff6b6b"

DEFAULTS = {"accounts": [], "games": [], "place": "", "delay": 6,
            "pane": 38, "micro": False, "windowWidth": 320, "windowHeight": 240, "badges": True,
            "gfx": True, "fps": 15, "quality": 1, "mute": True,
            "trim": True, "trim_sec": 90, "lowprio": True,
            "afk": False, "afk_min": 8, "afk_off": 8, "afk_gap": 1200,
            "watch": True, "watch_sec": 60, "auto_rejoin": False, "afk_skip": [], "idle_prio": [], "view_order": [],
            "update_url": "", "auto_update": True, "hotkeys": True, "compact": False, "perf": False,
            "join_mode": "game", "join_user": "", "users": [],
            "anim": True, "animMs": 160,
            "macros": {}, "macro_sel": "", "macro_target": "Focused account", "macro_loops": 1, "macro_key": "ctrl+alt+m",
            "dc_on": False, "dc_chan": "", "dc_token": "",
            "afk_bg": False, "macro_bg": False, "bg_wake": True}
STR_KEYS = {"place", "update_url", "join_user", "dc_chan", "macro_key"}
USER_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")

# ======================= GPU usage (Windows "GPU Engine" performance counters) =======================
class _PdhVal(ctypes.Structure): _fields_ = [("CStatus", ctypes.c_ulong), ("d", ctypes.c_double)]
# ctypes layout of one (name, value) entry returned by the Windows performance-counter API; used by gpu_sample (added v29).
class _PdhItem(ctypes.Structure): _fields_ = [("name", ctypes.c_wchar_p), ("val", _PdhVal)]
_GPU_RE = re.compile(r"pid_(\d+)_luid_(\S+?)_phys_(\d+)_eng_\d+_engtype_(\w+)", re.I)

# Reads every instance of a wildcard performance counter as (name, status, value) rows (added v37).
def _pdh_array(pdh, counter):
    size, cnt = ctypes.c_ulong(0), ctypes.c_ulong(0)
    pdh.PdhGetFormattedCounterArrayW(counter, 0x200, ctypes.byref(size), ctypes.byref(cnt), None)
    if not size.value: return []
    buf = ctypes.create_string_buffer(size.value)
    if pdh.PdhGetFormattedCounterArrayW(counter, 0x200, ctypes.byref(size), ctypes.byref(cnt), buf) != 0: return None
    items = ctypes.cast(buf, ctypes.POINTER(_PdhItem))
    return [(items[i].name or "", items[i].val.CStatus, items[i].val.d) for i in range(cnt.value)]

def gpu_sample(wait=1.0):
    """-> ({pid: gpu %}, total gpu %, {pid: dedicated VRAM bytes} or None) or None when the counters are unavailable."""
    try:
        pdh = ctypes.windll.pdh
        pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                                      ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
        q, c, cm = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(q)) != 0: return None
        try:
            if pdh.PdhAddEnglishCounterW(q, r"\GPU Engine(*)\Utilization Percentage", 0, ctypes.byref(c)) != 0: return None
            has_mem = pdh.PdhAddEnglishCounterW(q, r"\GPU Process Memory(*)\Dedicated Usage", 0, ctypes.byref(cm)) == 0
            pdh.PdhCollectQueryData(q); time.sleep(wait); pdh.PdhCollectQueryData(q)
            rows = _pdh_array(pdh, c)
            if rows is None: return None
            per, tot = {}, {}
            for name, status, val in rows:
                m = _GPU_RE.search(name)
                if not m or status not in (0, 1): continue
                pid, adapter, eng = int(m.group(1)), (m.group(2), m.group(3)), m.group(4).lower()
                v = max(0.0, val)
                per[(pid, adapter, eng)] = per.get((pid, adapter, eng), 0.0) + v
                tot[(adapter, eng)] = tot.get((adapter, eng), 0.0) + v
            by_pid = {}
            for (pid, _, _), v in per.items(): by_pid[pid] = max(by_pid.get(pid, 0.0), v)
            vram = None
            if has_mem:
                mem = _pdh_array(pdh, cm)
                if mem is not None:
                    vram = {}
                    for name, status, val in mem:
                        m = re.search(r"pid_(\d+)_", name)
                        if m and status in (0, 1): vram[int(m.group(1))] = vram.get(int(m.group(1)), 0.0) + max(0.0, val)
            return {p: min(100.0, v) for p, v in by_pid.items()}, min(100.0, max(tot.values(), default=0.0)), vram
        finally: pdh.PdhCloseQuery(q)
    except Exception: return None

# ======================= cookies (Windows DPAPI) =======================
class BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

# Encrypts/decrypts bytes with Windows DPAPI (tied to this Windows user); this is how saved cookies are protected (v28 or earlier).
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    inb = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    res = ctypes.string_at(out.pbData, out.cbData)
    kernel32.LocalFree(out.pbData)
    return res

enc = lambda s: base64.b64encode(_dpapi(s.encode(), True)).decode()
dec = lambda s: _dpapi(base64.b64decode(s), False).decode()

# ======================= Roblox web API =======================
def whoami(cookie):
    """-> (user id, user name)"""
    r = requests.get("https://users.roblox.com/v1/users/authenticated",
                     cookies={".ROBLOSECURITY": cookie}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j["id"], j["name"]

def roblox_post(url, cookie, body=None):
    """POST with the CSRF handshake Roblox requires."""
    h = {"Referer": "https://www.roblox.com/", "Origin": "https://www.roblox.com", "Content-Type": "application/json"}
    c = {".ROBLOSECURITY": cookie}
    data = None if body is None else json.dumps(body)
    r = requests.post(url, headers=h, cookies=c, data=data, timeout=15)
    if r.status_code == 403 and "x-csrf-token" in r.headers:
        h["X-CSRF-TOKEN"] = r.headers["x-csrf-token"]
        r = requests.post(url, headers=h, cookies=c, data=data, timeout=15)
    return r

# Asks Roblox for a one-time login ticket for a cookie; raises 'No ticket' when the cookie is expired (v28 or earlier).
def auth_ticket(cookie):
    t = roblox_post("https://auth.roblox.com/v1/authentication-ticket", cookie).headers.get("rbx-authentication-ticket")
    if not t: raise RuntimeError("No ticket - cookie expired or invalid")
    return t

def presence_type(cookie, uid):
    """0 offline, 1 online, 2 in a game, 3 in Studio."""
    r = roblox_post("https://presence.roblox.com/v1/presence/users", cookie, {"userIds": [uid]})
    r.raise_for_status()
    return r.json()["userPresences"][0]["userPresenceType"]

# Builds the roblox-player: link that starts the game; a job id joins that exact server (v28 or earlier).
def launch_uri(ticket, place, job=""):
    bt = random.randint(10**10, 10**11)
    req = f"RequestGameJob&gameId={job}" if job else "RequestGame"
    pl = (f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request={req}"
          f"&browserTrackerId={bt}&placeId={place}&isPlayTogetherGame=false")
    return (f"roblox-player:1+launchmode:play+gameinfo:{ticket}+launchtime:{int(time.time()*1000)}"
            f"+placelauncherurl:{quote(pl, safe='')}+browsertrackerid:{bt}"
            f"+robloxLocale:en_us+gameLocale:en_us+channel:+LaunchExp:InApp")

# Pulls the numeric place id out of a typed ID or a roblox.com/games link (v28 or earlier).
def parse_place(text):
    m = re.search(r"games/(\d+)", text) or re.search(r"(\d{5,})", text)
    return m.group(1) if m else ""

PERF_COLS = (("", 12, "w"), ("Account", 120, "w"), ("CPU", 46, "e"), ("GPU", 46, "e"), ("VRAM", 64, "e"),
             ("RAM", 68, "e"), ("Read", 74, "e"), ("Write", 74, "e"))
PERF_PAD = 3

def short_status(t):
    """Roll-call view: one short word per account."""
    if "outdated" in t: return "Outdated"
    t = t.split(" (")[0].split(" - ")[0]
    return {"Disconnected": "Offline", "Cookie expired": "Re-login", "Crashed / closed": "Crashed"}.get(t, t)

# Formats seconds as '<1m', '12m' or '1h 05m' for the 'In game' timer (added v36).
def fmt_dur(sec):
    m = int(sec // 60); h, m = divmod(m, 60)
    return "<1m" if sec < 60 else (f"{h}h {m:02d}m" if h else f"{m}m")

# Formats a byte count as MB or GB for the VRAM column (added v37).
def fmt_bytes(b):
    return f"{b/1073741824:.1f} GB" if b >= 1073741824 else f"{b/1048576:.0f} MB"

# Formats bytes per second as KB/s or MB/s for the disk columns (added v37).
def fmt_rate(bps):
    return f"{bps/1048576:.1f} MB/s" if bps >= 1048576 else f"{bps/1024:.0f} KB/s"

def resolve_user(name, cookies):
    """-> (place id, job id, shown name, error text). Looks up where a Roblox user is playing right now."""
    if not cookies: return "", "", name, "None of the selected accounts has a valid login to look the user up with."
    try:
        r = roblox_post("https://users.roblox.com/v1/usernames/users", cookies[0], {"usernames": [name], "excludeBannedUsers": False})
        r.raise_for_status(); data = r.json().get("data") or []
    except Exception: return "", "", name, "Couldn't reach Roblox to look that user up. Try again in a moment."
    if not data: return "", "", name, f'There is no Roblox user called "{name}" - check the spelling.'
    uid, shown = data[0]["id"], data[0]["name"]
    seen = set()
    for ck in cookies:
        try:
            r = roblox_post("https://presence.roblox.com/v1/presence/users", ck, {"userIds": [uid]}); r.raise_for_status()
            p = r.json()["userPresences"][0]
        except Exception: seen.add("net"); continue
        t = p.get("userPresenceType", 0); place = p.get("placeId") or p.get("rootPlaceId"); job = p.get("gameId")
        if t == 2 and place and job: return str(place), job, shown, ""
        seen.add("blocked" if t == 2 else "studio" if t == 3 else "offline")
    if "blocked" in seen:
        return "", "", shown, (f"{shown} is in a game, but their privacy settings (who can join them) don't let your accounts join. "
                               "Ask them to allow it, or make one of your accounts their friend.")
    if "studio" in seen: return "", "", shown, f"{shown} is in Roblox Studio, not in a game."
    if "offline" in seen: return "", "", shown, f"{shown} isn't in a game right now (offline, on the website, or hidden by their privacy settings)."
    return "", "", shown, "Couldn't reach Roblox to check where that user is. Try again in a moment."

RBX_VERSION_URL = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer"

def put(r, key, text, color=None):
    """Update a dashboard label only if its text/colour actually changed (CTk redraws are expensive).
    Keys a row does not have (roll-call rows only show the status) are skipped."""
    w = r.get(key)
    if w is None: return
    if key == "st" and r.get("short"): text = short_status(text)
    if r.get(key + "_v") == (text, color): return
    r[key + "_v"] = (text, color)
    w.configure(text=text, **({"text_color": color} if color else {}))

def _icon_bytes():
    """Default icon, drawn in code (no image file needed): two small tiles + one big focused tile. Classic 32-bit .ico."""
    # Draws one pixel layer of the default app icon in code, so no image file is needed (v28 or earlier).
    def layer(u, v):
        # Tells whether a point lies inside a rounded square (icon drawing helper) (v28 or earlier).
        def rr(x0, y0, x1, y1, r):
            dx, dy = max(x0 + r - u, 0, u - (x1 - r)), max(y0 + r - v, 0, v - (y1 - r))
            return dx * dx + dy * dy <= r * r
        if not rr(0, 0, 1, 1, .22): return None
        if rr(.42, .14, .86, .86, .07): return (236, 236, 238)
        if rr(.14, .14, .36, .47, .06) or rr(.14, .53, .36, .86, .06): return (110, 113, 122)
        return (20, 21, 24)
    imgs = []
    for s in (16, 32, 48):
        px = bytearray()
        for y in range(s - 1, -1, -1):                                   # bottom-up rows, 3x3 supersampling
            for x in range(s):
                r = g = b = n = 0
                for k in range(9):
                    c = layer((x + (k % 3 + .5) / 3) / s, (y + (k // 3 + .5) / 3) / s)
                    if c: r += c[0]; g += c[1]; b += c[2]; n += 1
                px += bytes((b // n, g // n, r // n, n * 255 // 9)) if n else b"\0\0\0\0"
        mask = bytes((s + 31) // 32 * 4 * s)
        imgs.append((s, struct.pack("<IiiHHIIiiII", 40, s, 2 * s, 1, 32, 0, len(px) + len(mask), 0, 0, 0, 0) + bytes(px) + mask))
    off, ents = 6 + 16 * len(imgs), b""
    for s, d in imgs: ents += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(d), off); off += len(d)
    return struct.pack("<HHH", 0, 1, len(imgs)) + ents + b"".join(d for _, d in imgs)

def app_icon():
    """Better_RAM.ico next to this file wins (your own icon); otherwise the built-in one, cached in the temp folder."""
    mine = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Better_RAM.ico")
    if os.path.exists(mine): return mine
    path = os.path.join(tempfile.gettempdir(), "BetterRAM_icon.ico")
    if not os.path.exists(path):
        with open(path, "wb") as fh: fh.write(_icon_bytes())
    return path

# Path of the user's real Desktop folder (follows OneDrive redirects) (v28 or earlier).
def desktop():
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(0, 0x10, 0, 0, buf) == 0 and buf.value: return buf.value   # follows OneDrive redirects
    return os.path.join(os.path.expanduser("~"), "Desktop")

# Finds Edge or Chrome for 'Add account via browser' (v28 or earlier).
def find_browser():
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            p = os.path.join(os.getenv(env, ""), rel)
            if os.path.exists(p): return p
    return None

# ======================= GlobalBasicSettings_13.xml (graphics lock) =======================
SKELETON = ('<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">'
            '<Item class="UserGameSettings" referent="RBX0"><Properties></Properties></Item></roblox>')

# Makes Roblox's settings file writable again (undoes the read-only lock) (v28 or earlier).
def unlock_settings():
    if os.path.exists(SETTINGS): os.chmod(SETTINGS, stat.S_IREAD | stat.S_IWRITE)

# Writes FPS cap, quality level and mute into Roblox's settings file, then locks it read-only so Roblox can't reset it (v28 or earlier).
def apply_graphics(fps, quality, mute):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    if os.path.exists(SETTINGS):
        unlock_settings(); xml = open(SETTINGS, encoding="utf-8").read()
    else:
        xml = SKELETON
    wanted = [("int", "FramerateCap", fps), ("int", "GraphicsQualityLevel", quality),
              ("token", "SavedQualityLevel", quality), ("bool", "Fullscreen", "false"), ("bool", "StartMaximized", "false")]
    if mute: wanted.append(("float", "MasterVolume", "0"))
    for tag, name, val in wanted:
        pat = rf'(<(?:token|int|float|bool)\s+name="{name}">)[^<]*(</)'
        if re.search(pat, xml): xml = re.sub(pat, lambda m: m.group(1) + str(val) + m.group(2), xml)
        else: xml = xml.replace("</Properties>", f'<{tag} name="{name}">{val}</{tag}></Properties>', 1)
    open(SETTINGS, "w", encoding="utf-8").write(xml)
    os.chmod(SETTINGS, stat.S_IREAD)                    # read-only so Roblox can't overwrite it

# ======================= Windows helpers =======================
GWL_STYLE, GWL_EXSTYLE, GWLP_HWNDPARENT = -16, -20, -8
WS_CHILD, WS_POPUP, WS_VISIBLE = 0x40000000, 0x80000000, 0x10000000
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_CLIPCHILDREN = 0x00020000, 0x00010000, 0x02000000
WS_EX_WINDOWEDGE, WS_EX_CLIENTEDGE, WS_EX_DLGMODALFRAME = 0x0100, 0x0200, 0x0001
WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = 0x00040000, 0x0080
WS_EX_LAYERED = 0x00080000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 1, 2, 4, 0x10, 0x20, 0x40
HWND_TOP = 0
STRIP = WS_POPUP | WS_CHILD | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
STRIP_EX = WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME | WS_EX_APPWINDOW

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

# Lists all visible Roblox game windows (window class WINDOWSCLIENT) (v28 or earlier).
def roblox_windows():
    found = []
    # EnumWindows callback that collects Roblox windows for roblox_windows.
    def cb(h, _):
        if user32.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, b, 64)
            if b.value == "WINDOWSCLIENT": found.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found

# Process ids of all running RobloxPlayerBeta.exe processes (v28 or earlier).
def roblox_pids():
    try: return {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "robloxplayerbeta.exe"}
    except Exception: return set()

# Process id that owns a window handle (v28 or earlier).
def pid_of(h):
    p = wt.DWORD(); user32.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value

# Screen rectangle of a window (v28 or earlier).
def win_rect(h):
    r = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r)); return r

# Window area in pixels; used to pick the real game window over the small splash window (v28 or earlier).
def win_area(h):
    r = win_rect(h); return (r.right - r.left) * (r.bottom - r.top)

# Force-closes a process by id (v28 or earlier).
def kill_pid(pid):
    try: subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=0x08000000)
    except Exception: pass

# True while the Roblox installer/updater is running; launches wait for it to finish (v28 or earlier).
def installer_running():
    try: return any((p.info["name"] or "").lower() == "robloxplayerinstaller.exe" for p in psutil.process_iter(["name"]))
    except Exception: return False

# ctypes struct for the Windows 'last user input' query (v28 or earlier).
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

# Seconds since the user last touched mouse or keyboard; Anti-AFK waits until the user is idle (v28 or earlier).
def user_idle_seconds():
    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(li)
    user32.GetLastInputInfo(ctypes.byref(li))
    return ((kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0

# ---- embedding: tiles are child windows (no top-level minimum size); the focused one is a real docked window ----
ORIG_STYLE = {}                   # hwnd -> original (style, exstyle), restored on release
EMBEDDED, DOCKED = set(), set()   # every window we modified / the subset currently docked as a real window

# Strips borders/title bar from a game window and remembers its original style so it can be restored later (v28 or earlier).
def _restyle(hw, add, add_ex=0):
    st = user32.GetWindowLongPtrW(hw, GWL_STYLE); ex = user32.GetWindowLongPtrW(hw, GWL_EXSTYLE)
    ORIG_STYLE.setdefault(hw, (st, ex))
    user32.SetWindowLongPtrW(hw, GWL_STYLE, ((st & 0xFFFFFFFF) & ~STRIP) | add)
    user32.SetWindowLongPtrW(hw, GWL_EXSTYLE, (ex & ~(STRIP_EX | WS_EX_LAYERED)) | add_ex)

# Turns a game window into a child of a viewer tile (small-tile mode) (v28 or earlier).
def embed_window(hw, parent):
    _restyle(hw, WS_CHILD | WS_VISIBLE)
    user32.SetParent(hw, parent)
    EMBEDDED.add(hw); DOCKED.discard(hw)

def dock_window(hw, owner, sx, sy, w, h, raise_=True):
    """Focused instance: a REAL top-level window (true OS focus/clicks), owned by the manager, parked over the pane."""
    if hw not in DOCKED:
        if hw in EMBEDDED:                                        # as a child its (BORDER, BORDER) becomes SCREEN coordinates
            user32.ShowWindow(hw, 0); user32.SetParent(hw, 0)     # -> hidden while it changes parent (no flash top-left)
        clear_region(hw)                                          # the focused window is not clipped
        _restyle(hw, WS_POPUP | WS_VISIBLE, WS_EX_TOOLWINDOW)     # no layered/alpha: that is what left the game surface gray
        user32.SetWindowLongPtrW(hw, GWLP_HWNDPARENT, owner)      # owned: stays above the app, hides with it
        EMBEDDED.add(hw); DOCKED.add(hw)
    user32.SetWindowPos(hw, HWND_TOP, sx, sy, w, h,
                        SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE | (0 if raise_ else SWP_NOZORDER))

GAP = 6                          # px between the tile block and the focused window (added v40)
BORDER, RADIUS = 2, 10           # tile border thickness / corner radius (px)

RGN = {}                          # hwnd -> (w, h) of the clip region already applied to a game window

# Clips a window to rounded corners (v28 or earlier).
def round_region(hw, w, h, r):
    user32.SetWindowRgn(hw, gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2), True)

# Removes the rounded-corner clip from a window (v28 or earlier).
def clear_region(hw):
    RGN.pop(hw, None); user32.SetWindowRgn(hw, None, True)

def fit_child(hw, w, h):
    """Tile content sits inset inside its (rounded, gray) cell so the cell shows as a border."""
    iw, ih = w - 2 * BORDER, h - 2 * BORDER
    user32.SetWindowPos(hw, HWND_TOP, BORDER, BORDER, iw, ih, SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    if RGN.get(hw) != (iw, ih): RGN[hw] = (iw, ih); round_region(hw, iw, ih, RADIUS - BORDER)

# Gives a game window back to the desktop with its original style (v28 or earlier).
def unembed_window(hw):
    EMBEDDED.discard(hw); DOCKED.discard(hw)
    if not user32.IsWindow(hw): return
    orig = ORIG_STYLE.pop(hw, None)
    user32.SetWindowLongPtrW(hw, GWLP_HWNDPARENT, 0)
    user32.SetParent(hw, 0); clear_region(hw)
    if orig:
        user32.SetWindowLongPtrW(hw, GWL_STYLE, orig[0]); user32.SetWindowLongPtrW(hw, GWL_EXSTYLE, orig[1])
    user32.SetWindowPos(hw, HWND_TOP, 80, 80, 960, 540, SWP_FRAMECHANGED | SWP_SHOWWINDOW)

atexit.register(lambda: [unembed_window(h) for h in list(EMBEDDED)])   # never take the games down with the app

# Blends two '#rrggbb' colours, k = 0..1 (added v40).
def mix(a, b, k):
    return "#" + "".join(f"{int(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * k):02x}" for i in (1, 3, 5))

# Key names usable in macros -> Windows virtual-key codes; MODS are the modifier keys, EXT_KEYS need the extended-key flag (added v41).
KEYMAP = {"enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "tab": 0x09, "backspace": 0x08, "delete": 0x2E,
          "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26,
          "right": 0x27, "down": 0x28, "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12, "win": 0x5B}
MODS, EXT_KEYS = (0x10, 0x11, 0x12, 0x5B), (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B)

# Virtual-key code of one key name (a-z, 0-9, F1-F24 or a KEYMAP name), or None (added v41).
def key_vk(name):
    name = name.lower()
    if name in KEYMAP: return KEYMAP[name]
    if len(name) == 1 and name.isalnum() and name.isascii(): return ord(name.upper())
    m = re.fullmatch(r"f(\d{1,2})", name)
    return 0x6F + int(m.group(1)) if m and 1 <= int(m.group(1)) <= 24 else None

# 'ctrl+shift+a' -> list of virtual-key codes, or None when any part is unknown (added v41).
def parse_combo(text):
    parts = [x.strip() for x in text.split("+") if x.strip()]
    vks = [key_vk(x) for x in parts]
    return vks if vks and None not in vks else None

# 'ctrl+alt+m' -> (RegisterHotKey modifier bits, key code) for a global hotkey: exactly one non-modifier key (added v41).
def hotkey_spec(text):
    vks = parse_combo(text)
    if not vks: return None
    bits = {0x11: 2, 0x10: 4, 0x12: 1, 0x5B: 8}
    main = [v for v in vks if v not in bits]
    return (sum(bits[v] for v in vks if v in bits), main[0]) if len(main) == 1 else None

# One macro step as a text line, e.g. ['swipe', .2, .8, .8, .2, 400] -> 'swipe 0.2 0.8 0.8 0.2 400' (added v41).
def fmt_step(st): return " ".join(str(v) for v in st)

# Macro text (one step per line, '#' comments) -> (steps, error text). Positions are fractions 0-1 of the window (added v41).
def parse_macro(text):
    steps = []
    for no, raw in enumerate(text.splitlines(), 1):
        a = raw.split("#")[0].split()
        if not a: continue
        t, a = a[0].lower(), a[1:]
        try:
            if t == "wait" and len(a) == 1: st = [t, int(a[0])]; ok = 0 <= st[1] <= 600000
            elif t == "key" and len(a) == 1: st = [t, a[0].lower()]; ok = parse_combo(a[0]) is not None
            elif t in ("click", "hold", "swipe"):
                n = {"click": 2, "hold": 3, "swipe": 5}[t]; extra = t != "swipe"
                btn = a[n].lower() if extra and len(a) == n + 1 else "left"
                if len(a) not in ((n, n + 1) if extra else (n,)) or btn not in ("left", "right"): raise ValueError
                v = [float(x) for x in a[:n]]; pos = v[:4] if t == "swipe" else v[:2]
                ms = 0 if t == "click" else int(v[-1])
                ok = all(0 <= x <= 1 for x in pos) and 0 <= ms <= 60000
                st = [t, *v[:4], ms] if t == "swipe" else [t, v[0], v[1], ms, btn] if t == "hold" else [t, v[0], v[1], btn]
            else: raise ValueError
            if not ok: raise ValueError
        except ValueError:
            return None, (f"Line {no}: can't read '{raw.strip()}'.\nUse: click x y | hold x y ms | swipe x1 y1 x2 y2 ms | key ctrl+a | wait ms\n"
                          "(x and y between 0 and 1)")
        steps.append(st)
    if len(steps) > 500: return None, "A macro can have at most 500 steps."
    return steps, ""

# ======================= Background input (added v42) =======================
# Posted window messages reach a game window without moving the real cursor and without taking focus, so the window can be an
# unfocused tile or the one in front. Nothing is injected into the game process: these are the same messages Windows itself sends.
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0200, 0x0201, 0x0202, 0x0204, 0x0205
WM_KEYDOWN, WM_KEYUP, WM_ACTIVATE = 0x0100, 0x0101, 0x0006
WS_EX_NOACTIVATE = 0x08000000
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL

# Client-area size (width, height) of a window in pixels (added v42).
def client_size(hw):
    rc = wt.RECT(); user32.GetClientRect(hw, ctypes.byref(rc)); return rc.right, rc.bottom

# Screen position of a window's client-area top-left corner (added v42).
def client_origin(hw):
    pt = wt.POINT(0, 0); user32.ClientToScreen(hw, ctypes.byref(pt)); return pt.x, pt.y

# Fractions (0-1) of the client area -> client pixel, kept inside the window; same rounding as the real-mouse macro (added v42).
def bg_pt(hw, fx, fy):
    w, h = client_size(hw)
    return min(max(int(fx * w), 0), max(w - 1, 0)), min(max(int(fy * h), 0), max(h - 1, 0))

# Posts one mouse message at a client pixel; flags are the MK_ button bits held at that moment (added v42).
def bg_mouse(hw, msg, x, y, flags=0):
    user32.PostMessageW(hw, msg, flags, (y << 16) | (x & 0xFFFF))

# Posts one key-down or key-up message with a proper scan code (and the extended-key bit for arrows etc.) (added v42).
def bg_key(hw, vk, up):
    lp = 1 | (user32.MapVirtualKeyW(vk, 0) << 16) | ((1 << 24) if vk in EXT_KEYS else 0) | ((3 << 30) if up else 0)
    user32.PostMessageW(hw, WM_KEYUP if up else WM_KEYDOWN, vk, lp)

# Tells a window it is active (on) or inactive (off) without changing the real focus; many games ignore input while inactive (added v42).
def bg_wake(hw, on):
    user32.PostMessageW(hw, WM_ACTIVATE, 1 if on else 0, 0)

# Posts a left or right click at a client pixel: move, press, hold, release. `stop` (a threading.Event) ends the pauses early (added v42).
def bg_click(hw, x, y, stop, right=False, hold=0.06):
    down, up, mk = (WM_RBUTTONDOWN, WM_RBUTTONUP, 2) if right else (WM_LBUTTONDOWN, WM_LBUTTONUP, 1)
    bg_mouse(hw, WM_MOUSEMOVE, x, y); stop.wait(0.03)
    bg_mouse(hw, down, x, y, mk); stop.wait(hold)
    bg_mouse(hw, up, x, y, 0); stop.wait(0.03)

# Plays macro steps (the Macros-tab format) on one window with posted messages only; runs in a worker thread and never touches Tk.
# on_step(i) is called before each step; wake = send the fake activation while the window is not in front; a pressed button or key
# is always released at the end, also when `stop` is set or the window disappears (added v42).
def bg_play(hw, steps, stop, wake=True, loops=1, on_step=None):
    woke = wake and user32.GetForegroundWindow() != hw
    if woke: bg_wake(hw, True)
    held, keys = None, []
    try:
        for _ in range(loops):
            for i, st in enumerate(steps):
                if stop.is_set() or not user32.IsWindow(hw): return
                if on_step: on_step(i)
                t = st[0]
                if t == "wait": stop.wait(st[1] / 1000)
                elif t == "key":
                    vks = parse_combo(st[1]) or []
                    keys = [v for v in vks if v in MODS] + [v for v in vks if v not in MODS]
                    for v in keys: bg_key(hw, v, False)
                    stop.wait(0.08)
                    for v in reversed(keys): bg_key(hw, v, True)
                    keys = []; stop.wait(0.05)
                elif t == "swipe":
                    x1, y1 = bg_pt(hw, st[1], st[2]); x2, y2 = bg_pt(hw, st[3], st[4]); ms = st[5]; n = max(2, min(40, ms // 25))
                    bg_mouse(hw, WM_MOUSEMOVE, x1, y1); stop.wait(0.03)
                    bg_mouse(hw, WM_LBUTTONDOWN, x1, y1, 1); held = (x1, y1)
                    for k in range(1, n + 1):
                        stop.wait(ms / 1000 / n)
                        if stop.is_set(): break
                        held = (x1 + (x2 - x1) * k // n, y1 + (y2 - y1) * k // n); bg_mouse(hw, WM_MOUSEMOVE, held[0], held[1], 1)
                    bg_mouse(hw, WM_LBUTTONUP, held[0], held[1], 0); held = None; stop.wait(0.04)
                else:
                    x, y = bg_pt(hw, st[1], st[2])
                    bg_click(hw, x, y, stop, st[-1] == "right", max(0.06, st[3] / 1000) if t == "hold" else 0.06)
    finally:
        for v in reversed(keys): bg_key(hw, v, True)
        if held and user32.IsWindow(hw): bg_mouse(hw, WM_LBUTTONUP, held[0], held[1], 0)
        if woke and user32.IsWindow(hw) and user32.GetForegroundWindow() != hw: bg_wake(hw, False)

# Makes a Tk top-level window non-activating: clicking it never takes the keyboard focus from the game or any other program (added v42).
def no_activate(win):
    hw = user32.GetAncestor(win.winfo_id(), 2)
    ex = user32.GetWindowLongPtrW(hw, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hw, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    user32.SetWindowPos(hw, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

# ======================= Visual macro builder (added v42) =======================
# Two floating windows that never take focus: a see-through layer exactly over the focused game window that carries one numbered,
# draggable widget per click / hold / swipe step (the colour key makes empty areas click-through, so the game stays usable), and a
# small control panel with the step list, [+] / [-], reorder, undo, named macro slots and a Test button. Positions are stored as
# fractions of the window, exactly like the Macros tab, so a macro built here runs on any account. It follows the focused account.
class MacroBuilder:
    KEY = "#010203"                                         # colour key: pixels of this colour are see-through AND click-through
    COL = {"click": "#3b8ee8", "hold": "#f0a030", "swipe": "#5fd38d"}
    R = 20                                                  # widget radius (px)
    HINT = "Drag a circle to move it  -  right-click a circle to delete it"

    # Creates the overlay and the panel over the focused window and shows the given macro; sets app.builder (added v42).
    def __init__(self, app, name, steps):
        app.builder = self
        self.app, self.name = app, name
        self.steps, self.hist = json.loads(json.dumps(steps)), []
        self.hw, self.rect, self.ov, self.pn = app.active, None, None, None
        self.sel = self.arm = self.run_i = self.pstart = self.dragging = None
        self.hits, self.alive, self.shown, self.hidden = [], True, True, False
        self.dirty = self.running = self.moved = False
        self.job, self.poff = None, (0, 0)
        fg = user32.GetForegroundWindow()
        self.mk_overlay(); self.mk_panel()
        for w in (self.ov, self.pn): w.update_idletasks(); no_activate(w)
        if fg and user32.GetForegroundWindow() != fg: user32.SetForegroundWindow(fg)     # creating a window must not steal focus
        self.refresh(); self.follow()

    # Runs a callback and logs instead of raising: Tk swallows errors of event handlers silently (added v42).
    def safe(self, fn, *a):
        try: fn(*a)
        except Exception as ex: self.app.log(f"Builder error: {str(ex)[:80]}", "warn")

    # Client rectangle of the target window in screen pixels (x, y, w, h), or None when it is gone (added v42).
    def measure(self):
        if not self.hw or not user32.IsWindow(self.hw): return None
        w, h = client_size(self.hw); x, y = client_origin(self.hw); return x, y, w, h

    # Creates the see-through, semi-transparent canvas window exactly over the target's client area (added v42).
    def mk_overlay(self):
        x, y, w, h = self.rect = self.measure()
        ov = self.ov = tk.Toplevel(self.app); ov.overrideredirect(True); ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.65); ov.attributes("-transparentcolor", self.KEY); ov.configure(bg=self.KEY)
        ov.geometry(f"{w}x{h}+{x}+{y}")
        cv = self.cv = tk.Canvas(ov, bg=self.KEY, highlightthickness=0, bd=0); cv.pack(fill="both", expand=True)
        for ev, fn in (("<ButtonPress-1>", self.c_down), ("<ButtonPress-3>", self.c_down), ("<B1-Motion>", self.c_move),
                       ("<ButtonRelease-1>", self.c_up), ("<ButtonRelease-3>", self.c_up)):
            cv.bind(ev, lambda e, f=fn: self.safe(f, e))

    # Small dark button made from a label (works in a window that never gets focus); .on = highlighted state (added v42).
    def tb(self, parent, text, cmd, pad=8):
        b = tk.Label(parent, text=text, bg=BTN, fg=TXT, padx=pad, pady=4, cursor="hand2", font=("Segoe UI Semibold", 10)); b.on = False
        b.bind("<Button-1>", lambda e: self.safe(cmd))
        b.bind("<Enter>", lambda e: b.configure(bg=BTN_H)); b.bind("<Leave>", lambda e: b.configure(bg="#3b8ee8" if b.on else BTN))
        return b

    # Switches a tb button's highlight on or off (added v42).
    def lit(self, b, on): b.on = on; b.configure(bg="#3b8ee8" if on else BTN)

    # Creates the floating control panel: title bar, slot row, step page (list + [+] [-] ...), slot page, test / mode row (added v42).
    def mk_panel(self):
        x, y, w, h = self.rect
        pn = self.pn = tk.Toplevel(self.app); pn.overrideredirect(True); pn.attributes("-topmost", True); pn.attributes("-alpha", 0.96)
        pn.configure(bg=CARD, highlightthickness=1, highlightbackground=BTN_H); pn.geometry(f"+{max(0, x + w - 350)}+{y + 12}")
        head = tk.Frame(pn, bg="#000000"); head.pack(fill="x")
        self.title = tk.Label(head, text="", bg="#000000", fg=TXT, font=("Segoe UI Semibold", 11), padx=10, pady=6, cursor="fleur", anchor="w")
        self.title.pack(side="left", fill="x", expand=True)
        x_ = tk.Label(head, text="✕", bg="#000000", fg=TXT, font=("Segoe UI Semibold", 11), padx=10, pady=6, cursor="hand2")
        x_.pack(side="right"); x_.bind("<Button-1>", lambda e: self.safe(self.close))
        for wd in (head, self.title): wd.bind("<ButtonPress-1>", self.p_down); wd.bind("<B1-Motion>", self.p_move)
        row = tk.Frame(pn, bg=CARD); row.pack(fill="x", padx=8, pady=(8, 2))
        self.slot_lab = tk.Label(row, text="", bg=CARD, fg=TXT, anchor="w", width=15, font=("Segoe UI Semibold", 10)); self.slot_lab.pack(side="left")
        for t, c in (("Load", self.slots_open), ("Save", self.save), ("Save as", lambda: self.save(True)), ("New", self.new)):
            self.tb(row, t, c, 6).pack(side="left", padx=2)
        body = tk.Frame(pn, bg=CARD); body.pack(fill="x")
        pg = self.pg_steps = tk.Frame(body, bg=CARD); pg.pack(fill="x")
        self.bar = tk.Frame(pg, bg=CARD); self.bar.pack(fill="x", padx=8, pady=(6, 2))
        self.b_add = self.tb(self.bar, "+", self.toggle_add, 14); self.b_add.pack(side="left", padx=(0, 2))
        for t, c in (("−", self.remove), ("▲", lambda: self.move(-1)), ("▼", lambda: self.move(1)), ("Undo", self.undo)):
            self.tb(self.bar, t, c, 14 if len(t) == 1 else 10).pack(side="left", padx=2)
        self.add_row, self.add_btns = tk.Frame(pg, bg=CARD), {}
        for k, t in (("click", "Click"), ("hold", "Hold"), ("swipe", "Swipe"), ("key", "Key"), ("wait", "Wait")):
            b = self.tb(self.add_row, t, lambda k=k: self.add(k), 9); b.pack(side="left", padx=2); self.add_btns[k] = b
        self.hint = tk.Label(pg, text=self.HINT, bg=CARD, fg=MUTED, wraplength=320, justify="left", anchor="w", font=("Segoe UI", 9))
        self.hint.pack(fill="x", padx=10, pady=(4, 2))
        lf = tk.Frame(pg, bg=CARD); lf.pack(fill="x", padx=8)
        sb = tk.Scrollbar(lf, orient="vertical"); self.lb = self.mk_list(lf, sb); sb.configure(command=self.lb.yview)
        self.lb.pack(side="left", fill="x", expand=True); sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self.safe(self.on_pick))
        self.prop = tk.Frame(pg, bg=CARD, height=34); self.prop.pack(fill="x", padx=8, pady=(4, 2)); self.prop.pack_propagate(False)
        self.p_lab = tk.Label(self.prop, bg=CARD, fg=TXT, font=("Segoe UI", 10), anchor="w")
        self.p_dec, self.p_inc = self.tb(self.prop, "−", lambda: self.bump(-1), 12), self.tb(self.prop, "+", lambda: self.bump(1), 12)
        self.p_btn = self.tb(self.prop, "", self.prop_btn)
        sp = self.pg_slots = tk.Frame(body, bg=CARD)
        tk.Label(sp, text="Saved macros", bg=CARD, fg=MUTED, anchor="w", font=("Segoe UI", 9)).pack(fill="x", padx=10, pady=(6, 2))
        self.sl = self.mk_list(sp); self.sl.pack(fill="x", padx=8)
        r = tk.Frame(sp, bg=CARD); r.pack(fill="x", padx=8, pady=6)
        for t, c in (("Load", self.slot_load), ("Delete", self.slot_delete), ("Back", self.slots_close)): self.tb(r, t, c).pack(side="left", padx=2)
        ft = tk.Frame(pn, bg=CARD); ft.pack(fill="x", padx=8, pady=(4, 2))
        self.tb(ft, "▶ Test", self.test, 12).pack(side="left", padx=(0, 2)); self.tb(ft, "■ Stop", self.stop, 12).pack(side="left", padx=2)
        f2 = tk.Frame(pn, bg=CARD); f2.pack(fill="x", padx=8, pady=(2, 8))
        self.b_mode = self.tb(f2, "", self.toggle_mode); self.b_mode.pack(side="left", padx=(0, 2))
        self.b_tgt = self.tb(f2, "", self.cycle_target); self.b_tgt.pack(side="left", padx=2)
        self.foot(); pn.update_idletasks(); pn.geometry(f"+{max(0, x + w - pn.winfo_reqwidth() - 12)}+{y + 12}")

    # A dark Listbox that never asks for the keyboard focus (used for the steps and for the saved macros) (added v42).
    def mk_list(self, parent, sb=None):
        return tk.Listbox(parent, height=9, width=38, bg=FIELD, fg=TXT, selectbackground="#3b8ee8", selectforeground="#ffffff", highlightthickness=0,
                          bd=0, activestyle="none", exportselection=False, takefocus=0, font=("Consolas", 10), yscrollcommand=sb.set if sb else None)

    # Title-bar drag of the panel: remembers where inside the panel the press happened (added v42).
    def p_down(self, e): self.poff = (e.x_root - self.pn.winfo_x(), e.y_root - self.pn.winfo_y())

    # Title-bar drag of the panel: moves it with the mouse (added v42).
    def p_move(self, e): self.pn.geometry(f"+{e.x_root - self.poff[0]}+{e.y_root - self.poff[1]}")

    # Updates the 'Input: ...' and 'On: ...' buttons from the Macros-tab settings (added v42).
    def foot(self):
        a = self.app.cfg; t = a["macro_target"]
        self.b_mode.configure(text="Input: Background" if a["macro_bg"] else "Input: Real mouse")
        self.b_tgt.configure(text="On: " + (t if len(t) <= 18 else t[:17] + "…"))

    # Panel button: flips background input for macros (same setting as the checkbox in the Macros tab) (added v42).
    def toggle_mode(self):
        v = not self.app.cfg["macro_bg"]; self.app.cfg["macro_bg"] = v; self.app.v["macro_bg"].set(v); self.foot()

    # Panel button: cycles the 'Run on' target of the Macros tab: focused, all running accounts, or one account (added v42).
    def cycle_target(self):
        a = self.app; vals = ["Focused account", "All running accounts"] + [x["name"] for x in a.cfg["accounts"]]
        cur = a.cfg["macro_target"]; nxt = vals[(vals.index(cur) + 1) % len(vals)] if cur in vals else vals[0]
        a.cfg["macro_target"] = nxt; a.mg.set(nxt); self.foot()

    # Shows a short message under the buttons (added v42).
    def set_hint(self, text): self.hint.configure(text=text)

    # Redraws everything that depends on the steps: list, overlay widgets, property row, slot name, title (added v42).
    def refresh(self):
        self.fill_list(); self.render(); self.props(); self.slot_text()
        who = next((n for n, h in self.app.windows.items() if h == self.hw), "")
        self.title.configure(text=f"Macro builder  -  {who}" if who else "Macro builder")

    # Shows the current slot name (with * when there are unsaved changes) (added v42).
    def slot_text(self): self.slot_lab.configure(text=(self.name or "(unsaved)")[:13] + (" *" if self.dirty else ""))

    # One step as a list line; the number is the step's real position, the same number the widget on screen shows (added v42).
    def describe(self, i):
        st = self.steps[i]; t = st[0]; pct = lambda v: f"{round(v * 100)}%"
        if t == "wait": body = f"Wait {st[1]} ms"
        elif t == "key": body = f"Key {st[1]}"
        elif t == "swipe": body = f"Swipe {st[5]} ms  {pct(st[1])},{pct(st[2])} → {pct(st[3])},{pct(st[4])}"
        elif t == "hold": body = f"Hold {st[3]} ms  {pct(st[1])},{pct(st[2])}" + (" R" if st[4] == "right" else "")
        else: body = f"Click {pct(st[1])},{pct(st[2])}" + (" R" if st[3] == "right" else "")
        return f"{i + 1:>3}  {body}"

    # Refills the step list and keeps the selection (added v42).
    def fill_list(self):
        self.lb.delete(0, "end")
        for i in range(len(self.steps)): self.lb.insert("end", self.describe(i))
        if self.sel is not None and self.sel < len(self.steps): self.lb.select_set(self.sel); self.lb.see(self.sel)

    # Rewrites one list line while a widget is being dragged (added v42).
    def lb_update(self, i):
        self.lb.delete(i); self.lb.insert(i, self.describe(i)); self.lb.select_set(i)

    # List click: selects that step (its widget gets a white outline) (added v42).
    def on_pick(self):
        s = self.lb.curselection(); self.sel = s[0] if s else None; self.render(); self.props()

    # Selects a step from the screen widgets and mirrors it in the list (added v42).
    def select(self, i):
        self.sel = i; self.lb.selection_clear(0, "end")
        if i is not None: self.lb.select_set(i); self.lb.see(i)
        self.render(); self.props()

    # Draws the numbered widgets: circle = click, ringed circle = hold, circle + line + small end circle = swipe; white outline = selected
    # or currently running; red R = right button. While a placement tool is armed the whole area is tinted so clicks land on it (added v42).
    def render(self):
        if not self.rect: return
        cv, (x, y, w, h), R = self.cv, self.rect, self.R
        cv.delete("all"); self.hits = []
        if self.arm:
            cv.create_rectangle(0, 0, w, h, fill="#0b1020", outline="#3b8ee8", width=4)
            cv.create_text(w // 2, 26, fill="#ffffff", font=("Segoe UI Semibold", 13),
                           text=f"Click{' and drag' if self.arm == 'swipe' else ''} on the game to place a {self.arm}  (press its button again to stop)")
        for i, st in enumerate(self.steps):
            t = st[0]
            if t not in self.COL: continue
            px, py, col = st[1] * w, st[2] * h, self.COL[t]
            hot = i == self.sel or i == self.run_i
            edge = "#ffffff" if hot else "#cfe6ff"
            if t == "swipe":
                qx, qy = st[3] * w, st[4] * h
                cv.create_line(px, py, qx, qy, fill=col, width=8, capstyle="round")
                cv.create_oval(qx - 11, qy - 11, qx + 11, qy + 11, fill=col, outline=edge, width=4 if hot else 2)
                self.hits.append((i, "b", qx, qy, 14))
            cv.create_oval(px - R, py - R, px + R, py + R, fill=col, outline=edge, width=5 if hot else 2)
            if t == "hold": cv.create_oval(px - R + 7, py - R + 7, px + R - 7, py + R - 7, outline="#ffffff", width=2)
            cv.create_text(px, py, text=str(i + 1), fill="#ffffff", font=("Segoe UI Semibold", 13))
            if t != "swipe" and st[-1] == "right": cv.create_text(px + R - 2, py - R + 2, text="R", fill="#ff6b6b", font=("Segoe UI Semibold", 11))
            self.hits.append((i, "a", px, py, R))

    # Remembers the steps for Undo (the last 50 states) and marks the macro as changed (added v42).
    def push(self):
        self.hist.append(json.dumps(self.steps)); del self.hist[:-50]; self.dirty = True; self.slot_text()

    # Undo button: goes back to the previous state of the step list (added v42).
    def undo(self):
        if not self.hist: return self.set_hint("Nothing to undo")
        self.steps = json.loads(self.hist.pop())
        if self.sel is not None and self.sel >= len(self.steps): self.sel = None
        self.refresh()

    # Inserts a step after the selected one (or at the end), selects it and redraws (added v42).
    def insert(self, step):
        if len(self.steps) >= 500: return self.set_hint("A macro can have at most 500 steps.")
        self.push(); i = self.sel + 1 if self.sel is not None else len(self.steps)
        self.steps.insert(i, step); self.sel = i; self.refresh()

    # [+] button: shows or hides the row with the step types (hiding also stops placing) (added v42).
    def toggle_add(self):
        if self.add_row.winfo_ismapped(): self.add_row.pack_forget(); self.arm = None; self.lit(self.b_add, False)
        else: self.add_row.pack(fill="x", padx=8, pady=2, after=self.bar); self.lit(self.b_add, True)
        self.lit_add(); self.render()

    # Highlights the armed step type's button (added v42).
    def lit_add(self):
        for k, b in self.add_btns.items(): self.lit(b, k == self.arm)
        self.set_hint(f"Click on the game to place a {self.arm}. Placed steps go after the selected one." if self.arm else self.HINT)

    # Step type button: click / hold / swipe arm the placement tool (press again to stop), key asks for the key or combo,
    # wait adds a 500 ms pause (added v42).
    def add(self, kind):
        if kind == "wait": return self.insert(["wait", 500])
        if kind == "key":
            combo = self.prompt(self.app.ask, "Key or key combo", "Key or combo to press, e.g. space, f5 or ctrl+shift+a:")
            if combo is None: return
            combo = combo.strip().lower()
            if not parse_combo(combo): return self.prompt(self.app.note, "Key", "That is not a valid key or combo. Use names like space, enter, f5, a, "
                                                                                 "or combos like ctrl+shift+a (modifiers: ctrl, shift, alt, win).")
            return self.insert(["key", combo])
        self.arm = None if self.arm == kind else kind
        self.lit_add(); self.render()

    # [-] button: removes the selected step, or the last one when nothing is selected (added v42).
    def remove(self, i=None):
        i = self.sel if i is None else i
        if i is None: i = len(self.steps) - 1
        if not 0 <= i < len(self.steps): return
        self.push(); del self.steps[i]
        self.sel = min(i, len(self.steps) - 1) if self.steps else None
        self.refresh()

    # Up / down buttons: moves the selected step one place, so the numbers on screen change with the order (added v42).
    def move(self, d):
        i = self.sel
        if i is None or not 0 <= i + d < len(self.steps): return
        self.push(); self.steps[i], self.steps[i + d] = self.steps[i + d], self.steps[i]; self.sel = i + d; self.refresh()

    # Property row: label of the selected step plus the buttons that edit it (time -/+, left/right button, change key) (added v42).
    def props(self):
        for wd in (self.p_lab, self.p_dec, self.p_inc, self.p_btn): wd.pack_forget()
        i = self.sel
        if i is None or i >= len(self.steps):
            self.p_lab.configure(text="Select a step to edit it"); self.p_lab.pack(side="left", padx=2); return
        st = self.steps[i]; t = st[0]
        self.p_lab.configure(text=f"Wait {st[1]} ms" if t == "wait" else f"Hold {st[3]} ms" if t == "hold" else f"Swipe {st[5]} ms" if t == "swipe"
                             else f"Key {st[1]}" if t == "key" else "Click")
        self.p_lab.pack(side="left", padx=(2, 6))
        if t in ("wait", "hold", "swipe"): self.p_dec.pack(side="left", padx=2); self.p_inc.pack(side="left", padx=2)
        if t in ("click", "hold"): self.p_btn.configure(text="Right-click" if st[-1] == "right" else "Left-click"); self.p_btn.pack(side="left", padx=(8, 2))
        elif t == "key": self.p_btn.configure(text="Change"); self.p_btn.pack(side="left", padx=(8, 2))

    # -/+ in the property row: changes the selected step's time; the increment grows with the value (added v42).
    def bump(self, d):
        i = self.sel
        if i is None or i >= len(self.steps): return
        st = self.steps[i]; k = {"wait": 1, "hold": 3, "swipe": 5}.get(st[0])
        if k is None: return
        v = st[k]; step = 50 if v < 500 else 100 if v < 2000 else 500 if v < 10000 else 1000
        lo, hi = {"wait": (0, 600000), "hold": (100, 60000), "swipe": (100, 10000)}[st[0]]
        new = min(hi, max(lo, v + d * step))
        if new != v: self.push(); st[k] = new; self.lb_update(i); self.props()

    # Property row button: toggles left / right click, or changes the key of a key step (added v42).
    def prop_btn(self):
        i = self.sel
        if i is None or i >= len(self.steps): return
        st = self.steps[i]
        if st[0] in ("click", "hold"): self.push(); st[-1] = "left" if st[-1] == "right" else "right"; self.refresh()
        elif st[0] == "key":
            combo = self.prompt(self.app.ask, "Key or key combo", "Key or combo to press:", default=st[1])
            if combo and parse_combo(combo.strip().lower()): self.push(); st[1] = combo.strip().lower(); self.refresh()

    # Mouse press on the overlay: on a widget = select it and start dragging (right button = delete it); on empty tinted area while a
    # placement tool is armed = start of a placement (added v42).
    def c_down(self, e):
        right = e.num == 3
        hit = next((h for h in reversed(self.hits) if (e.x - h[2]) ** 2 + (e.y - h[3]) ** 2 <= h[4] ** 2), None)
        if hit:
            if right: return self.remove(hit[0])
            self.dragging, self.moved = hit, False; return self.select(hit[0])
        if self.arm: self.pstart = (e.x, e.y, "right" if right else "left")

    # Mouse move on the overlay: drags the widget (stores fractions of the window live) or shows the swipe rubber band (added v42).
    def c_move(self, e):
        w, h = self.rect[2], self.rect[3]
        if self.dragging:
            if not self.moved: self.push(); self.moved = True
            i, part = self.dragging[0], self.dragging[1]; st = self.steps[i]
            fx, fy = round(min(max(e.x / w, 0), 1), 4), round(min(max(e.y / h, 0), 1), 4)
            if part == "b": st[3], st[4] = fx, fy
            else: st[1], st[2] = fx, fy
            self.render(); self.lb_update(i)
        elif self.arm == "swipe" and self.pstart:
            self.cv.delete("rb"); self.cv.create_line(self.pstart[0], self.pstart[1], e.x, e.y, fill="#5fd38d", width=8, capstyle="round", tags="rb")

    # Mouse release on the overlay: ends a drag, or turns the placement gesture into a click / hold / swipe step (added v42).
    def c_up(self, e):
        if self.dragging: self.dragging = None; return
        if not (self.arm and self.pstart): return
        x0, y0, btn = self.pstart; self.pstart = None; self.cv.delete("rb")
        w, h = self.rect[2], self.rect[3]; f = lambda v, m: round(min(max(v / m, 0), 1), 4)
        if self.arm == "swipe":
            if (e.x - x0) ** 2 + (e.y - y0) ** 2 < 196: return self.set_hint("Swipe: press at the start and drag to the end")
            self.insert(["swipe", f(x0, w), f(y0, h), f(e.x, w), f(e.y, h), 400])
        elif self.arm == "hold": self.insert(["hold", f(x0, w), f(y0, h), 1000, btn])
        else: self.insert(["click", f(x0, w), f(y0, h), btn])

    # Runs an in-app prompt (ask / confirm / note) from the builder: both floating windows are hidden meanwhile and the manager gets the
    # keyboard, because the prompt is drawn inside the manager window (added v42).
    def prompt(self, fn, *a, **k):
        self.hidden = True; self.vis(False)
        try:
            user32.SetForegroundWindow(self.app.top_hwnd())
            return fn(*a, **k)
        finally:
            self.hidden = False

    # Shows or hides both windows without activating them (ShowWindow SW_SHOWNOACTIVATE / SW_HIDE) (added v42).
    def vis(self, on):
        self.shown = on
        for w in (self.ov, self.pn):
            if w is not None: user32.ShowWindow(user32.GetAncestor(w.winfo_id(), 2), 4 if on else 0)

    # Re-shows both windows on top of everything, without activating them (builder button pressed again) (added v42).
    def front(self):
        self.hidden = False; self.vis(True)
        for w in (self.ov, self.pn): user32.SetWindowPos(user32.GetAncestor(w.winfo_id(), 2), -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # Every 150 ms: follows the focused account, keeps the overlay exactly over its client area, hides both windows while the Viewer is
    # not showing / the manager is minimized / a prompt is open, and re-shows them afterwards (added v42).
    def follow(self):
        if not self.alive: return
        app = self.app
        try:
            live = app.live()
            if app.active in live and app.active != self.hw and not self.running:
                self.hw, self.rect = app.active, None; self.refresh()
            m = self.measure() if self.hw in live else None
            ok = bool(m and m[2] > 40 and m[3] > 40 and not self.hidden and not app.modal and app.state() != "iconic"
                      and app.tv.get() == "Viewer" and user32.IsWindowVisible(self.hw))
            if ok:
                if m != self.rect: self.rect = m; self.ov.geometry(f"{m[2]}x{m[3]}+{m[0]}+{m[1]}"); self.render()
                if not self.shown: self.vis(True)
            elif self.shown: self.vis(False)
        except Exception as ex: app.log(f"Builder error: {str(ex)[:80]}", "warn")
        self.job = app.after(150, self.follow)

    # Save / Save as: stores the steps under a name in the same macro list as the Macros tab (asks for the name in-app) (added v42).
    def save(self, as_new=False):
        a = self.app
        if not self.steps: return self.set_hint("Nothing to save yet - add some steps")
        name = self.name
        if as_new or not name:
            name = self.prompt(a.ask, "Save macro", "Name for this macro slot:", default=self.name or f"Macro {len(a.cfg['macros']) + 1}")
            if not name or not name.strip(): return
            name = name.strip()[:40]
            if name in a.cfg["macros"] and name != self.name and self.prompt(
                    a.confirm, "Replace macro", f"A macro named '{name}' already exists. Replace it?", [("Replace", True), ("Cancel", None)]) is not True: return
        a.cfg["macros"][name] = json.loads(json.dumps(self.steps)); a.cfg["macro_sel"] = name
        self.name, self.dirty = name, False; a.macro_refresh(); self.slot_text(); self.set_hint(f"Saved '{name}' ({len(self.steps)} steps)")
        a.log(f"Macro '{name}' saved from the visual builder ({len(self.steps)} steps)", "ok")

    # New button: empties the editor (Undo brings the old steps back) (added v42).
    def new(self):
        self.push(); self.steps, self.name, self.sel, self.arm = [], "", None, None; self.lit_add(); self.refresh()

    # Load button: shows the list of saved macro slots instead of the step page (added v42).
    def slots_open(self):
        names = list(self.app.cfg["macros"])
        if not names: return self.set_hint("No saved macros yet - build one and press Save")
        self.sl.delete(0, "end")
        for n in names: self.sl.insert("end", n)
        if self.name in names: self.sl.select_set(names.index(self.name))
        self.pg_steps.pack_forget(); self.pg_slots.pack(fill="x")

    # Back button of the slot list (added v42).
    def slots_close(self): self.pg_slots.pack_forget(); self.pg_steps.pack(fill="x")

    # Load in the slot list: replaces the steps with that macro and makes it the selected macro of the Macros tab (added v42).
    def slot_load(self):
        s = self.sl.curselection()
        if not s: return
        name = self.sl.get(s[0]); steps = self.app.cfg["macros"].get(name)
        if steps is None: return
        self.push(); self.steps = json.loads(json.dumps(steps)); self.name, self.dirty, self.sel, self.arm = name, False, None, None
        self.app.cfg["macro_sel"] = name; self.app.macro_refresh(); self.slots_close(); self.lit_add(); self.refresh()

    # Delete in the slot list: removes that saved macro after a confirmation (the steps in the editor stay) (added v42).
    def slot_delete(self):
        s = self.sl.curselection()
        if not s: return
        name, a = self.sl.get(s[0]), self.app
        if self.prompt(a.confirm, "Delete macro", f"Delete the macro '{name}'?", [("Delete", True), ("Cancel", None)]) is not True: return
        a.cfg["macros"].pop(name, None); a.cfg["macro_sel"] = next(iter(a.cfg["macros"]), ""); a.macro_refresh()
        if name == self.name: self.name = ""; self.dirty = True
        self.slot_text(); self.slots_close() if not a.cfg["macros"] else self.slots_open()

    # Test button: runs the steps on the accounts chosen by 'On:' using the 'Input:' mode. Background input keeps the overlay visible and
    # lights up each step as it runs; real-mouse input hides the overlay (it would catch the clicks) until the run ends (added v42).
    def test(self):
        a = self.app
        if not self.steps: return self.set_hint("Nothing to test - add some steps")
        if self.running: return
        self.arm = None; self.lit_add(); a.collect(); bg = a.cfg["macro_bg"]
        if not bg: self.hidden = True; self.vis(False)
        self.running = True; self.render()
        if not a.macro_start(json.loads(json.dumps(self.steps)), None, self.name or "builder test", self.test_done, self.on_run_step if bg else None):
            self.test_done()

    # Called from the worker thread before each step: hands the number over to the main thread (added v42).
    def on_run_step(self, i): self.app.after(0, lambda: self.set_run(i))

    # Main thread: marks the running step on screen and in the list (added v42).
    def set_run(self, i):
        if self.alive and self.running: self.run_i = i; self.render(); self.lb.see(i)

    # The test run finished or failed to start: shows the overlay again (added v42).
    def test_done(self):
        self.running, self.run_i, self.hidden = False, None, False
        if self.alive: self.render()

    # Stop button: stops a running test (added v42).
    def stop(self):
        if self.running: self.app.macro_abort()

    # Closes the builder; asks first when there are unsaved changes (added v42).
    def close(self, ask=True):
        if ask and self.dirty and self.steps:
            r = self.prompt(self.app.confirm, "Macro builder", "Save the changes before closing?", [("Save", True), ("Discard", False), ("Cancel", None)])
            if r is None: return
            if r:
                self.save()
                if self.dirty: return                          # the name prompt was cancelled: stay open
        if self.running: self.app.macro_abort()
        self.alive = False
        if self.job:
            try: self.app.after_cancel(self.job)
            except Exception: pass
        self.app.builder = None
        for w in (self.ov, self.pn):
            try:
                if w is not None: w.destroy()
            except Exception: pass

def grid_plan(n, W, H):
    """Column count that gives the biggest 16:9 windows fitting W x H -> (cols, cell_w, cell_h, w, h)."""
    best = None
    for cols in range(1, n + 1):
        rows = -(-n // cols); cw, ch = W // cols, H // rows
        w = min(cw, int(ch * 16 / 9))
        if best is None or w > best[3]: best = (cols, cw, ch, w, int(w * 9 / 16))
    return best

class Badge(tk.Frame):
    """Username tag drawn inside the window's own tile and kept above the Roblox child window.
    Click = focus that account, press-and-drag onto another tile = reorder, onto the Focused tile = switch with it."""
    # Builds the username tag drawn on each tile: status dot + name, with click / drag / drop callbacks (v28 or earlier).
    def __init__(self, cell, text, on_click, on_drag, on_drop):
        super().__init__(cell, bg="#000000", highlightthickness=0, bd=0)
        self.dot = tk.Label(self, text="●", bg="#000000", fg=GREEN, font=("Segoe UI", 8))
        self.dot.pack(side="left", padx=(7, 2))
        name = tk.Label(self, text=text, bg="#000000", fg="#ffffff", font=("Segoe UI Semibold", 10))
        name.pack(side="left", padx=(0, 9), pady=2)
        self.cbs, self.press, self.moved = (on_click, on_drag, on_drop), None, False
        for w in (self, self.dot, name):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", self._down); w.bind("<B1-Motion>", self._move); w.bind("<ButtonRelease-1>", self._up)
        self.place(x=4, y=4)

    # Mouse press on a tag: remembers where the press started.
    def _down(self, e): self.press, self.moved = (e.x_root, e.y_root), False

    # Mouse move on a tag: after 8 px of movement it counts as a drag and calls the drag callback.
    def _move(self, e):
        if self.press and (self.moved or abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1]) > 8):
            self.moved = True; self.cbs[1](e)

    # Mouse release on a tag: a plain click focuses the account, a drag ends with the drop callback.
    def _up(self, e):
        if self.press: self.cbs[2](e) if self.moved else self.cbs[0]()
        self.press, self.moved = None, False

    # Changes the colour of the tag's status dot only when it differs (avoids redraws).
    def set_color(self, c):
        if self.dot.cget("fg") != c: self.dot.configure(fg=c)

    # Keeps the tag on top of the game window inside its tile.
    def raise_above(self, cell_hwnd):
        bh = self.winfo_id()
        if user32.GetWindow(cell_hwnd, 5) != bh:                   # GW_CHILD = current top child
            user32.SetWindowPos(bh, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

# ======================= App =======================
ctk.set_appearance_mode("dark")

# Main application window: all UI, launching, viewer tiling and the monitoring threads (v28 or earlier); extended through v37.
class App(ctk.CTk):
    modal = False                    # True while an in-app prompt is open (docked game windows are hidden)
    cancel = None                    # closes that prompt (same as its last button)

    # Loads config, creates all state dictionaries and the window, builds the UI and starts the background threads (v28 or earlier).
    def __init__(self):
        super().__init__()
        global BORDER, RADIUS
        sc = getattr(self, "_get_window_scaling", lambda: 1.0)()          # display scale (1.0 / 1.25 / 1.5 ...)
        BORDER, RADIUS = max(2, round(2 * sc)), round(10 * sc)             # tile border follows the scale
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()       # real pixels (DPI-aware process)
        w = int(min(0.9 * sw / sc, max(920, 0.6 * sw / sc))); h = int(min(0.9 * sh / sc, max(880, 0.8 * sh / sc)))
        self.title("Better RAM"); self.geometry(f"{w}x{h}"); self.minsize(min(1100, w), min(700, h))
        self.configure(fg_color=BG)
        self.after(300, self.set_icon)                      # customtkinter sets its own icon at ~200 ms; ours goes on top
        self.protocol("WM_DELETE_WINDOW", self.on_exit)
        self.mutex = kernel32.CreateMutexW(None, True, "ROBLOX_singletonMutex")   # lets several Roblox clients run
        saved = json.load(open(DATA)) if os.path.exists(DATA) else {}
        self.cfg = {**json.loads(json.dumps(DEFAULTS)), **{k: v for k, v in saved.items() if k in DEFAULTS}}
        self._saved = ""
        # per-account runtime state
        self.windows = {}                                   # account name -> hwnd
        self.crashed, self.hung, self.missing, self.procs = {}, {}, {}, {}
        self.cookie_ok, self.prev_state = {}, {}
        self.last_use, self.crash_use, self.apid, self.launching = {}, {}, {}, set()               # last seen (cpu %, ram MB) per account / frozen at crash time
        self.disconnected, self.offline, self.rejoin_hist = set(), {}, {}
        self.started, self.launch_info = {}, {}             # launch time / (place, job) per account
        # viewer state
        self.cells, self.badges, self.fixes, self.drag = {}, {}, {}, None
        self.ph = self.ph_name = None                       # "Focused" placeholder tile
        self.afk_sel = {}
        self.sizing, self.ready, self._size, self._rz = False, False, None, None
        self.hk_thread, self.hk_tid = None, 0
        self.active = self.maxed = None
        self.dock_local = self.last_dock = self._relayout = None
        self.dock_fast_until, self.hires, self._td, self._winpos = 0.0, False, None, None
        self.press, self.was_down, self.app_fg_top, self._tab, self._dirty, self.dock_fix = None, False, False, "", False, 0
        self._lay_job = None                                # pending live layout commit (added v39)
        self.anim, self.flashes, self._anim_job = {}, {}, None   # running tile slides / border flashes / shared ticker (added v40)
        self.rec, self.macro_on, self.m_pt, self.m_held, self.m_kd, self._m_job = None, False, None, 0, [], None   # recorder / macro run state (added v41)
        self.dc_seen = {}                                   # Discord alert text -> last time sent (added v41)
        self.builder, self.bld_wait, self.bg_job, self.macro_cb = None, False, None, None   # visual builder / opening / running background job / macro-end callback (added v42)
        # background work
        self.launch_jobs, self.launch_lock = 0, threading.Lock()
        self.afk_busy, self.afk_next = False, time.time() + 480
        self.afk_hw = self.afk_pt = None; self.afk_pressed = False
        self.sel, self.rows, self.v = {}, {}, {}
        self.latest_ver, self.pid_build, self.out_logged = None, {}, set()     # newest Roblox build, pid -> running build, warned pids
        self.vram, self.vram_ok, self.io_prev = {}, None, {}
        self.gpu, self.gpu_total, self.gpu_ok = {}, 0.0, None      # pid -> GPU %, system GPU %, counters available?
        self.build(); self.refresh(); self.macro_init()
        self.bind("<Configure>", self.on_resize, add="+"); self.bind("<Configure>", self.on_move, add="+"); self.after(1500, lambda: setattr(self, "ready", True))
        for delay, fn in ((40, self.poll), (1000, self.sync), (2000, self.dash), (600, self.badge_loop),
                          (1500, self.heal_loop), (100, self.track_dock)):
            self.after(delay, fn)
        for fn in (self.maintenance, self.watch_loop, self.gpu_loop, self.version_loop):
            threading.Thread(target=fn, daemon=True).start()
        if self.cfg["auto_update"]: self.after(4000, lambda: threading.Thread(target=self.check_update, daemon=True).start())
        if self.cfg["hotkeys"]: self.hotkeys(True)
        self.log("Better RAM started")

    # Sets the window icon (drawn in code, see app_icon) (v28 or earlier).
    def set_icon(self):
        try: self.iconbitmap(app_icon())
        except Exception: pass

    @property
    # True while launching or Anti-AFK is moving windows; clicks are ignored meanwhile (v28 or earlier).
    def busy(self):                                         # launching / anti-AFK moves windows: ignore clicks meanwhile
        return self.launch_jobs > 0 or self.afk_busy

    # ---------- UI helpers ----------
    def btn(self, parent, text, cmd, primary=False, w=120, h=38):
        return ctk.CTkButton(parent, text=text, command=cmd, width=w, height=h, corner_radius=12,
                             fg_color=TXT if primary else BTN, hover_color="#ffffff" if primary else BTN_H,
                             text_color=BG if primary else TXT, font=("Segoe UI Semibold", 13))

    # Creates a rounded settings card, optionally with a title (v28 or earlier).
    def card(self, parent, title=None):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=18); c.pack(fill="x", padx=3, pady=6)
        if title: ctk.CTkLabel(c, text=title, font=("Segoe UI Semibold", 15), text_color=TXT).pack(anchor="w", padx=18, pady=(14, 4))
        return c

    # Creates one horizontal row inside a card (v28 or earlier).
    def line(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=14, pady=6); return f

    # Adds a label + text entry bound to a config key (v28 or earlier).
    def entry(self, f, label, key, w=70):
        ctk.CTkLabel(f, text=label, text_color=MUTED).pack(side="left")
        v = tk.StringVar(value=str(self.cfg[key])); self.v[key] = v
        ctk.CTkEntry(f, textvariable=v, width=w, height=34, corner_radius=10, fg_color=FIELD,
                     border_width=0).pack(side="left", padx=(8, 22))

    # Adds a checkbox bound to a config key (v28 or earlier).
    def check(self, f, label, key, cmd=None):
        v = tk.BooleanVar(value=self.cfg[key]); self.v[key] = v
        ctk.CTkCheckBox(f, text=label, variable=v, onvalue=True, offvalue=False, corner_radius=7, command=cmd,
                        fg_color=TXT, hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H,
                        text_color=TXT).pack(side="left", padx=(0, 24))

    def confirm(self, title, text, buttons, field=None, secret=False):
        """In-app prompt drawn over the whole window. Docked game windows are hidden meanwhile so nothing can cover it.
        buttons = [(label, value), ...]; the first is the primary action, the last one also answers Escape.
        field = initial text adds an entry (the primary button then returns its text, the others None);
        The X in the top-right corner (and the app's own close button) answers like the last button. Returns the clicked value."""
        if self.modal: return None
        self.modal = True
        hidden = [h for h in DOCKED if user32.IsWindow(h)]
        for h in hidden: user32.ShowWindow(h, 0)
        ov = ctk.CTkFrame(self, fg_color=BG, corner_radius=0); ov.place(x=0, y=0, relwidth=1, relheight=1); ov.lift()
        card = ctk.CTkFrame(ov, fg_color=CARD, corner_radius=18); card.place(relx=0.5, rely=0.4, anchor="center")
        ctk.CTkLabel(card, text=title, font=("Segoe UI Semibold", 17), text_color=TXT).pack(padx=34, pady=(26, 6))
        ctk.CTkLabel(card, text=text, justify="left", text_color=MUTED, wraplength=420).pack(padx=34, pady=(0, 18))
        e = None
        if field is not None:
            e = ctk.CTkEntry(card, width=400, height=38, corner_radius=10, fg_color=FIELD, border_width=0, show="•" if secret else "")
            e.insert(0, field); e.pack(padx=34, pady=(0, 18))
        out = tk.StringVar(); res = {}
        # Button handler of the in-app prompt: stores which button (or the typed text) was chosen and closes the prompt.
        def pick(i):
            res["v"] = e.get() if e is not None and i == 0 else buttons[i][1]; out.set("x")
        row = ctk.CTkFrame(card, fg_color="transparent"); row.pack(pady=(0, 26))
        for i, (label, _) in enumerate(buttons):
            self.btn(row, label, lambda i=i: pick(i), primary=(i == 0), w=130).pack(side="left", padx=6)
        self.cancel = lambda: pick(len(buttons) - 1)
        ctk.CTkButton(ov, text="✕", width=40, height=40, corner_radius=12, fg_color=BTN, hover_color=BTN_H, text_color=TXT,
                      font=("Segoe UI Semibold", 16), command=self.cancel).place(relx=1, x=-14, y=12, anchor="ne")
        for w in (ov, e):
            if w is not None: w.bind("<Escape>", lambda _: pick(len(buttons) - 1))
        if e is not None: e.bind("<Return>", lambda _: pick(0)); e.focus_set()
        else: ov.focus_set()
        self.wait_variable(out)
        ov.destroy(); self.modal = False; self.cancel = None
        for h in hidden:
            if user32.IsWindow(h): user32.ShowWindow(h, 4)       # SW_SHOWNOACTIVATE
        self.after(50, self.retile); self.after(150, self.verify_layout)
        return res["v"]

    # In-app message box with one OK button (never a native dialog) (v28 or earlier).
    def note(self, title, text): self.confirm(title, text, [("OK", True)])

    def ask(self, title, prompt, secret=False, default=""):
        """Text entry; returns the text ("" is allowed) or None when cancelled."""
        return self.confirm(title, prompt, [("OK", True), ("Cancel", None)], field=default, secret=secret)

    # ---------- UI ----------
    def build(self):
        tv = self.tv = ctk.CTkTabview(self, fg_color=BG, corner_radius=18, command=lambda: self.after(10, self.kick_track), segmented_button_fg_color=CARD,
                                      segmented_button_selected_color=BTN_H, segmented_button_selected_hover_color=BTN_H,
                                      segmented_button_unselected_color=CARD, segmented_button_unselected_hover_color=BTN)
        tv.pack(fill="both", expand=True, padx=6, pady=8)
        dash, view, mac, sett = tv.add("Dashboard"), tv.add("Viewer"), tv.add("Macros"), tv.add("Settings")

        # --- viewer ---
        top = ctk.CTkFrame(view, fg_color="transparent"); top.pack(fill="x", padx=6, pady=(4, 8))
        self.active_label = ctk.CTkLabel(top, text="Focused: -", font=("Segoe UI Semibold", 14), text_color=TXT)
        self.active_label.pack(side="left", padx=8)
        self.fs = self.btn(top, "Fullscreen", self.fullscreen, w=130, h=32); self.fs.pack(side="right", padx=6)
        sb = ctk.CTkFrame(view, fg_color="transparent", height=124); sb.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        sb.pack_propagate(False)
        lc = ctk.CTkFrame(sb, fg_color="transparent"); lc.pack(side="left", fill="y", padx=(0, 10))      # left corner, top to bottom
        ctk.CTkButton(lc, text="Anti-AFK now", command=lambda: self.start_afk(True), width=150, height=32, corner_radius=10,
                      fg_color=TXT, hover_color="#ffffff", text_color=BG,
                      font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(4, 6))
        for label, key in (("Anti-AFK", "afk"), ("Connection watch", "watch")):
            row = ctk.CTkFrame(lc, fg_color="transparent"); row.pack(anchor="w", pady=3)
            self.check(row, label, key)
        rc = ctk.CTkFrame(sb, fg_color="transparent"); rc.pack(side="left", fill="both", expand=True)      # rest of the width
        hd = ctk.CTkFrame(rc, fg_color="transparent"); hd.pack(fill="x", pady=(0, 4))
        self.afk_label = ctk.CTkLabel(hd, text="AFK on:", text_color=MUTED); self.afk_label.pack(side="left", padx=(4, 10))
        self.btn(hd, "All", lambda: self.afk_all(True), w=50, h=26).pack(side="left", padx=(0, 6))
        self.btn(hd, "None", lambda: self.afk_all(False), w=56, h=26).pack(side="left")
        self.afk_list = ctk.CTkScrollableFrame(rc, height=60, fg_color=FIELD, corner_radius=8)
        self.afk_list.pack(fill="both", expand=True)
        self.afk_cells, self.afk_cols, self.afk_rc, self.afk_sb_on = [], 0, rc, True
        self.after(10, self.layout_afk)
        rc.bind("<Configure>", lambda e: self.after(60, self.layout_afk))
        self.stage = tk.Frame(view, bg="#000000", highlightthickness=0)
        self.stage.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.stage.bind("<Configure>", self.on_stage)
        self.empty = tk.Label(self.stage, text="Running instances will be shown here", bg="#000000", fg=MUTED, font=("Segoe UI", 13))
        self.empty.place(relx=0.5, rely=0.5, anchor="center"); self.empty_on = True

        # --- dashboard: left = game + accounts, right = log, bottom = actions ---
        dash.grid_columnconfigure(0, weight=3, uniform="dash"); dash.grid_columnconfigure(1, weight=2, uniform="dash"); dash.grid_rowconfigure(0, weight=1)   # fixed 60/40, whatever the text inside
        left = ctk.CTkFrame(dash, fg_color="transparent"); left.grid(row=0, column=0, sticky="nsew")
        right = ctk.CTkFrame(dash, fg_color="transparent"); right.grid(row=0, column=1, sticky="nsew")
        lb = ctk.CTkFrame(right, fg_color="transparent"); lb.pack(fill="x", padx=3, pady=(6, 6))
        self.btn(lb, "Clear", self.clear_log, w=100).pack(side="left", padx=6)
        self.btn(lb, "Open log file", lambda: os.path.exists(LOG) and os.startfile(LOG), w=140).pack(side="left", padx=6)
        bar = ctk.CTkFrame(right, fg_color="transparent"); bar.pack(side="bottom", fill="x", padx=3, pady=(0, 2))
        self.logbox = ctk.CTkTextbox(right, fg_color=CARD, corner_radius=14, text_color=TXT,
                                     font=("Consolas", 13), wrap="word", state="disabled")
        self.logbox.pack(fill="both", expand=True, padx=3, pady=(0, 6))
        for tag, col in (("ok", GREEN), ("warn", ORANGE), ("bad", RED), ("info", TXT)):
            self.logbox.tag_config(tag, foreground=col)

        g = self.card(left)
        f = ctk.CTkFrame(g, fg_color="transparent"); f.pack(fill="x", padx=12, pady=(10, 4)); f.grid_columnconfigure(1, weight=1)
        self.v["place"] = tk.StringVar(value=self.cfg["place"]); self.v["join_user"] = tk.StringVar(value=self.cfg["join_user"])
        self.mode_btn = ctk.CTkSegmentedButton(f, values=["Game", "User"], command=self.set_join_mode, width=110, height=34,
                                               corner_radius=10, fg_color=FIELD, selected_color=BTN_H, selected_hover_color=BTN_H,
                                               unselected_color=FIELD, unselected_hover_color=BTN, text_color=TXT,
                                               font=("Segoe UI Semibold", 13))
        self.mode_btn.set("User" if self.cfg["join_mode"] == "user" else "Game"); self.mode_btn.grid(row=0, column=0, padx=(0, 6))
        self.e_game = ctk.CTkEntry(f, textvariable=self.v["place"], height=34, corner_radius=10, fg_color=FIELD, border_width=0,
                                   placeholder_text="Game ID or roblox.com/games/... link")
        self.e_user = ctk.CTkEntry(f, textvariable=self.v["join_user"], height=34, corner_radius=10, fg_color=FIELD, border_width=0,
                                   placeholder_text="Roblox username to join")
        self.e_game.grid(row=0, column=1, sticky="ew", padx=(0, 6)); self.e_user.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.btn(f, "Save", self.save_target, w=60, h=34).grid(row=0, column=2, padx=(0, 6))
        self.combo = ctk.CTkComboBox(f, values=[""], width=150, height=34, corner_radius=10, fg_color=FIELD, border_width=0,
                                     button_color=BTN, button_hover_color=BTN_H, dropdown_fg_color=CARD, state="readonly",
                                     command=self.pick_target)
        self.combo.grid(row=0, column=3, padx=(0, 6))
        ctk.CTkButton(f, text="Delete", command=self.del_target, width=64, height=34, corner_radius=12, fg_color="#4a1d24",
                      hover_color="#6b2833", text_color="#ff9a9a", font=("Segoe UI Semibold", 13)).grid(row=0, column=4)
        self.join_box = ctk.CTkFrame(g, fg_color=FIELD, corner_radius=10); self.join_box.pack(fill="x", padx=12, pady=(2, 10))
        self.join_dot = ctk.CTkLabel(self.join_box, text="●", text_color=MUTED, font=("Segoe UI", 14), width=20)
        self.join_dot.pack(side="left", padx=(10, 2), pady=4)
        self.join_lbl = ctk.CTkLabel(self.join_box, text="", anchor="w", justify="left", text_color=TXT,
                                     font=("Segoe UI Semibold", 12), wraplength=480)
        self.join_lbl.pack(side="left", fill="x", expand=True, padx=(2, 10), pady=4)
        for k in ("place", "join_user"): self.v[k].trace_add("write", lambda *_: self.after_idle(self.update_game_info))
        self.refresh_games()

        # --- dashboard: summary, accounts, actions ---
        s = ctk.CTkFrame(left, fg_color=CARD, corner_radius=14); s.pack(fill="x", padx=3, pady=(4, 6))
        self.sum = {}                                        # fixed-width cells: a changing number can never resize the layout
        for i, (k, w) in enumerate((("run", 74), ("frozen", 70), ("disc", 112), ("crashed", 80), ("ram", 92), ("cpu", 66), ("gpu", 70))):
            self.sum[k] = ctk.CTkLabel(s, text="", font=("Segoe UI Semibold", 13), text_color=TXT, anchor="w", width=w)
            self.sum[k].pack(side="left", padx=(14 if i == 0 else 4, 0), pady=12)
        hd = ctk.CTkFrame(left, fg_color="transparent"); hd.pack(fill="x", padx=3, pady=(2, 0))
        self.btn(hd, "Select all", self.sel_all, w=110, h=30).pack(side="left", padx=6)
        self.btn(hd, "Deselect all", self.sel_none, w=120, h=30).pack(side="left", padx=6)
        self.btn(hd, "Refresh status", self.refresh_status, w=130, h=30).pack(side="right", padx=6)
        self.rc_btn = self.btn(hd, "Roll call", self.toggle_compact, w=96, h=30); self.rc_btn.pack(side="right", padx=0)
        self.perf_btn = self.btn(hd, "Performance", self.toggle_perf, w=110, h=30); self.perf_btn.place(relx=0.5, rely=0.5, anchor="center")
        self.style_roll_btn()
        self.list = ctk.CTkScrollableFrame(left, fg_color=CARD, corner_radius=18, height=120)
        self.list.pack(fill="both", expand=True, padx=3, pady=(6, 3))
        bar.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bar, text="Launch selected", command=self.launch, height=40, corner_radius=12,
                      fg_color=TXT, hover_color="#ffffff", text_color=BG,
                      font=("Segoe UI Semibold", 15)).grid(row=0, column=0, columnspan=2, padx=2, pady=(4, 6), sticky="ew")
        grid = ((("Rejoin selected", self.rejoin_selected), ("Close selected", self.close_selected)),
                (("Add account (paste cookie)", self.add), ("Add account via browser", self.add_browser)),
                (("Export accounts", self.export_accounts), ("Import accounts", self.import_accounts)),
                (("Close all", self.close_all), None))
        for r, items in enumerate(grid, 1):
            for c, it in enumerate(items):
                if it:
                    b = self.btn(bar, it[0], it[1], h=32); b.configure(font=("Segoe UI Semibold", 12))
                    b.grid(row=r, column=c, padx=2, pady=3, sticky="ew")
        ctk.CTkButton(bar, text="Delete selected accounts", command=self.remove, height=32, corner_radius=12,
                      fg_color="#4a1d24", hover_color="#6b2833", text_color="#ff9a9a",
                      font=("Segoe UI Semibold", 12)).grid(row=4, column=1, padx=2, pady=3, sticky="ew")

        # --- macros ---
        mc = self.card(mac, "Macro")
        f = self.line(mc)
        ctk.CTkLabel(f, text="Macro", text_color=MUTED).pack(side="left")
        self.mm = ctk.CTkOptionMenu(f, values=["-"], width=200, height=34, corner_radius=10, fg_color=BTN, button_color=BTN_H,
                                    button_hover_color=BTN_H, dropdown_fg_color=CARD, command=self.macro_pick)
        self.mm.pack(side="left", padx=(8, 14))
        for t, cmd in (("Record", self.macro_record), ("New", self.macro_new), ("Save", self.macro_save), ("Delete", self.macro_delete)):
            self.btn(f, t, cmd, w=84, h=34).pack(side="left", padx=3)
        self.btn(f, "Visual builder", self.builder_open, primary=True, w=130, h=34).pack(side="left", padx=(12, 3))
        self.mt = ctk.CTkTextbox(mc, height=240, fg_color=FIELD, corner_radius=10, font=("Consolas", 13), text_color=TXT)
        self.mt.pack(fill="x", padx=14, pady=6)
        f = self.line(mc)
        ctk.CTkLabel(f, text="Run on", text_color=MUTED).pack(side="left")
        self.mg = ctk.CTkOptionMenu(f, values=["Focused account"], width=220, height=34, corner_radius=10, fg_color=BTN, button_color=BTN_H,
                                    button_hover_color=BTN_H, dropdown_fg_color=CARD, command=self.macro_target_pick)
        self.mg.pack(side="left", padx=(8, 22))
        self.check(f, "Background input", "macro_bg")
        self.entry(f, "Repeat", "macro_loops", 50)
        self.btn(f, "Run / stop", self.macro_toggle, primary=True, w=120, h=34).pack(side="left")
        ctk.CTkLabel(mc, wraplength=900, justify="left", text_color=MUTED,
                     text="One step per line; x and y are fractions (0-1) of the game window, so a macro works on any account and window size:  "
                          "click x y [right]  |  hold x y ms [right]  |  swipe x1 y1 x2 y2 ms  |  key ctrl+shift+a  |  wait ms  ('#' starts a comment). "
                          "Record opens a see-through layer over the focused window: click, hold (0.5 s+), drag to swipe, type keys or combos; "
                          "Done saves. Visual builder puts numbered, draggable widgets over the focused window: [+] adds a step and you click or drag "
                          "where it goes, the list sets the order, Save / Load keep named macros. Normal runs use the real mouse and keyboard like "
                          "Anti-AFK, one account after another; with Background input ticked the clicks and keys are posted to the game windows instead "
                          "(no cursor movement, no focus change, all accounts at once). Run / stop or the macro hotkey (Settings) stops a running macro."
                     ).pack(anchor="w", padx=18, pady=(0, 14))

        # --- settings ---
        sc = ctk.CTkScrollableFrame(sett, fg_color=BG); sc.pack(fill="both", expand=True)
        c = self.card(sc, "Layout")
        f = self.line(c); self.entry(f, "Launch delay (s)", "delay", 60)
        f = self.line(c); self.entry(f, "Tile area % of viewer width", "pane", 60)
        self.btn(f, "Apply", lambda: self.apply_layout(pane=True), w=90, h=34).pack(side="left")
        ctk.CTkLabel(f, text="Limits: 20-70 %, used with 2+ instances (one instance fills the viewer)", text_color=MUTED).pack(side="left", padx=12)
        f = self.line(c); self.check(f, "Custom tile size (unfocused window)", "micro")
        self.entry(f, "Width px", "windowWidth", 60); self.entry(f, "Height px", "windowHeight", 60)
        ctk.CTkLabel(f, text="Limits: 40-4000 px", text_color=MUTED).pack(side="left")
        f = self.line(c)
        ctk.CTkLabel(f, text="Presets", text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(f, values=["320x240", "240x180", "200x150", "160x120", "120x90"], width=120, height=34,
                          corner_radius=10, fg_color=BTN, button_color=BTN_H, button_hover_color=BTN_H,
                          dropdown_fg_color=CARD, command=self.pick_size).pack(side="left", padx=(8, 22))
        self.btn(f, "Apply", lambda: self.apply_layout(size=True), w=90, h=34).pack(side="left")
        f = self.line(c); self.check(f, "Username badges", "badges")
        f = self.line(c); self.check(f, "Animations", "anim"); self.entry(f, "Duration ms", "animMs", 60)
        ctk.CTkLabel(f, text="Limits: 0-600 ms (0 = off)", text_color=MUTED).pack(side="left")
        f = self.line(c); self.btn(f, "Apply all", lambda: self.apply_layout(True, True, True), primary=True, w=140).pack(side="left")
        for k in ("pane", "windowWidth", "windowHeight", "micro"): self.v[k].trace_add("write", self.layout_changed)
        c = self.card(sc, "Graphics lock")
        f = self.line(c); self.check(f, "Lock low graphics on launch", "gfx"); self.check(f, "Mute", "mute")
        f = self.line(c); self.entry(f, "FPS cap", "fps", 60); self.entry(f, "Quality (1-10)", "quality", 60)
        f = self.line(c)
        self.btn(f, "Apply now", self.apply_gfx, w=120).pack(side="left", padx=(0, 10))
        self.btn(f, "Unlock file", self.unlock, w=120).pack(side="left")
        c = self.card(sc, "RAM trimmer")
        f = self.line(c); self.check(f, "Auto trim", "trim"); self.check(f, "Lower priority", "lowprio")
        self.entry(f, "Every (s)", "trim_sec", 60)
        c = self.card(sc, "Anti-AFK")
        f = self.line(c)
        self.entry(f, "Every (min)", "afk_min", 60); self.entry(f, "Corner offset (px)", "afk_off", 60)
        self.entry(f, "Click gap (ms)", "afk_gap", 70)
        f = self.line(c); self.check(f, "Background input (no cursor movement, no focus change)", "afk_bg"); self.check(f, "Fake window activation", "bg_wake")
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Background input posts the Anti-AFK clicks (and macro steps, see the Macros tab) straight to each game window, focused or not, "
                          "all at once. 'Fake window activation' tells an unfocused window it is active while it receives input and undoes that afterwards; "
                          "turn it off if a game misbehaves with it. Whether a game accepts posted input is up to the game - try it with the Visual "
                          "builder's Test button first."
                     ).pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, "Connection watch")
        f = self.line(c); self.check(f, "Auto-rejoin (max 3 per 30 min)", "auto_rejoin")
        f = self.line(c); self.entry(f, "Check every (s)", "watch_sec", 60)
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Asks Roblox whether each account is still in a game. A disconnect is flagged after 2 checks in a "
                          "row, so expect 1-2+ minutes. If an account uses 'appear offline', turn it off in the Viewer tab.").pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, "Hotkeys")
        f = self.line(c); self.check(f, "Hotkeys", "hotkeys", lambda: self.hotkeys(self.v["hotkeys"].get()))
        f = self.line(c); self.entry(f, "Macro hotkey", "macro_key", 170); self.btn(f, "Apply", self.apply_macro_key, w=90, h=34).pack(side="left")
        ctk.CTkLabel(f, text="Starts / stops the macro of the Macros tab, e.g. ctrl+alt+m or F8", text_color=MUTED).pack(side="left", padx=12)
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Ctrl+Shift+1..9 focus the 1st..9th running account (tile order), Ctrl+Shift+Left / Right = previous / next. "
                          "Works while a game window has focus. If another program already uses a key, it is listed in the log."
                     ).pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, "Discord alerts")
        f = self.line(c); self.check(f, "Message when an account crashes, disconnects or fails to launch", "dc_on")
        f = self.line(c); self.entry(f, "Channel ID", "dc_chan", 200); self.btn(f, "Set bot token", self.dc_token, w=130, h=34).pack(side="left", padx=(0, 8))
        self.dc_lab = ctk.CTkLabel(f, width=110, anchor="w", text_color=MUTED, text="Token: set" if self.cfg["dc_token"] else "Token: not set")
        self.dc_lab.pack(side="left", padx=(0, 8)); self.btn(f, "Send test", self.dc_test, w=110, h=34).pack(side="left")
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Create a bot in the Discord developer portal, invite it to your server with permission to post in one channel, then paste that "
                          "channel's ID (Discord Developer Mode > right-click the channel > Copy ID) and set the bot token. The token is stored "
                          "encrypted for this Windows user, like the cookies. The same alert is sent at most once a minute."
                     ).pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, f"Updates  (installed: v{VERSION})")
        f = self.line(c); self.entry(f, "Update link (https)", "update_url", 430)
        f = self.line(c); self.check(f, "Check at launch", "auto_update"); self.btn(f, "Check now", self.check_update_now, w=120).pack(side="left")
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Link to your newest Better RAM .py file (for example its GitHub 'Raw' link). It is only installed when its "
                          "VERSION number is higher than this one. Only use a link that you alone can edit.").pack(anchor="w", padx=18, pady=(0, 14))

    # ---------- logging ----------
    def log(self, msg, kind="info"):
        """Timestamped event -> log panel + file. Safe to call from any thread."""
        stamp = time.strftime("%H:%M:%S")
        try:
            with open(LOG, "a", encoding="utf-8") as fh: fh.write(f"{time.strftime('%Y-%m-%d')} {stamp}  {msg}\n")
        except Exception: pass
        self.after(0, lambda: self.log_line(stamp, msg, kind))
        if kind == "bad" and self.cfg["dc_on"]: self.notify(msg)

    # Writes one timestamped line into the log panel; called on the main thread (added v33, split out of log).
    def log_line(self, stamp, msg, kind):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{stamp}  {msg}\n", kind)
        if int(self.logbox.index("end-1c").split(".")[0]) > 1500: self.logbox.delete("1.0", "300.0")
        self.logbox.configure(state="disabled"); self.logbox.see("end")

    # Short hint such as 'tick accounts first': shown in the log panel only, not saved to the log file (v28; reworked v33).
    def say(self, text):                                    # short hint ("tick accounts first"): shown in the log panel only
        stamp = time.strftime("%H:%M:%S"); self.after(0, lambda: self.log_line(stamp, text, "warn"))

    # Empties the log panel (the log file is untouched) (v28 or earlier).
    def clear_log(self):
        self.logbox.configure(state="normal"); self.logbox.delete("1.0", "end"); self.logbox.configure(state="disabled")

    # ---------- config ----------
    PENDING = {"micro", "windowWidth", "windowHeight", "pane", "macro_key"}      # committed by apply_layout only

    # Copies every settings widget value into self.cfg; entries in PENDING are only committed by apply_layout / live_layout (v28 or earlier).
    def collect(self):
        for k, var in self.v.items():
            if k in self.PENDING: continue
            try: val = var.get()
            except tk.TclError: continue
            if k in STR_KEYS: self.cfg[k] = str(val).strip()
            elif isinstance(var, tk.BooleanVar): self.cfg[k] = bool(val)
            else:
                m = re.search(r"\d+", str(val))
                if m: self.cfg[k] = int(m.group())

    # Writes self.cfg to the data file when something changed (v28 or earlier).
    def save(self):
        self.collect()
        try:
            blob = json.dumps(self.cfg, sort_keys=True)
            if blob != self._saved:
                with open(DATA, "w") as fh: fh.write(blob)
                self._saved = blob
        except Exception: pass

    # Saves settings about once a second so every change is persisted (v28 or earlier).
    def sync(self):                                         # every setting change is persisted within a second
        self.save(); self.after(1000, self.sync)

    # ---------- games ----------
    def glabels(self): return [f'{g["name"]}  ({g["place"]})' for g in self.cfg["games"]]

    # Returns the saved game that has this place id, or None (added v29).
    def game_for(self, pid): return next((g for g in self.cfg["games"] if g["place"] == pid), None)

    # True when the Game | User switch is on 'User' (accounts follow a user instead of joining a game) (added v37).
    def user_mode(self): return self.cfg.get("join_mode") == "user"

    # Handler of the Game | User switch: stores the mode and reloads the saved menu (added v37).
    def set_join_mode(self, v):
        self.cfg["join_mode"] = "user" if v == "User" else "game"; self.save(); self.refresh_games()

    # Refreshes the 'Accounts will join' line and the saved menu to match the entry (added v29; user mode added v37).
    def update_game_info(self):
        try:
            if self.user_mode():
                self.e_game.grid_remove(); self.e_user.grid()
                who = self.v["join_user"].get().strip().lstrip("@"); saved = who.lower() in [u.lower() for u in self.cfg["users"]]
                if not who: dot, txt = MUTED, "No user selected - type a Roblox username above"
                elif not USER_RE.match(who): dot, txt = RED, f'"{who}" is not a valid Roblox username'
                elif saved: dot, txt = GREEN, f"Accounts will join:  {who}'s server (looked up at launch)   -   saved"
                else: dot, txt = ORANGE, f"Accounts will join:  {who}'s server (looked up at launch)   -   not saved yet"
                lab = next((u for u in self.cfg["users"] if u.lower() == who.lower()), "")
            else:
                self.e_user.grid_remove(); self.e_game.grid()
                pid = parse_place(self.v["place"].get()); g = self.game_for(pid) if pid else None
                if not pid: dot, txt = MUTED, "No game selected - enter a game ID or link above"
                elif g: dot, txt = GREEN, f'Accounts will join:  {g["name"]}  (ID {pid})   -   saved'
                else: dot, txt = ORANGE, f"Accounts will join:  ID {pid}   -   not saved yet (press Save to name it)"
                lab = f'{g["name"]}  ({g["place"]})' if g else ""
            self.join_dot.configure(text_color=dot); self.join_lbl.configure(text=txt)
            if self.combo.get() != lab: self.combo.set(lab)
        except Exception: pass

    # Reloads the saved menu with saved games or saved users, depending on the mode (v28; reworked v37).
    def refresh_games(self):
        vals = self.cfg["users"] if self.user_mode() else self.glabels()
        self.combo.configure(values=vals or [""]); self.update_game_info()

    # Handler of the saved menu: copies the chosen game id or username into the entry (added v37, replaces pick_game).
    def pick_target(self, choice):
        if self.user_mode():
            if choice in self.cfg["users"]: self.v["join_user"].set(choice)
        else:
            L = self.glabels()
            if choice in L: self.v["place"].set(self.cfg["games"][L.index(choice)]["place"])
        self.update_game_info()

    # Save button: saves the typed game (asks for a name) or the typed username (added v37, replaces save_game).
    def save_target(self):
        self.collect()
        if self.user_mode():
            who = self.cfg["join_user"].lstrip("@")
            if not USER_RE.match(who): return self.note("Join user", "Type a valid Roblox username first (3-20 letters, numbers or _).")
            if who.lower() not in [u.lower() for u in self.cfg["users"]]: self.cfg["users"].append(who)
            self.v["join_user"].set(who); self.save(); return self.refresh_games()
        pid = parse_place(self.cfg["place"])
        if not pid: return self.note("Game", "Paste a game ID or link first.")
        old = self.game_for(pid)
        name = self.ask("Save game", "Name for this game:", default=old["name"] if old else "")
        if not name: return
        self.cfg["games"] = [g for g in self.cfg["games"] if g["place"] != pid] + [{"name": name, "place": pid}]
        self.v["place"].set(pid); self.refresh_games()

    # Delete button: asks for confirmation, then removes the selected saved game or user (added v37, replaces del_game).
    def del_target(self):
        cur = self.combo.get()
        if self.user_mode():
            if cur not in self.cfg["users"]: return self.say("No saved user selected - pick one in the menu first")
            if not self.confirm("Delete user", f'Delete the saved user "{cur}" from Better RAM?\n\nIt is only removed from your saved '
                                "users list. Nothing changes on Roblox or on your accounts.", [("Delete", True), ("Cancel", False)]): return
            self.cfg["users"] = [u for u in self.cfg["users"] if u != cur]; self.save()
            self.refresh_games(); return self.log(f'Deleted saved user "{cur}"')
        L = self.glabels()
        if cur not in L: return self.say("No saved game selected - pick one in the menu first")
        g = self.cfg["games"][L.index(cur)]
        if not self.confirm("Delete game", f'Delete the saved game "{g["name"]}" (ID {g["place"]}) from Better RAM?\n\n'
                            "It is removed from your saved games list and you would have to save it again. "
                            "Nothing changes on Roblox or on your accounts.", [("Delete", True), ("Cancel", False)]): return
        self.cfg["games"] = [x for x in self.cfg["games"] if x is not g]
        self.refresh_games(); self.log(f'Deleted saved game "{g["name"]}"')

    # ---------- accounts ----------
    def account(self, name): return next((a for a in self.cfg["accounts"] if a["name"] == name), None)
    # Names of the accounts whose checkbox is ticked (v28 or earlier).
    def checked(self): return [n for n, v in self.sel.items() if v.get()]
    # Ticks every account (v28 or earlier).
    def sel_all(self): [v.set(True) for v in self.sel.values()]
    # Unticks every account (v28 or earlier).
    def sel_none(self): [v.set(False) for v in self.sel.values()]

    # Roll call button: switches the account list to the compact [name - status] view and back (added v36).
    def toggle_compact(self):
        self.cfg["compact"] = not self.cfg.get("compact", False)
        if self.cfg["compact"]: self.cfg["perf"] = False
        self.style_roll_btn(); self.save(); self.build_rows(); self.update_rows()

    # Performance button: switches the account list to the performance table and back (added v37).
    def toggle_perf(self):
        self.cfg["perf"] = not self.cfg.get("perf", False)
        if self.cfg["perf"]: self.cfg["compact"] = False
        self.style_roll_btn(); self.save(); self.build_rows(); self.update_rows()

    # Lights up the Roll call / Performance buttons while their view is active (added v36).
    def style_roll_btn(self):
        for btn, key in ((self.rc_btn, "compact"), (self.perf_btn, "perf")):
            on = self.cfg.get(key, False)
            btn.configure(fg_color=TXT if on else BTN, hover_color="#ffffff" if on else BTN_H, text_color=BG if on else TXT)

    # Rebuilds the account rows and the Viewer AFK list from the saved accounts (v28; split into build_rows in v36).
    def refresh(self):
        self.build_rows(); self.build_afk_list([a["name"] for a in self.cfg["accounts"]]); self.after(50, self.update_rows)
        self.macro_targets_refresh()

    # Creates the account rows in one of three views: normal, Roll call (compact) or Performance (added v36; Performance v37).
    def build_rows(self):
        for w in self.list.winfo_children(): w.destroy()
        self.rows = {}
        names = [a["name"] for a in self.cfg["accounts"]]
        self.sel = {n: self.sel.get(n, tk.BooleanVar(value=False)) for n in names}
        compact = self.cfg.get("compact", False) and not self.cfg.get("perf", False)
        perf = self.cfg.get("perf", False)
        for c in range(3): self.list.grid_columnconfigure(c, weight=1 if compact else 0, uniform="rc" if compact else "")
        for i, n in enumerate(names):
            bad = self.cookie_ok.get(n) is False
            txt, col = ("Cookie expired - re-login", RED) if bad else ("Idle", MUTED)
            if perf:
                if i == 0:
                    hf = ctk.CTkFrame(self.list, fg_color="transparent"); hf.pack(fill="x", pady=(0, 2), padx=2)
                    for col_i, (t, w, an) in enumerate(PERF_COLS):
                        ctk.CTkLabel(hf, text=t, text_color=MUTED, width=w, anchor=an, font=("Segoe UI", 11)).grid(row=0, column=col_i, padx=PERF_PAD)
                f = ctk.CTkFrame(self.list, fg_color=FIELD, corner_radius=12); f.pack(fill="x", pady=2, padx=2)
                r = {"perf": True}
                r["dot"] = ctk.CTkLabel(f, text="●", text_color=col, width=PERF_COLS[0][1], font=("Segoe UI", 12))
                r["dot"].grid(row=0, column=0, padx=PERF_PAD, pady=7)
                ctk.CTkCheckBox(f, text=n, variable=self.sel[n], onvalue=True, offvalue=False, corner_radius=6, checkbox_width=20,
                                checkbox_height=20, fg_color=TXT, hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H,
                                text_color=TXT, font=("Segoe UI", 12), width=PERF_COLS[1][1]).grid(row=0, column=1, padx=PERF_PAD, sticky="w")
                for col_i, key in enumerate(("cpu", "gpu", "vram", "ram", "rd", "wr"), 2):
                    r[key] = ctk.CTkLabel(f, text="", text_color=TXT, width=PERF_COLS[col_i][1], anchor="e", font=("Segoe UI", 12))
                    r[key].grid(row=0, column=col_i, padx=PERF_PAD)
                r["st"] = None; self.rows[n] = r
                continue
            if compact:                                      # roll call: [username - status], 3 per row
                f = ctk.CTkFrame(self.list, fg_color=FIELD, corner_radius=10)
                f.grid(row=i // 3, column=i % 3, padx=3, pady=3, sticky="ew"); f.grid_columnconfigure(0, weight=1)
                ctk.CTkCheckBox(f, text=n, variable=self.sel[n], onvalue=True, offvalue=False, corner_radius=6,
                                checkbox_width=20, checkbox_height=20, fg_color=TXT, hover_color="#ffffff", checkmark_color=BG,
                                border_color=BTN_H, text_color=TXT, font=("Segoe UI", 12), width=100).grid(row=0, column=0, padx=(8, 2), pady=8, sticky="w")
                st = ctk.CTkLabel(f, text="", text_color=col, anchor="e", width=58, font=("Segoe UI Semibold", 12))
                st.grid(row=0, column=1, padx=(0, 8))
                self.rows[n] = {"st": st, "short": True}; put(self.rows[n], "st", txt, col)
                continue
            if i: ctk.CTkFrame(self.list, height=2, corner_radius=0, fg_color=BTN_H).pack(fill="x", padx=14, pady=2)
            f = ctk.CTkFrame(self.list, fg_color=FIELD, corner_radius=14); f.pack(fill="x", pady=3, padx=2)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkCheckBox(f, text=n, variable=self.sel[n], onvalue=True, offvalue=False, corner_radius=7,
                            fg_color=TXT, hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H,
                            text_color=TXT, width=140).grid(row=0, column=0, padx=(10, 4), pady=8, sticky="w")
            sf = ctk.CTkFrame(f, fg_color="transparent"); sf.grid(row=0, column=1, padx=4, sticky="w")
            st = ctk.CTkLabel(sf, text=txt, text_color=col, anchor="w", width=100); st.pack(anchor="w")
            tm = ctk.CTkLabel(sf, text="", text_color=MUTED, anchor="w", width=100, height=14, font=("Segoe UI", 11)); tm.pack(anchor="w")
            cpu = ctk.CTkLabel(f, text="", text_color=MUTED, width=40)
            ram = ctk.CTkLabel(f, text="", text_color=MUTED, width=62)
            gpu = ctk.CTkLabel(f, text="", text_color=MUTED, width=64)
            cpu.grid(row=0, column=2, padx=3); ram.grid(row=0, column=3, padx=3); gpu.grid(row=0, column=4, padx=3)
            lp = tk.BooleanVar(value=n in self.cfg["idle_prio"])
            ctk.CTkCheckBox(f, text="Low prio", variable=lp, command=lambda n=n, v=lp: self.set_idle_prio(n, v.get()),
                            width=70, checkbox_width=18, checkbox_height=18, corner_radius=5, fg_color=TXT,
                            hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H, text_color=MUTED,
                            font=("Segoe UI", 12)).grid(row=0, column=5, padx=(4, 2))
            self.btn(f, "Show", lambda n=n: self.show(n), w=52, h=32).grid(row=0, column=6, padx=(4, 8))
            self.rows[n] = {"st": st, "tm": tm, "cpu": cpu, "ram": ram, "gpu": gpu}

    # Sets an account's status text from any thread (v28 or earlier).
    def set_status(self, name, text, color=MUTED):
        # Runs on the main thread: writes the status text into the row.
        def go():
            r = self.rows.get(name)
            if r: put(r, "st", text, color)
        self.after(0, go)

    # Creates one Anti-AFK checkbox for an account (v28 or earlier).
    def afk_box(self, parent, n):
        return ctk.CTkCheckBox(parent, text=n, variable=self.afk_sel[n], command=self.afk_toggle, width=20,
                               height=20, checkbox_width=18, checkbox_height=18, corner_radius=5, fg_color=TXT, hover_color="#ffffff",
                               checkmark_color=BG, border_color=BTN_H, text_color=TXT, font=("Segoe UI", 12))

    # Rebuilds the Viewer's Anti-AFK account list (v28; grid of columns with an auto scrollbar since v32).
    def build_afk_list(self, names):
        for w in self.afk_list.winfo_children(): w.destroy()
        skip = set(self.cfg["afk_skip"])
        self.afk_sel = {n: tk.BooleanVar(value=n not in skip) for n in names}     # the one source of truth
        self.afk_cells = []
        for n in names:
            cell = ctk.CTkFrame(self.afk_list, fg_color=CARD, corner_radius=7, width=170, height=24)
            cell.pack_propagate(False); self.afk_cells.append(cell)
            self.afk_box(cell, n).pack(anchor="w", padx=8, expand=True)
        self.afk_cols = 0; self.layout_afk()
        self.afk_count()

    def layout_afk(self):
        """Accounts sit side by side in as many columns as fit; extra accounts add rows. The scrollbar (top to bottom)
        only appears when there are more than 3 rows."""
        try:
            w = self.afk_rc.winfo_width()
            n = len(self.afk_cells)
            cols = max(1, (max(w, 200) - (24 if n > 3 else 4)) // 176)
            rows = -(-n // cols) if n else 0
            if rows > 3 and cols > 1:                       # the scrollbar costs width: recount without it
                cols = max(1, (max(w, 200) - 24) // 176); rows = -(-n // cols)
            need = rows > 3
            if cols != self.afk_cols:
                self.afk_cols = cols
                for i, c in enumerate(self.afk_cells): c.grid(row=i // cols, column=i % cols, padx=3, pady=2, sticky="w")
            sb = self.afk_list._scrollbar
            if need != self.afk_sb_on:
                self.afk_sb_on = need
                if need: sb.grid()
                else: sb.grid_remove(); self.afk_list._parent_canvas.yview_moveto(0)
        except Exception: pass

    # All / None buttons of the Anti-AFK list (v28 or earlier).
    def afk_all(self, on):
        for v in self.afk_sel.values(): v.set(on)
        self.afk_toggle()

    # Stores which accounts are skipped by Anti-AFK and updates the counter (v28 or earlier).
    def afk_toggle(self):
        self.cfg["afk_skip"] = [n for n, v in self.afk_sel.items() if not v.get()]
        self.afk_count()

    # Updates the 'AFK on (x/y)' label (v28 or earlier).
    def afk_count(self):
        t = f"AFK on ({sum(v.get() for v in self.afk_sel.values())}/{len(self.afk_sel)}):"
        if self.afk_label.cget("text") != t: self.afk_label.configure(text=t)

    # Saves a new account (cookie encrypted) and refreshes the list (v28 or earlier).
    def store_account(self, name, cookie, uid):
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a["name"] != name] + \
                               [{"name": name, "cookie": enc(cookie), "id": uid}]
        self.cookie_ok.pop(name, None); self.refresh(); self.log(f"Added account {name}", "ok")

    # 'Add account (paste cookie)': asks for the .ROBLOSECURITY cookie and checks it with Roblox (v28 or earlier).
    def add(self):
        c = self.ask("Add account", "Paste the .ROBLOSECURITY cookie\n(treat it like a password):", secret=True)
        if not c: return
        try: uid, name = whoami(c.strip())
        except Exception as ex: return self.note("Invalid cookie", str(ex))
        self.store_account(name, c.strip(), uid)

    # 'Add account via browser': opens a browser login in a background thread (v28 or earlier).
    def add_browser(self):
        self.log("Opening browser - log in there (2FA/captcha work normally). It closes by itself.")
        threading.Thread(target=self._browser_login, daemon=True).start()

    # Runs the Playwright browser login and captures the cookie once the user is logged in (v28 or earlier).
    def _browser_login(self):
        try: from playwright.sync_api import sync_playwright
        except ImportError:
            return self.after(0, lambda: self.note("Missing package", "Run:  pip install playwright"))
        exe = find_browser()
        if not exe: return self.log("Microsoft Edge or Google Chrome must be installed", "bad")
        tmp, found, proc = tempfile.mkdtemp(prefix="altmgr_"), None, None   # fresh profile = separate session per account
        with socket.socket() as sk: sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
        try:
            # a normal browser, only attached to afterwards - no automation flags, so the captcha works
            proc = subprocess.Popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={tmp}",
                                     "--no-first-run", "--no-default-browser-check", "https://www.roblox.com/login"])
            with sync_playwright() as p:
                browser = None
                for _ in range(40):
                    try: browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}"); break
                    except Exception: time.sleep(0.5)
                if browser is None: raise RuntimeError("could not attach to the browser")
                ctx, end, tried = browser.contexts[0], time.time() + 600, None
                while time.time() < end and not found:
                    for c in ctx.cookies("https://www.roblox.com"):
                        if c["name"] == ".ROBLOSECURITY" and c["value"] != tried:
                            tried = c["value"]
                            try: uid, name = whoami(tried); found = (name, tried, uid)
                            except Exception: pass
                    if not found: time.sleep(1.5)
        except Exception as ex:
            if not found: self.log(f"Browser login ended: {str(ex)[:80]}", "warn")
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try: proc.wait(5)
                except Exception: pass
            shutil.rmtree(tmp, ignore_errors=True)
        if found: self.after(0, lambda: self.store_account(*found))
        else: self.log("Browser login cancelled / timed out", "warn")

    # Writes the accounts (cookies UNENCRYPTED) to a file after a warning (v28 or earlier).
    def export_accounts(self):
        if not self.cfg["accounts"]: return self.note("Export accounts", "There are no accounts to export.")
        if not self.confirm("Export accounts", "The file will contain your cookies UNENCRYPTED. Anyone who gets it "
                            "can take over these accounts. Never share it, never upload it, delete it after use.",
                            [("Export", True), ("Cancel", None)]): return
        rows = []
        for a in self.cfg["accounts"]:
            try: ck = dec(a["cookie"])
            except Exception: ck = ""
            rows.append({"name": a["name"], "id": a.get("id", 0), "cookie": ck})
        path, i = os.path.join(desktop(), "AltManager_export.json"), 2
        while os.path.exists(path): path, i = os.path.join(desktop(), f"AltManager_export_{i}.json"), i + 1
        try:
            with open(path, "w", encoding="utf-8") as fh: json.dump({"accounts": rows}, fh, indent=2, ensure_ascii=False)
        except Exception as ex: return self.note("Export failed", str(ex)[:200])
        self.log(f"Exported {len(rows)} account(s) to the Desktop", "ok")
        self.note("Export done", f"Saved to:\n{path}\n\nIt is NOT encrypted - delete it when you no longer need it.")

    # Reads an export file; accounts with the same name are replaced (v28 or earlier).
    def import_accounts(self):
        d = os.path.join(desktop(), "AltManager_export.json")
        p = self.ask("Import accounts", "Path of a Better RAM export file (.json).\nAccounts with the same name are replaced.",
                     default=d if os.path.exists(d) else "")
        if not p: return
        try:
            with open(p.strip().strip('"'), encoding="utf-8") as fh: data = json.load(fh)
            new = []
            for r in data["accounts"] if isinstance(data, dict) else data:
                new.append({"name": str(r["name"]), "cookie": enc(str(r["cookie"])), "id": r.get("id", 0)})
        except Exception: return self.note("Import failed", "That file could not be read as a Better RAM export.")
        names = {a["name"] for a in new}
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a["name"] not in names] + new
        for n in names: self.cookie_ok.pop(n, None)
        self.refresh(); self.log(f"Imported {len(new)} account(s)", "ok")

    # 'Delete selected accounts': in-app confirmation, then removes the saved logins (v28 or earlier).
    def remove(self):
        names = self.checked()
        if not names: return self.say("Tick the accounts you want to delete first")
        if not self.confirm("Delete accounts", f"Delete {len(names)} account(s) from Better RAM?\n\n" + ", ".join(names) +
                            "\n\nThe saved logins are removed and you would have to add them again. "
                            "The Roblox accounts themselves are not touched.", [("Delete", True), ("Cancel", False)]): return
        gone = set(names)
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a["name"] not in gone]
        self.refresh()

    # ---------- graphics lock ----------
    def apply_gfx(self):
        self.collect()
        try:
            apply_graphics(self.cfg["fps"], self.cfg["quality"], self.cfg["mute"])
            self.log(f"Graphics lock written (FPS {self.cfg['fps']}, quality {self.cfg['quality']}), file is read-only")
        except Exception as ex: self.note("Settings", str(ex))

    # Unlocks the Roblox settings file from the Settings tab (v28 or earlier).
    def unlock(self):
        try: unlock_settings(); self.log("Graphics settings file unlocked")
        except Exception as ex: self.note("Settings", str(ex))

    # ---------- launching / closing / rejoining ----------
    def launch(self):
        self.save(); user = self.user_mode(); place = "" if user else parse_place(self.cfg["place"])
        who = self.cfg["join_user"].lstrip("@")
        if user and not USER_RE.match(who): return self.note("Join user", "Type a valid Roblox username first (3-20 letters, numbers or _).")
        if not user and not place: return self.note("Game", "Enter a game ID or roblox.com/games link.")
        if self.cfg["gfx"]: self.apply_gfx()
        sel = [a for a in self.cfg["accounts"] if a["name"] in self.checked()]
        todo = [a for a in sel if not (self.windows.get(a["name"]) in self.live() or a["name"] in self.launching)]
        if len(todo) < len(sel):
            self.log("Already running or starting, skipped: " + ", ".join(a["name"] for a in sel if a not in todo), "warn")
        if user:
            if todo:
                self.launching.update(a["name"] for a in todo)
                threading.Thread(target=self._launch_user, args=(who, todo), daemon=True).start()
            return
        if todo: gm = self.game_for(place); self.log(f"Launching {len(todo)} account(s) into " + (f'{gm["name"]} (place {place})' if gm else f"place {place}"))
        self.start_launch(todo, place, "")

    # Worker thread for User mode: looks up the user's current server, shows an error if joining isn't possible, otherwise launches every account there (added v37).
    def _launch_user(self, who, todo):
        cookies = []
        for a in todo:
            try:
                if self.cookie_ok.get(a["name"]) is not False: cookies.append(dec(a["cookie"]))
            except Exception: pass
        place, job, shown, err = resolve_user(who, cookies)
        if err:
            for a in todo: self.launching.discard(a["name"])
            self.log(f"Can't join {shown}: {err}", "bad")
            return self.after(0, lambda: self.note("Can't join user", err))
        self.log(f"Launching {len(todo)} account(s) into {shown}'s server (place {place})")
        self.after(0, lambda: self.start_launch(todo, place, job))

    # Marks accounts as launching and starts the launch worker thread (v28 or earlier).
    def start_launch(self, accounts, place, job):
        self.launching.update(a["name"] for a in accounts)
        if accounts: threading.Thread(target=self._launch_worker, args=(accounts, place, job), daemon=True).start()

    # Launches accounts one after another (one Roblox start at a time) and reports errors per account (v28 or earlier).
    def _launch_worker(self, accounts, place, job):
        self.launch_jobs += 1
        try:
            for a in accounts:
                with self.launch_lock:                       # one Roblox start at a time (window detection relies on it)
                    try: self.launch_one(a, place, job)
                    except Exception as ex:
                        n = a["name"]
                        if "No ticket" in str(ex):
                            self.cookie_ok[n] = False
                            self.set_status(n, "Cookie expired - re-login", RED)
                            self.log(f"{n}: cookie expired - re-login needed", "bad")
                        else:
                            self.set_status(n, f"Error: {str(ex)[:36]}", RED)
                            self.log(f"{n}: launch error - {str(ex)[:80]}", "bad")
                    finally: self.launching.discard(a["name"])
        finally:
            self.launch_jobs -= 1

    # Launches a single account: ticket, start Roblox, wait for its window, hand it to the viewer (v28 or earlier).
    def launch_one(self, a, place, job):
        n = a["name"]; self.crashed.pop(n, None)
        if self.cookie_ok.get(n) is False:
            self.set_status(n, "Cookie expired - skipped", RED); return self.log(f"{n}: skipped (cookie expired)", "warn")
        for i in range(120):                                 # never stack launches on a running installer/updater
            if not installer_running(): break
            if i == 0: self.log(f"{n}: waiting for the Roblox updater to finish", "warn")
            self.set_status(n, "Waiting for Roblox updater..."); time.sleep(1)
        self.set_status(n, "Getting ticket...")
        ticket = auth_ticket(dec(a["cookie"]))
        before, bp = set(roblox_windows()), roblox_pids()
        os.startfile(launch_uri(ticket, place, job))
        self.set_status(n, "Starting...")
        for _ in range(90):
            time.sleep(1)
            if self.fresh(before, bp): break
        else:
            self.set_status(n, "Timed out", RED); return self.log(f"{n}: Roblox window never appeared (timed out)", "bad")
        time.sleep(4)                                        # splash -> game window: take the biggest new window
        cands = self.fresh(before, bp)
        if not cands:
            self.set_status(n, "Window vanished", RED); return self.log(f"{n}: window vanished right after starting", "bad")
        hw = max(cands, key=win_area)
        self.log(f"{n}: launched", "ok")
        self.after(0, lambda: self.adopt(n, hw, place, job))
        time.sleep(self.cfg["delay"])

    def fresh(self, before, bp):
        """New windows of THIS launch: unseen before, not already managed (a docked window hidden on another tab would
        look new and get claimed twice), and owned by a new Roblox process when processes can be told apart."""
        mine = set(self.windows.values()); used = {pid_of(h) for h in mine}
        ws = [h for h in roblox_windows() if h not in before and h not in mine and pid_of(h) not in used]
        new = roblox_pids() - bp
        return [h for h in ws if pid_of(h) in new] if new else ws

    def adopt(self, n, hw, place, job):
        """Main thread only: register a new window, then tile (retile replaces self.windows, so workers must not write it)."""
        if hw in self.windows.values() or not user32.IsWindow(hw):
            return self.log(f"{n}: window was already taken - launch not adopted, press Launch again", "bad")
        self.windows[n] = hw; self.apid[n] = pid_of(hw)
        self.hung[n] = self.missing[n] = self.offline[n] = 0
        self.started[n] = time.time(); self.launch_info[n] = (place, job)
        if n in self.cfg["idle_prio"]: self.set_priority(n, 0x40)
        self.retile()
        for ms in (8000, 20000, 40000):                      # after the game finished joining: refresh a tile stuck on old frames
            self.after(ms, lambda h=hw: self.nudge(h))

    # Closes one instance and clears its row (v28; uses clear_row since v37).
    def kill_instance(self, n, status="Closed"):
        hw = self.windows.pop(n, None)
        if hw:
            kill_pid(pid_of(hw)); self.drop_cell(hw)
            if self.active == hw: self.active = None
            if self.maxed == hw: self.maxed = None
        for d in (self.procs, self.hung, self.missing, self.offline, self.prev_state, self.crashed): d.pop(n, None)
        self.disconnected.discard(n)
        r = self.rows.get(n)
        if r:
            self.clear_row(r, status, MUTED)

    # Closes the ticked running accounts (v28 or earlier).
    def close_selected(self):
        names = [n for n in self.checked() if n in self.windows]
        if not names: return self.say("Tick the running accounts you want to close first")
        for n in names: self.kill_instance(n)
        self.retile(); self.log(f"Closed {len(names)} instance(s): {', '.join(names)}")

    # Closes every instance (v28 or earlier).
    def close_all(self):
        names = list(self.windows)
        for n in names: self.kill_instance(n)
        self.crashed.clear(); self.active = None; self.refresh(); self.sync_empty()
        if names: self.log(f"Closed all instances ({len(names)})")

    # Rejoins the ticked accounts (v28 or earlier).
    def rejoin_selected(self):
        names = self.checked()
        if not names: return self.say("Tick the accounts you want to rejoin first")
        self.rejoin(names)

    def rejoin(self, names):
        """Close the instance (if any) and start it again in the same game."""
        default = (parse_place(self.cfg["place"]), "")
        for n in names:
            a = self.account(n)
            if not a: continue
            place, job = self.launch_info.get(n, default)
            if not place: self.log(f"{n}: no game ID to rejoin - enter one on the Dashboard", "warn"); continue
            self.kill_instance(n, "Rejoining...")
            self.log(f"{n}: rejoining place {place}", "warn")
            self.start_launch([a], place, job)
        self.retile()

    # ---------- connection watch (Roblox presence) ----------
    def check_presence(self, names):
        for n in names:
            a = self.account(n)
            if not a or n not in self.windows or time.time() - self.started.get(n, 0) < 150: continue      # still joining
            if not a.get("id"): a["id"] = whoami(dec(a["cookie"]))[0]
            kind = presence_type(dec(a["cookie"]), a["id"])
            self.after(0, lambda n=n, k=kind: self.on_presence(n, k))
            time.sleep(1)

    # Background thread: connection watch, every 'watch_sec' seconds (minimum 30) checks whether each open account is still in a game (v28 or earlier).
    def watch_loop(self):
        nxt = time.time() + 60
        while True:
            time.sleep(3)
            try:
                if not self.cfg["watch"] or time.time() < nxt: continue
                nxt = time.time() + max(30, self.cfg["watch_sec"])
                self.check_presence(list(self.windows))
            except Exception as ex:
                self.log(f"Connection watch error: {str(ex)[:70]}", "warn")

    # Reacts to a presence result: tracks disconnects and triggers auto-rejoin (v28 or earlier).
    def on_presence(self, n, kind):
        if n not in self.windows: return
        if kind == 2:                                        # in a game
            self.offline[n] = 0
            if n in self.disconnected:
                self.disconnected.discard(n); self.log(f"{n}: back in a game", "ok")
            return
        self.offline[n] = self.offline.get(n, 0) + 1
        if self.offline[n] >= 2 and n not in self.disconnected:
            self.disconnected.add(n)
            self.log(f"{n}: DISCONNECTED - window is open but Roblox says the account is not in a game", "bad")
            if self.cfg["auto_rejoin"]: self.auto_rejoin(n)

    # Rejoins a disconnected account, at most 3 attempts per 30 minutes (v28 or earlier).
    def auto_rejoin(self, n):
        now = time.time(); hist = [t for t in self.rejoin_hist.get(n, []) if now - t < 1800]
        if len(hist) >= 3: return self.log(f"{n}: auto-rejoin paused (3 attempts in 30 min)", "warn")
        self.rejoin_hist[n] = hist + [now]
        self.log(f"{n}: auto-rejoin attempt {len(hist) + 1}", "warn")
        self.rejoin([n])

    # ---------- viewer layout ----------
    def stage_size(self):
        return max(self.stage.winfo_width(), 200), max(self.stage.winfo_height(), 200)

    def sync_empty(self):
        """Hint text in the stage while no instance window is alive."""
        on = not any(user32.IsWindow(h) for h in self.windows.values())
        if on == self.empty_on: return
        self.empty_on = on
        if on: self.empty.place(relx=0.5, rely=0.5, anchor="center")
        else: self.empty.place_forget()

    # Windows that still exist; also clears active/maximized when their window is gone (v28 or earlier).
    def live(self):
        wins = [h for h in self.windows.values() if user32.IsWindow(h)]
        if self.active not in wins: self.active = None
        if self.maxed not in wins: self.maxed = None
        return wins

    # Computes tile slots, the focus-pane rectangle and whether the custom size fits (v28 or earlier; changed v39: a custom
    # tile size is kept and only scaled down, same proportions, when it does not fit - it never switches to the automatic size;
    # changed v40: tiles stack from the top-left corner and the focused window fills all the space right of them).
    def plan(self, n):
        """-> (tile slots, focus-pane rect, tiles fit?) in stage coordinates."""
        W, H = self.stage_size()
        multi = n > 1
        tw = int(W * max(20, min(70, self.cfg["pane"])) / 100) if multi else W
        fits = True
        if self.cfg["micro"]:
            w0, h0 = max(40, self.cfg["windowWidth"]), max(40, self.cfg["windowHeight"])
            s, cols = 0.0, 1
            for c in range(1, n + 1):                        # most columns that keep the biggest scale
                sc = min(1.0, tw / (c * w0), H / (-(-n // c) * h0))
                if sc >= s: s, cols = sc, c
            fits = s >= 1.0
            w, h = max(1, int(w0 * s)), max(1, int(h0 * s))
        else: cols, _, _, w, h = grid_plan(n, tw, H)
        slots = [((i % cols) * w, (i // cols) * h, w, h) for i in range(n)]       # tiles touch each other, stacked from the top-left
        if multi: fx = cols * w + GAP; fr = (fx, 0, max(1, W - fx), H)           # focused window fills the rest
        else: fr = (0, 0, W, H)
        return slots, fr, fits

    # Re-arranges every tile and the focused window in the Viewer; the central layout routine (v28 or earlier).
    def retile(self):
        order = self.cfg["view_order"]
        self.windows = dict(sorted(self.windows.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)))
        self.collect(); wins = self.live(); self.sync_empty(); self.sync_fs()
        if not wins: self.placeholder(None); return
        if self.tv.get() != "Viewer":
            if any(h not in EMBEDDED for h in wins): self.tv.set("Viewer")          # new windows must be embedded now
            else: self._dirty = True; return                                       # hidden stage: lay out when it is shown
        self._dirty = False
        self.update_idletasks(); self.fixes.clear()
        if self.maxed in wins:                               # one instance fills the viewer, the rest are hidden
            self.anim.clear()
            self.placeholder(None); W, H = self.stage_size()
            for hw in wins:
                if hw == self.maxed: self.place(hw, (0, 0, W, H))
                else: self.cell_for(hw).place_forget()
            self.stage.update_idletasks()
            self.after(30, self.update_badges); self.after(60, lambda h=self.maxed: self.give_focus(h))
            return
        if self.active is None: self.active = wins[0]
        slots, fr, fits = self.plan(len(wins))
        for i, hw in enumerate(wins):
            self.place(hw, fr if hw == self.active else slots[i])
        self.sync_ph(wins, slots); self.stage.update_idletasks()
        big = sum(1 for i, hw in enumerate(wins) if hw != self.active
                  and (win_rect(hw).right - win_rect(hw).left > slots[i][2] + 3 or win_rect(hw).bottom - win_rect(hw).top > slots[i][3] + 3))
        msg = f"Layout: {len(wins)} windows, tiles {slots[0][2]}x{slots[0][3]}"
        if big: msg += f" - {big} resisted resizing and are cropped to their tile"
        if not fits: msg += " - custom tile size doesn't fit the tile area, scaled down (raise Tile area % for the exact size)"
        extra = tuple(sorted(h for h in roblox_windows() if h not in wins))
        if extra and extra != getattr(self, "_extra", ()):
            self.log("Roblox window(s) open but not managed by Better RAM (pid " + ", ".join(str(pid_of(h)) for h in extra) +
                     ") - leftover from an earlier session? Close them, they cannot be placed in the viewer", "warn")
        self._extra = extra
        self.layout_msg = msg; self.after(30, self.update_badges); self.set_active_label()

    # Positions one tile cell at a rectangle and rounds its corners (v28 or earlier).
    def place(self, hw, rect):
        x, y, w, h = rect
        cell = self.cell_for(hw)
        self.move_cell(cell, hw, x, y, w, h)
        if cell.rgn != (w, h): cell.rgn = (w, h); round_region(cell.winfo_id(), w, h, RADIUS)
        if hw == self.active:                                # focused instance = real window docked over the pane
            self.dock_local = rect; self.dock(hw)
        else:
            if hw in DOCKED: self.undock(hw, cell)           # just lost focus -> back into its tile
            elif user32.GetParent(hw) != cell.winfo_id(): embed_window(hw, cell.winfo_id())   # never size a top-level as a tile
            fit_child(hw, w, h)

    # Puts a tile cell at its rectangle; an unfocused tile that only changes position (same size) slides there (added v40).
    def move_cell(self, cell, hw, x, y, w, h):
        ms = min(600, max(0, self.cfg["animMs"])) if self.cfg["anim"] else 0
        old = getattr(cell, "cur", None)
        if ms and hw != self.active and old and old != (x, y) and cell.rgn == (w, h) and cell.winfo_ismapped():
            self.anim[cell] = (old[0], old[1], x, y, time.time(), ms); self.anim_go()
        else:
            self.anim.pop(cell, None); cell.cur = (x, y); cell.place(x=x, y=y, width=w, height=h)

    # Border flash of a widget (tile cell or 'Focused' placeholder), fading back to the normal colour (added v40).
    def flash(self, w):
        ms = min(600, max(0, self.cfg["animMs"])) * 2 if self.cfg["anim"] else 0
        if w is not None and ms: self.flashes[w] = (time.time(), ms); self.anim_go()

    # Starts the shared animation ticker if it is not running (added v40).
    def anim_go(self):
        if self._anim_job is None: self._anim_job = self.after(16, self.anim_tick)

    # Shared 16 ms ticker for tile slides and border flashes; only moves cells / recolours borders (never resizes a game window)
    # and stops by itself when nothing is animating, so idle CPU stays at zero (added v40).
    def anim_tick(self):
        self._anim_job = None; now = time.time()
        for cell, (x0, y0, x1, y1, t0, ms) in list(self.anim.items()):
            k = min(1.0, (now - t0) * 1000 / ms); e = 1 - (1 - k) ** 3
            try:
                cell.cur = (round(x0 + (x1 - x0) * e), round(y0 + (y1 - y0) * e)); cell.place(x=cell.cur[0], y=cell.cur[1])
            except tk.TclError: self.anim.pop(cell, None); continue
            if k >= 1: self.anim.pop(cell, None)
        for w, (t0, ms) in list(self.flashes.items()):
            k = min(1.0, (now - t0) * 1000 / ms)
            try: w.configure(bg=mix(MUTED, BTN_H, k))
            except tk.TclError: self.flashes.pop(w, None); continue
            if k >= 1: self.flashes.pop(w, None)
        if self.anim or self.flashes: self.anim_go()

    # Shows or hides the 'Focused' placeholder in the focused account's slot (v28 or earlier).
    def sync_ph(self, wins, slots):
        name = next((n for n, h in self.windows.items() if h == self.active), None)
        show = name and len(wins) > 1 and self.active in wins
        self.placeholder(slots[wins.index(self.active)] if show else None, name)

    def placeholder(self, rect, name=""):
        """Tile-styled stand-in for the focused account's grid slot (plain tk widgets, no native window)."""
        if rect is None:
            if self.ph: self.ph.place_forget()
            return
        if self.ph is None:
            self.ph = tk.Frame(self.stage, bg=BTN_H, highlightthickness=0, bd=0); self.ph.rgn = None
            inner = tk.Frame(self.ph, bg=CARD, bd=0)
            inner.place(x=BORDER, y=BORDER, relwidth=1, relheight=1, width=-2 * BORDER, height=-2 * BORDER)
            tk.Label(inner, text="Focused", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).place(relx=0.5, rely=0.4, anchor="center")
            self.ph_name = tk.Label(inner, bg=CARD, fg=MUTED, font=("Segoe UI Semibold", 11))
            self.ph_name.place(relx=0.5, rely=0.6, anchor="center")
            self.ph_press = None                             # press-and-drag the placeholder onto a tile = switch with it
            # Placeholder: mouse press, remembers where it started (added v33).
            def down(e): self.ph_press = (e.x_root, e.y_root)
            # Placeholder: after 8 px of movement starts dragging the focused account (added v33).
            def move(e):
                if self.ph_press and (self.drag or abs(e.x_root - self.ph_press[0]) + abs(e.y_root - self.ph_press[1]) > 8):
                    self.drag_tile(self.ph_name.cget("text"), e)
            # Placeholder: mouse release, drops the dragged focused account on a tile (added v33).
            def up(e):
                if self.drag: self.drop_tile(self.ph_name.cget("text"), e)
                self.ph_press = None
            for w in (self.ph, inner, *inner.winfo_children()):
                w.configure(cursor="hand2"); w.bind("<Button-1>", down); w.bind("<B1-Motion>", move); w.bind("<ButtonRelease-1>", up)
        x, y, w, h = rect
        self.ph.place(x=x, y=y, width=w, height=h)
        if self.ph.rgn != (w, h): self.ph.rgn = (w, h); round_region(self.ph.winfo_id(), w, h, RADIUS)
        if self.ph_name.cget("text") != name: self.ph_name.configure(text=name)

    # Returns (creating if needed) the tile cell that holds a game window (v28 or earlier).
    def cell_for(self, hw):
        cell = self.cells.get(hw)
        if cell is None:
            cell = tk.Frame(self.stage, bg=BTN_H, highlightthickness=0, bd=0)
            cell.rgn = None; cell.place(x=0, y=0, width=10, height=10); cell.update_idletasks()
            ch = cell.winfo_id()
            user32.SetWindowLongPtrW(ch, GWL_STYLE, (user32.GetWindowLongPtrW(ch, GWL_STYLE) & 0xFFFFFFFF) | WS_CLIPCHILDREN)
            if hw != self.active: embed_window(hw, ch)       # the focused one is docked instead
            self.cells[hw] = cell
        return cell

    # ---------- drag a tile's name tag onto another tile to reorder / onto the Focused tile to switch ----------
    def tile_at(self, x, y, exclude):
        ph = self.ph                                         # the "Focused" placeholder is a drop target too (switch focus)
        if ph is not None and ph.winfo_ismapped() and exclude != self.active and \
                ph.winfo_rootx() <= x < ph.winfo_rootx() + ph.winfo_width() and ph.winfo_rooty() <= y < ph.winfo_rooty() + ph.winfo_height():
            return "PH"
        for hw, c in self.cells.items():
            if hw == exclude or hw in DOCKED or not c.winfo_ismapped(): continue
            if c.winfo_rootx() <= x < c.winfo_rootx() + c.winfo_width() and c.winfo_rooty() <= y < c.winfo_rooty() + c.winfo_height():
                return hw

    # While a name tag is dragged: moves the ghost label and highlights the tile under the mouse (v28 or earlier).
    def drag_tile(self, n, e):
        if self.drag is None:
            ghost = tk.Label(self.stage, text=n, bg=TXT, fg=BG, font=("Segoe UI Semibold", 11), padx=10, pady=4)
            self.drag = {"hw": self.windows.get(n), "ghost": ghost, "target": None}
        d = self.drag
        d["ghost"].place(x=e.x_root - self.stage.winfo_rootx() + 10, y=e.y_root - self.stage.winfo_rooty() + 10)
        d["ghost"].tkraise()
        t = self.tile_at(e.x_root, e.y_root, d["hw"])
        if t != d["target"]:
            self.mark_target(d["target"], False)
            if t: self.mark_target(t, True)                      # highlighted border = drop target
            d["target"] = t

    # Highlights or un-highlights a drop target (a tile or the Focused placeholder) (added v33).
    def mark_target(self, t, on):
        w = self.ph if t == "PH" else self.cells.get(t)
        if w is not None: w.configure(bg=TXT if on else BTN_H)

    # Finishes a drag: reorders tiles, or swaps with the Focused tile and focuses the account (v28; swap added v33).
    def drop_tile(self, n, e):
        d, self.drag = self.drag, None
        if not d: return
        d["ghost"].destroy(); self.mark_target(d["target"], False)
        f = next((k for k, h in self.windows.items() if h == self.active), None)         # focused account
        dst = f if d["target"] == "PH" else next((k for k, h in self.windows.items() if h == d["target"]), None)
        if dst is None or dst == n: return
        names = list(self.windows)
        if f in (n, dst):                                    # dropped on / dragged from the Focused tile: swap places and focus
            i, j = names.index(n), names.index(dst); names[i], names[j] = names[j], names[i]
            self.cfg["view_order"] = names + [x for x in self.cfg["view_order"] if x not in names]
            self.active = self.windows[n if dst == f else dst]
            self.retile(); self.after(50, lambda h=self.active: self.give_focus(h)); self.after(150, self.verify_layout)
            return
        names.insert(names.index(dst), names.pop(names.index(n)))
        self.cfg["view_order"] = names + [x for x in self.cfg["view_order"] if x not in names]
        self.retile()

    # Removes the tile cell of a closed window (v28 or earlier).
    def drop_cell(self, hw):
        EMBEDDED.discard(hw); DOCKED.discard(hw); ORIG_STYLE.pop(hw, None); RGN.pop(hw, None)
        c = self.cells.pop(hw, None)
        if c: c.destroy()
        if hw == self.active: self.placeholder(None)

    # Releases every embedded window back to the desktop (v28 or earlier).
    def unembed_all(self):
        for hw in list(EMBEDDED): unembed_window(hw)
        for hw in list(self.cells): self.cells.pop(hw).destroy()

    # Window handle of the app's top-level window (v28 or earlier).
    def top_hwnd(self): return user32.GetAncestor(self.winfo_id(), 2)

    # Parks the focused game window as a real top-level window over the focus pane (v28 or earlier).
    def dock(self, hw):
        if self.modal: return
        x, y, w, h = self.dock_local
        sx, sy = self.stage.winfo_rootx() + x, self.stage.winfo_rooty() + y
        fresh = hw not in DOCKED
        dock_window(hw, self.top_hwnd(), sx, sy, w, h, raise_=fresh)
        self.last_dock = (sx, sy, w, h)
        if fresh: self.after(60, lambda: self.give_focus(hw)); self.after(120, lambda: self.kick(hw, True))
        self.set_active_label()

    # Puts a docked window back into its tile cell (v28 or earlier).
    def undock(self, hw, cell):
        user32.SetWindowLongPtrW(hw, GWLP_HWNDPARENT, 0); DOCKED.discard(hw)
        embed_window(hw, cell.winfo_id())

    def give_focus(self, hw):
        """Only a real top-level window can hold true OS focus, so this applies to the docked instance."""
        try:
            if user32.IsWindow(hw) and hw in DOCKED and not self.modal: user32.SetForegroundWindow(hw)
        except Exception: pass

    def kick(self, hw, grow):
        """A re-docked game surface can stay gray until its size changes (exactly what a manual resize does):
        grow it by 1 px, then restore the real size 60 ms later so the swapchain re-creates and repaints."""
        if hw != self.active or hw not in DOCKED or not user32.IsWindow(hw) or not self.last_dock: return
        x, y, w, h = self.last_dock; d = 1 if grow else 0
        user32.SetWindowPos(hw, 0, x, y, w + d, h + d, SWP_NOZORDER | SWP_NOACTIVATE)
        if grow: self.after(60, lambda: self.kick(hw, False))

    def nudge(self, hw, grow=True):
        """Tiles can keep showing the first frames after joining (join banners etc.) until the window's size changes.
        Grow the tile by 1 px, then put the real size back 80 ms later: the game re-creates its surface and repaints."""
        c = self.cells.get(hw)
        if not c or hw in DOCKED or not user32.IsWindow(hw) or not c.winfo_ismapped() or self.tv.get() != "Viewer": return
        d = 1 if grow else 0
        user32.SetWindowPos(hw, HWND_TOP, BORDER, BORDER, c.winfo_width() - 2 * BORDER + d, c.winfo_height() - 2 * BORDER + d, SWP_NOACTIVATE)
        if grow: self.after(80, lambda: self.nudge(hw, False))

    # Nudges every tile one after another (added v35; used by Refresh status).
    def nudge_all(self):
        for i, hw in enumerate(list(self.cells)): self.after(i * 120, lambda h=hw: self.nudge(h))

    # Updates the 'Focused: name' label (v28 or earlier).
    def set_active_label(self):
        name = next((n for n, h in self.windows.items() if h == self.active), None)
        self.active_label.configure(text=f"Focused: {name}" if name else "Focused: -")

    # Makes a window the focused one (swaps it with the previous focused tile) (v28 or earlier).
    def switch_to(self, hw):
        if hw == self.active: return
        old, self.active = self.active, hw
        wins = self.live()
        if hw not in wins: return
        slots, fr, _ = self.plan(len(wins))
        if old in wins: self.place(old, slots[wins.index(old)])
        self.place(hw, fr); self.sync_ph(wins, slots)
        self.flash(self.cells.get(old)); self.flash(self.ph)
        self.stage.update_idletasks()
        self.after(10, self.update_badges); self.after(50, lambda: self.give_focus(hw)); self.after(150, self.verify_layout)

    # Dashboard 'Show' button: opens the Viewer and focuses that account (v28 or earlier).
    def show(self, n):
        hw = self.windows.get(n)
        if not hw or hw not in self.live(): return
        if self.maxed: self.maxed = None; self.retile()
        self.tv.set("Viewer"); self.switch_to(hw)

    def fullscreen(self):
        """One button: the focused instance fills the viewer; press again to bring the tiles back."""
        if self.maxed: self.maxed = None
        elif self.live() and self.active: self.maxed = self.active
        else: return self.say("No instance running")
        self.retile()

    # Keeps the Fullscreen button text in sync (v28 or earlier).
    def sync_fs(self):
        t = "Exit fullscreen" if self.maxed else "Fullscreen"
        if self.fs.cget("text") != t: self.fs.configure(text=t)

    # Preset menu for tile size: only fills the fields, 'Apply' commits (v28 or earlier).
    def pick_size(self, choice):                             # only fills the fields; "Apply" commits them
        w, h = choice.split("x"); self.v["windowWidth"].set(w); self.v["windowHeight"].set(h)

    def num(self, key, lo, hi):
        """Reads just the digits of an entry (so '40%' or ' 320 px' work), limits it, writes the clean number back."""
        m = re.search(r"\d+", str(self.v[key].get()))
        if not m: return None, None
        raw = int(m.group()); n = min(hi, max(lo, raw))
        self.v[key].set(str(n)); self.cfg[key] = n
        return n, raw

    # Typing in a layout entry (or ticking Custom tile size) schedules live_layout 0.7 s after the last change (added v39).
    def layout_changed(self, *_):
        if self._lay_job: self.after_cancel(self._lay_job)
        self._lay_job = self.after(700, self.live_layout)

    # Commits tile size / tile area from the entries without rewriting them (so typing is not disturbed) and re-tiles
    # when the Viewer is next shown; the Apply buttons still confirm in the log (added v39).
    def live_layout(self):
        self._lay_job = None
        try:
            for k, lo, hi in (("pane", 20, 70), ("windowWidth", 40, 4000), ("windowHeight", 40, 4000)):
                m = re.search(r"\d+", str(self.v[k].get()))
                if m: self.cfg[k] = min(hi, max(lo, int(m.group())))
            self.cfg["micro"] = bool(self.v["micro"].get())
        except tk.TclError: return
        if self.tv.get() == "Viewer": self.retile()
        else: self._dirty = True

    # Commits the layout entries and re-tiles, every step confirmed in the log (v28 or earlier; changed v39: cancels the pending live_layout).
    def apply_layout(self, size=False, pane=False, other=False):
        """Commit layout entries (they are not used before) and re-tile; every step is confirmed in the log."""
        if other:
            self.collect(); self.log(f"Launch delay {self.cfg['delay']} s, username badges {'on' if self.cfg['badges'] else 'off'}")
        if size:
            self.cfg["micro"] = bool(self.v["micro"].get())
            (w, rw), (h, rh) = self.num("windowWidth", 40, 4000), self.num("windowHeight", 40, 4000)
            if w is None or h is None: self.log("Custom tile size: type a number for width and height", "warn")
            else:
                self.log(f"Custom tile size {'ON' if self.cfg['micro'] else 'OFF (automatic sizes)'}: {w}x{h} px"
                         + (" (limited to 40-4000)" if (w, h) != (rw, rh) else ""))
        if pane:
            n, raw = self.num("pane", 20, 70)
            if n is None: self.log("Tile area: type a number (20-70)", "warn")
            else: self.log(f"Tile area set to {n}% of viewer width" + (f" (you typed {raw}, allowed 20-70)" if n != raw else ""))
        if self._lay_job: self.after_cancel(self._lay_job); self._lay_job = None
        if not self.live(): return self.log("No Roblox windows open - the layout is used as soon as they start")
        self.layout_msg = ""; self.retile()
        self.log(self.layout_msg or ("Saved - applied when you open the Viewer tab" if self._dirty
                 else "Saved - fullscreen is on, 'Exit fullscreen' in the Viewer tab brings the tiles back"))

    def on_resize(self, e):
        """Every customtkinter widget redraws on each step of a window drag (slow). Hide the content while the size is
        changing and draw it once, 200 ms after the last step."""
        if e.widget is not self: return
        size = (e.width, e.height)
        if size == self._size: return
        self._size = size
        if not self.ready or self.state() == "iconic": return
        if not self.sizing:
            self.sizing = True
            for h in DOCKED:
                if user32.IsWindow(h): user32.ShowWindow(h, 0)
            self.tv.pack_forget()
        if self._rz: self.after_cancel(self._rz)
        self._rz = self.after(200, self.end_resize)

    # Redraws the UI once after a window resize has finished (v28 or earlier).
    def end_resize(self):
        self._rz = None
        self.tv.pack(fill="both", expand=True, padx=6, pady=8)
        self.update_idletasks(); self.sizing = False
        self.after(50, self.settle)

    def settle(self):
        """Second pass after a drag: final size, fresh layout for the scrollable frames and the stage."""
        if self._rz or self.sizing: return                  # a new drag started meanwhile
        self._size = (self.winfo_width(), self.winfo_height())
        self.tv.pack_configure(fill="both", expand=True)
        self.update_idletasks()
        for sf in (self.list, self.afk_list):
            try: sf._fit_frame_dimensions_to_canvas(None)
            except Exception: pass
        self.on_stage()

    # Viewer stage was resized: schedules a re-layout (v28 or earlier).
    def on_stage(self, _=None):
        if self._relayout: self.after_cancel(self._relayout)
        self._relayout = self.after(200, self._do_relayout)

    # Runs the scheduled re-layout when the Viewer is visible (v28 or earlier).
    def _do_relayout(self):
        self._relayout = None
        if self.cells and self.tv.get() == "Viewer" and self.stage.winfo_width() > 200: self.retile()

    # Walks up from a clicked child window to the game window it belongs to (v28 or earlier).
    def owner_of(self, h):
        mine = set(self.windows.values())
        for _ in range(8):                                   # walk up from a clicked child window to one of ours
            if not h: return None
            if h in mine: return h
            h = user32.GetParent(h)
        return None

    def poll(self):
        """Click on a tile (acted on at RELEASE, never mid-click) -> it becomes the focused real window."""
        down = bool(user32.GetAsyncKeyState(1) & 0x8000); now = time.time()
        if down and not self.was_down and not self.busy:
            pt = wt.POINT(); user32.GetCursorPos(ctypes.byref(pt))
            hw = self.owner_of(user32.WindowFromPoint(pt))
            self.press = (hw, pt.x, pt.y, now) if hw else None
        elif self.was_down and not down and self.press:
            hw, x0, y0, t0 = self.press; self.press = None
            pt = wt.POINT(); user32.GetCursorPos(ctypes.byref(pt))
            if now - t0 < 0.6 and abs(pt.x - x0) < 8 and abs(pt.y - y0) < 8 and user32.IsWindow(hw) and hw != self.active:
                self.switch_to(hw)
        self.was_down = down
        fg = user32.GetForegroundWindow()
        if fg and fg == self.top_hwnd() and not self.app_fg_top and self._tab == "Viewer" and self.active in DOCKED:
            self.after(120, lambda h=self.active: self.give_focus(h))     # tabbed back in -> hand focus to the game
        self.app_fg_top = bool(fg and fg == self.top_hwnd()); self._tab = self.tv.get()
        if self._dirty and self._tab == "Viewer": self._dirty = False; self.after(60, self.retile)
        self.after(40 if self._tab == "Viewer" and self.cells else 200, self.poll)

    # Wakes track_dock immediately (and optionally switches it to the fast 10 ms rate for 0.6 s) (added v38).
    def kick_track(self, fast=False):
        if fast: self.dock_fast_until = time.time() + 0.6
        if self._td:
            try: self.after_cancel(self._td)
            except Exception: pass
        self.track_dock()

    # The manager window was moved: switch the docked game window to fast following at once (added v38).
    def on_move(self, e):
        if e.widget is not self: return
        pos = (self.winfo_x(), self.winfo_y())
        if pos != self._winpos:
            self._winpos = pos
            if self.ready: self.kick_track(True)

    def track_dock(self):
        """Keep the docked window glued to the focus pane when the app moves/resizes; hide it off the Viewer tab."""
        try:
            if self.modal or self.sizing: return                  # a prompt is open / the window is being resized: leave it hidden
            hw = self.active
            if hw and hw in DOCKED and user32.IsWindow(hw) and self.dock_local:
                if self.tv.get() != "Viewer" or self.state() == "iconic":
                    if user32.IsWindowVisible(hw): user32.ShowWindow(hw, 0)
                else:
                    x, y, w, h = self.dock_local
                    want = (self.stage.winfo_rootx() + x, self.stage.winfo_rooty() + y, w, h)
                    r = win_rect(hw)
                    bad = (user32.GetWindowLongPtrW(hw, GWL_STYLE) & WS_CAPTION == WS_CAPTION or user32.GetWindowLongPtrW(hw, GWL_STYLE) & WS_THICKFRAME) or \
                          max(abs(r.left - want[0]), abs(r.top - want[1]), abs(r.right - r.left - w), abs(r.bottom - r.top - h)) > 2
                    if bad: self.dock_fast_until = time.time() + 0.5
                    if bad and self.dock_fix < 25:           # Roblox put its frame/size back (e.g. while still starting): dock it again
                        if not self.dock_fix: self.log("Focused window left its pane - re-docking", "warn")
                        self.dock_fix += 1
                        _restyle(hw, WS_POPUP | WS_VISIBLE, WS_EX_TOOLWINDOW)
                        user32.SetWindowPos(hw, 0, *want, SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED)
                        self.last_dock = want; self.after(80, lambda h=hw: self.kick(h, True))
                    elif want != self.last_dock or not user32.IsWindowVisible(hw):
                        self.dock_fast_until = time.time() + 0.5
                        user32.SetWindowPos(hw, 0, *want, SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
                        self.last_dock = want
                    if not bad: self.dock_fix = 0
        finally:
            fast = time.time() < self.dock_fast_until
            if fast != self.hires:
                try: (ctypes.windll.winmm.timeBeginPeriod if fast else ctypes.windll.winmm.timeEndPeriod)(1)
                except Exception: pass
                self.hires = fast
            self._td = self.after(10 if fast else 80 if self.dock_fix else 200, self.track_dock)

    def verify_layout(self):
        """Self-heal: a tile that re-parented itself, regained its frame, or drifted gets put back."""
        if not (self.cells and self.tv.get() == "Viewer"): return
        for hw, cell in list(self.cells.items()):
            if hw in DOCKED:
                if hw != self.active and user32.IsWindow(hw): self.undock(hw, cell); fit_child(hw, cell.winfo_width(), cell.winfo_height())
                continue
            if not user32.IsWindow(hw) or not cell.winfo_ismapped(): continue
            ch = cell.winfo_id(); w, h = cell.winfo_width(), cell.winfo_height()
            st = user32.GetWindowLongPtrW(hw, GWL_STYLE) & 0xFFFFFFFF
            if user32.GetParent(hw) != ch or not (st & WS_CHILD) or (st & (WS_CAPTION | WS_THICKFRAME)) \
               or user32.GetWindowLongPtrW(hw, GWL_EXSTYLE) & WS_EX_LAYERED:      # stuck at alpha 0 = grey tile
                embed_window(hw, ch); fit_child(hw, w, h); continue
            r = win_rect(hw)
            if (abs(r.right - r.left - w + 2 * BORDER) > 2 or abs(r.bottom - r.top - h + 2 * BORDER) > 2) and self.fixes.get(hw, 0) < 3:
                self.fixes[hw] = self.fixes.get(hw, 0) + 1   # stop nagging a window that truly can't resize
                fit_child(hw, w, h)

    # Every 1.5 s verifies the docked layout and repairs it (v28 or earlier).
    def heal_loop(self):
        try: self.verify_layout()
        finally: self.after(1500, self.heal_loop)

    # ---------- badges ----------
    def update_badges(self):
        for n in [n for n in self.badges if n not in self.windows]:
            try: self.badges.pop(n).destroy()
            except Exception: self.badges.pop(n, None)
        for n, hw in self.windows.items():
            c = self.cells.get(hw)
            if not c: continue
            try:
                b = self.badges.get(n)
                if b is not None and b.master is not c: b.destroy(); b = None
                if b is None: b = self.badges[n] = Badge(c, n, lambda h=hw: self.switch_to(h), lambda e, n=n: self.drag_tile(n, e),
                                           lambda e, n=n: self.drop_tile(n, e))
                if not self.cfg["badges"]: b.place_forget(); continue
                if not b.winfo_ismapped(): b.place(x=4, y=4)
                b.set_color(RED if n in self.disconnected else ORANGE if self.hung.get(n, 0) >= 2 else GREEN)
                b.raise_above(c.winfo_id())
            except Exception: pass

    # Every 0.4 s refreshes the username tags while the Viewer is open (v28 or earlier).
    def badge_loop(self):
        try:
            if self.cells and self.tv.get() == "Viewer": self.update_badges()
        finally: self.after(400, self.badge_loop)

    # ---------- dashboard ----------
    def usage(self, n, pid):
        try:
            p = self.procs.get(n)
            if not p or p.pid != pid: p = psutil.Process(pid); p.cpu_percent(None); self.procs[n] = p
            return p.cpu_percent(None) / (psutil.cpu_count() or 1), p.memory_info().rss / 1048576
        except Exception: return None, None

    def disk_rate(self, n, pid):
        """Read / write bytes per second of an instance since the last look (needs the process kept by usage())."""
        try:
            p = self.procs.get(n)
            if not p or p.pid != pid: return None
            io = p.io_counters(); t = time.time(); prev = self.io_prev.get(pid)
            if len(self.io_prev) > 64: self.io_prev = {k: v for k, v in self.io_prev.items() if psutil.pid_exists(k)}
            if prev and t - prev[0] < 0.5: return None
            self.io_prev[pid] = (t, io.read_bytes, io.write_bytes)
            if not prev: return None
            dt = t - prev[0]
            return max(0, io.read_bytes - prev[1]) / dt, max(0, io.write_bytes - prev[2]) / dt
        except Exception: return None

    # Blanks an account row's values and sets its status dot (added v37).
    def clear_row(self, r, st=None, col=MUTED):
        if st is not None: put(r, "st", st, col)
        put(r, "dot", "●", col)
        for k in ("tm", "cpu", "ram", "gpu", "vram", "rd", "wr"): put(r, k, "")

    # Refreshes every account row and the summary each 2 s: status, timer, CPU/RAM/GPU, outdated check, performance columns (v28; extended v29-v37).
    def update_rows(self):
        run = frozen = disc = crashed = 0; ram = cpu_t = gpu_t = 0.0
        for n, hw in list(self.windows.items()):            # gone for 2 checks in a row = crashed / closed
            self.missing[n] = 0 if user32.IsWindow(hw) else self.missing.get(n, 0) + 1
            if self.missing[n] >= 2 and self.rebind(n, hw): continue
            if self.missing[n] >= 2:
                self.crashed[n] = time.strftime("%H:%M"); use = self.crash_use[n] = self.last_use.pop(n, None)
                self.windows.pop(n); self.procs.pop(n, None); self.prev_state.pop(n, None); self.disconnected.discard(n)
                self.drop_cell(hw)
                self.log(f"{n}: window disappeared - crashed or closed" +
                         (f" (last seen: RAM {use[1]:.0f} MB, CPU {use[0]:.0f}%)" if use else ""), "bad")
                self.sync_empty()
        for a in self.cfg["accounts"]:
            n = a["name"]; r = self.rows.get(n)
            if not r: continue
            if n in self.windows:
                hw = self.windows[n]
                self.hung[n] = self.hung.get(n, 0) + 1 if user32.IsHungAppWindow(hw) else 0
                cpu, mb = self.usage(n, pid_of(hw))
                if self.hung[n] >= 2: state, text, col = "frozen", "Frozen (not responding)", ORANGE; frozen += 1
                elif n in self.disconnected: state, text, col = "disc", "Disconnected - not in a game", RED; disc += 1
                else:
                    state, text, col = "run", "Running", GREEN; run += 1
                    pid = pid_of(hw); b = self.build_of(pid)
                    if b and self.latest_ver and b != self.latest_ver:        # started from an older Roblox build
                        text, col = "Running (outdated)", ORANGE
                        if pid not in self.out_logged:
                            self.out_logged.add(pid); self.log(f"{n}: running an outdated Roblox build - Rejoin it to update", "warn")
                if state != self.prev_state.get(n):
                    if state == "frozen": self.log(f"{n}: not responding", "warn")
                    elif self.prev_state.get(n) == "frozen": self.log(f"{n}: responding again", "ok")
                    self.prev_state[n] = state
                if cpu is not None: cpu_t += cpu; ram += mb; self.last_use[n] = (cpu, mb)
                put(r, "st", text, col); put(r, "dot", "●", col)
                t0 = self.started.get(n); put(r, "tm", f"In game {fmt_dur(time.time() - t0)}" if t0 else "")
                put(r, "cpu", "n/a" if cpu is None else f"{cpu:.0f}%"); put(r, "ram", "n/a" if mb is None else f"{mb:.0f} MB")
                pid = pid_of(hw); g = self.gpu.get(pid); pre = "" if r.get("perf") else "GPU "
                put(r, "gpu", f"{pre}n/a" if self.gpu_ok is False else f"{pre}-" if self.gpu_ok is None else f"{pre}{g or 0:.0f}%")
                if g: gpu_t += g
                if r.get("perf"):
                    put(r, "vram", "-" if self.vram_ok is None else "n/a" if not self.vram_ok else fmt_bytes(self.vram.get(pid, 0)))
                    d = self.disk_rate(n, pid)
                    if d: put(r, "rd", fmt_rate(d[0])); put(r, "wr", fmt_rate(d[1]))
            elif n in self.crashed:
                crashed += 1
                u = self.crash_use.get(n)
                put(r, "st", f"Crashed / closed ({self.crashed[n]})", RED); put(r, "tm", ""); put(r, "dot", "●", RED)
                put(r, "cpu", f"{u[0]:.0f}%" if u else "-"); put(r, "ram", f"{u[1]:.0f} MB" if u else "-")
                for k in ("gpu", "vram", "rd", "wr"): put(r, k, "")
        for k, t in (("run", f"Running {run}"), ("frozen", f"Frozen {frozen}"), ("disc", f"Disconnected {disc}"),
                     ("crashed", f"Crashed {crashed}"), ("ram", f"RAM {ram/1024:.1f} GB"), ("cpu", f"CPU {cpu_t:.0f}%"),
                     ("gpu", f"GPU {min(100, gpu_t):.0f}%" if self.gpu_ok else "GPU n/a")):
            put(self.sum, k, t)

    def version_loop(self):
        """Asks Roblox which build is current (every 15 min). Network trouble just keeps the last answer."""
        while True:
            wait = 120
            try:
                r = requests.get(RBX_VERSION_URL, timeout=10); r.raise_for_status()
                v = r.json().get("clientVersionUpload")
                if v: self.latest_ver, wait = v, 900
            except Exception: pass
            time.sleep(wait)

    def build_of(self, pid):
        """Roblox build folder (version-xxxxxxxx) a running instance was started from; cached per process."""
        if pid not in self.pid_build:
            if len(self.pid_build) > 64: self.pid_build = {p: b for p, b in self.pid_build.items() if psutil.pid_exists(p)}
            try:
                b = os.path.basename(os.path.dirname(psutil.Process(pid).exe()))
                self.pid_build[pid] = b if b.startswith("version-") else None
            except Exception: self.pid_build[pid] = None
        return self.pid_build[pid]

    # Background thread that samples GPU and VRAM usage every ~1.5 s (added v29; VRAM v37).
    def gpu_loop(self):
        while True:
            try:
                time.sleep(1.5 if self.windows else 4)
                r = gpu_sample()
                if r is None: self.gpu_ok = False; time.sleep(30); continue      # counters missing (old Windows / no driver)
                self.gpu, self.gpu_total, self.gpu_ok = r[0], r[1], True
                self.vram_ok = r[2] is not None; self.vram = r[2] or {}
            except Exception: time.sleep(5)

    def rebind(self, n, old):
        """Roblox sometimes replaces its window (same process, new handle): follow it instead of calling it a crash."""
        mine = set(self.windows.values())
        ws = [h for h in roblox_windows() if h not in mine and pid_of(h) == self.apid.get(n)]
        if not ws: return False
        new = max(ws, key=win_area)
        self.drop_cell(old); self.windows[n] = new; self.missing[n] = 0
        if self.active == old: self.active = new
        if self.maxed == old: self.maxed = new
        self.log(f"{n}: Roblox replaced its window - following it", "warn"); self.retile()
        return True

    def refresh_status(self):
        """Re-check every account now: clear stale crash notes, redraw usage, ask Roblox who is really in a game."""
        for n in [n for n in self.crashed if n not in self.windows]: del self.crashed[n]
        self.missing.clear()
        for a in self.cfg["accounts"]:
            r = self.rows.get(a["name"])
            if r and a["name"] not in self.windows:
                bad = self.cookie_ok.get(a["name"]) is False
                self.clear_row(r, "Cookie expired - re-login" if bad else "Idle", RED if bad else MUTED)
        self.update_rows(); self.nudge_all()
        threading.Thread(target=self._refresh_presence, daemon=True).start()

    # Refresh status button, worker part: re-checks who is really in a game (v28 or earlier).
    def _refresh_presence(self):
        try: self.check_presence(list(self.windows))
        except Exception as ex: self.log(f"Status refresh error: {str(ex)[:70]}", "warn")
        self.after(1500, self.update_rows)

    # Every 2 s calls update_rows (v28 or earlier).
    def dash(self):
        try: self.update_rows()
        finally: self.after(2000, self.dash)

    # ---------- RAM trim ----------
    def prio_class(self, n):
        return 0x40 if n in self.cfg["idle_prio"] else 0x4000 if self.cfg["lowprio"] else 0x20   # IDLE / BELOW_NORMAL / NORMAL

    # Sets a process priority class for an instance (v28 or earlier).
    def set_priority(self, n, cls):
        hw = self.windows.get(n)
        hp = hw and user32.IsWindow(hw) and kernel32.OpenProcess(0x0200 | 0x0400, False, pid_of(hw))
        if hp: kernel32.SetPriorityClass(hp, cls); kernel32.CloseHandle(hp)

    # 'Low prio' checkbox of an account: stores it and applies it (v28 or earlier).
    def set_idle_prio(self, n, on):
        s = set(self.cfg["idle_prio"]); (s.add if on else s.discard)(n)
        self.cfg["idle_prio"] = sorted(s); self.set_priority(n, self.prio_class(n))
        self.log(f"{n}: lowest priority {'on' if on else 'off'}")

    # Trims RAM of every running instance (also run automatically by maintenance) (v28 or earlier).
    def do_trim(self):
        ok = blocked = 0
        for n, hw in list(self.windows.items()):
            if not user32.IsWindow(hw): continue
            hp = kernel32.OpenProcess(0x0100 | 0x0200 | 0x0400, False, pid_of(hw))
            if not hp: blocked += 1; continue
            if psapi.EmptyWorkingSet(hp): ok += 1
            else: blocked += 1
            if self.prio_class(n) != 0x20: kernel32.SetPriorityClass(hp, self.prio_class(n))
            kernel32.CloseHandle(hp)
        if ok or blocked: self.log(f"RAM trim: {ok} trimmed, {blocked} blocked", "ok" if ok else "warn")

    # ---------- global hotkeys (RegisterHotKey on one idle thread; costs nothing until a key is pressed) ----------
    HK_KEYS = [(i, 0x30 + i, str(i)) for i in range(1, 10)] + [(10, 0x25, "Left"), (11, 0x27, "Right")]

    # Starts or stops the global Ctrl+Shift hotkey thread (v28 or earlier).
    def hotkeys(self, on):
        th = self.hk_thread
        if on and not (th and th.is_alive()):
            self.hk_thread = threading.Thread(target=self._hk_loop, daemon=True); self.hk_thread.start()
        elif not on and th and th.is_alive():
            user32.PostThreadMessageW(self.hk_tid, 0x0012, 0, 0); th.join(1)       # WM_QUIT; the thread unregisters itself

    # Hotkey thread: registers the hotkeys and forwards presses to the main thread (v28 or earlier).
    def _hk_loop(self):
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)                      # creates this thread's message queue
        self.hk_tid = kernel32.GetCurrentThreadId()
        bad = [f"Ctrl+Shift+{name}" for i, vk, name in self.HK_KEYS if not user32.RegisterHotKey(None, i, 0x4006, vk)]
        spec = hotkey_spec(self.cfg["macro_key"])                                  # the configurable macro hotkey (id 20, added v41)
        if spec and not user32.RegisterHotKey(None, 20, spec[0] | 0x4000, spec[1]): bad.append(self.cfg["macro_key"])
        if bad: self.log("Hotkeys unavailable (used by another program): " + ", ".join(bad), "warn")
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312: self.after(0, lambda i=int(msg.wParam): self.hotkey(i))
        for i, _, _ in self.HK_KEYS: user32.UnregisterHotKey(None, i)
        user32.UnregisterHotKey(None, 20)

    # Handles one Ctrl+Shift hotkey press: 1-9 focus that account by position, Left / Right focus the previous / next one (v28 or earlier).
    def hotkey(self, i):
        if i == 20: return self.macro_toggle()               # macro hotkey (added v41)
        if self.modal or self.busy: return
        alive = self.live(); names = [n for n, h in self.windows.items() if h in alive]
        if not names: return
        if i <= 9: idx = i - 1
        else:
            cur = next((k for k, n in enumerate(names) if self.windows[n] == self.active), -1)
            idx = (cur + (-1 if i == 10 else 1)) % len(names)
        if idx < len(names): self.show(names[idx])

    # ---------- anti-AFK: visit each instance and click for real (a tile can't hold OS focus) ----------
    def run_seq(self, steps):
        if not steps: return
        d, fn = steps[0]
        # Runs one step of the Anti-AFK sequence, then the rest (run_seq helper).
        def go():
            try: fn()
            finally: self.run_seq(steps[1:])
        self.after(d, go)

    # Starts an Anti-AFK round (clicks each account's window); waits when the user is active or the app is minimized (v28 or earlier;
    # changed v42: with 'Background input' on, the round is posted to the windows instead - see afk_bg_round - and needs no waiting).
    def start_afk(self, force=False):
        if self.afk_busy: return
        if self.cfg["afk_bg"]: return self.afk_bg_round(force)
        if self.state() == "iconic":
            self.afk_next = time.time() + 60; return self.say("Anti-AFK waiting: the manager is minimized")
        if not force and user_idle_seconds() < 8:
            self.afk_next = time.time() + 30; return          # you're busy: try again shortly
        alive, skip = self.live(), set(self.cfg["afk_skip"])
        wins = [h for n, h in self.windows.items() if h in alive and n not in skip]
        if not wins: return
        gap = max(300, self.cfg["afk_gap"])
        self.afk_busy = True
        self.afk_prev = (self.tv.get(), self.active)
        old = wt.POINT(); user32.GetCursorPos(ctypes.byref(old)); self.afk_cursor = (old.x, old.y)
        if self.tv.get() != "Viewer": self.tv.set("Viewer")
        steps = []
        for hw in wins:
            if hw == self.active and not force and user_idle_seconds() < 60: continue
            steps += [(700, lambda h=hw: self.switch_to(h)), (900, lambda h=hw: self.afk_aim(h)),
                      (300, self.afk_down), (150, self.afk_up), (gap, self.afk_down), (150, self.afk_up)]
        steps.append((600, self.afk_finish))
        self.log(f"Anti-AFK round started ({len(wins)} instances)")
        self.run_seq(steps)

    # Moves the cursor to the Anti-AFK click spot of a window (v28 or earlier).
    def afk_aim(self, hw):
        self.afk_hw = hw
        rc = wt.RECT(); user32.GetClientRect(hw, ctypes.byref(rc)); off = max(1, self.cfg["afk_off"])
        pt = wt.POINT(max(1, rc.right - off), max(1, rc.bottom - off)); user32.ClientToScreen(hw, ctypes.byref(pt))
        user32.SetCursorPos(pt.x, pt.y); self.afk_pt = pt

    # Presses the mouse only if the cursor is really over that game window (v28 or earlier).
    def afk_down(self):
        pt = self.afk_pt
        self.afk_pressed = bool(pt and self.afk_hw and user32.IsWindow(self.afk_hw)
                                and self.owner_of(user32.WindowFromPoint(pt)) == self.afk_hw)   # never click anything else
        if self.afk_pressed: user32.mouse_event(2, 0, 0, 0, 0)

    # Releases the mouse button after afk_down (v28 or earlier).
    def afk_up(self):
        if self.afk_pressed: user32.mouse_event(4, 0, 0, 0, 0); self.afk_pressed = False

    # Restores the previous tab, focused account and cursor after an Anti-AFK round (v28 or earlier).
    def afk_finish(self):
        prev_tab, prev_active = self.afk_prev
        if prev_active in self.live() and prev_active != self.active: self.switch_to(prev_active)
        if prev_tab != "Viewer": self.after(800, lambda: self.tv.set(prev_tab))
        user32.SetCursorPos(*self.afk_cursor)
        self.afk_busy = False
        self.log("Anti-AFK round done", "ok")

    # ---------- macros (added v41): saved click / hold / swipe / key sequences played on the real windows like Anti-AFK ----------
    # Selects a valid macro at startup and fills the Macros tab (added v41).
    def macro_init(self):
        if self.cfg["macro_sel"] not in self.cfg["macros"]: self.cfg["macro_sel"] = next(iter(self.cfg["macros"]), "")
        self.macro_refresh()

    # Fills the Macros tab from the config: macro menu, step text and run-on menu (added v41).
    def macro_refresh(self):
        sel = self.cfg["macro_sel"]
        self.mm.configure(values=list(self.cfg["macros"]) or ["-"]); self.mm.set(sel or "-")
        self.mt.delete("1.0", "end"); self.mt.insert("1.0", "\n".join(fmt_step(x) for x in self.cfg["macros"].get(sel, [])))
        self.macro_targets_refresh()

    # Refreshes the 'Run on' menu: focused account, all running accounts, or one account (added v41).
    def macro_targets_refresh(self):
        if not hasattr(self, "mg"): return
        vals = ["Focused account", "All running accounts"] + [a["name"] for a in self.cfg["accounts"]]
        if self.cfg["macro_target"] not in vals: self.cfg["macro_target"] = vals[0]
        self.mg.configure(values=vals); self.mg.set(self.cfg["macro_target"])

    # Macro menu handler (added v41).
    def macro_pick(self, name):
        self.cfg["macro_sel"] = name if name in self.cfg["macros"] else ""; self.macro_refresh()

    # Run-on menu handler (added v41).
    def macro_target_pick(self, v): self.cfg["macro_target"] = v

    # New button: empty editor; Save then asks for a name (added v41).
    def macro_new(self):
        self.cfg["macro_sel"] = ""; self.macro_refresh()

    # Parses the editor text and saves it under the selected name (asks for one when it is new) (added v41).
    def macro_save(self):
        steps, err = parse_macro(self.mt.get("1.0", "end"))
        if err: return self.note("Macro", err)
        if not steps: return self.note("Macro", "Nothing to save - record or type some steps first.")
        name = self.cfg["macro_sel"] or self.ask("Save macro", "Name for this macro:", default=f"Macro {len(self.cfg['macros']) + 1}")
        if not name or not name.strip(): return
        name = name.strip()[:40]; self.cfg["macros"][name] = steps; self.cfg["macro_sel"] = name
        self.macro_refresh(); self.log(f"Macro '{name}' saved ({len(steps)} steps)", "ok")

    # Deletes the selected macro after a confirmation (added v41).
    def macro_delete(self):
        sel = self.cfg["macro_sel"]
        if not sel: return
        if self.confirm("Delete macro", f"Delete the macro '{sel}'?", [("Delete", True), ("Cancel", None)]) is not True: return
        self.cfg["macros"].pop(sel, None); self.cfg["macro_sel"] = next(iter(self.cfg["macros"]), ""); self.macro_refresh()

    # Validates the macro hotkey entry, stores it and restarts the hotkey thread so it takes effect (added v41).
    def apply_macro_key(self):
        txt = self.v["macro_key"].get().strip().lower()
        if txt and not hotkey_spec(txt): return self.note("Macro hotkey", "Not a valid hotkey. Use e.g. ctrl+alt+m or F8 (modifiers: ctrl, shift, alt, win).")
        self.cfg["macro_key"] = txt; self.v["macro_key"].set(txt)
        if self.cfg["hotkeys"]: self.hotkeys(False); self.hotkeys(True)
        self.log(f"Macro hotkey: {txt or 'none'}" + ("" if self.cfg["hotkeys"] else " (turn Hotkeys on to use it)"))

    # Windows the macro runs on, from the 'Run on' menu (added v41).
    def macro_targets(self):
        alive, t = self.live(), self.cfg["macro_target"]
        if t == "Focused account": return [self.active] if self.active in alive else []
        if t == "All running accounts": return [h for h in self.windows.values() if h in alive]
        h = self.windows.get(t); return [h] if h in alive else []

    # Hotkey / button: starts the selected macro, or stops it when it is running (added v41).
    def macro_toggle(self):
        if self.macro_on or self.bg_job: self.macro_abort()          # (changed v42: also stops a background job)
        else: self.macro_start()

    # Starts the selected macro on its target accounts, one after another, like an Anti-AFK round (added v41; changed v42: steps / hws /
    # name can be given (the visual builder's Test uses that), on_done is called when the run ends, on_step(i) before each step in background
    # mode, 'Background input' posts everything to the windows instead of using the real mouse; returns True when a run was started).
    def macro_start(self, steps=None, hws=None, name=None, on_done=None, on_step=None):
        name = name or self.cfg["macro_sel"]; steps = steps or self.cfg["macros"].get(name)
        if self.afk_busy or self.rec: return self.say("Macro: wait until the Anti-AFK round / recorder is finished")
        if not steps: return self.say("Macro: select or record a macro first")
        hws = hws or self.macro_targets()
        if not hws: return self.say(f"Macro: no running account for '{self.cfg['macro_target']}'")
        self.collect(); loops = min(999, max(1, self.cfg["macro_loops"]))
        if self.cfg["macro_bg"]: return self.macro_start_bg(name, steps, hws, loops, on_step, on_done)
        if self.state() == "iconic": return self.say("Macro waiting: the manager is minimized")
        self.afk_busy = self.macro_on = True
        self.afk_prev = (self.tv.get(), self.active)
        old = wt.POINT(); user32.GetCursorPos(ctypes.byref(old)); self.afk_cursor = (old.x, old.y)
        if self.tv.get() != "Viewer": self.tv.set("Viewer")
        seq = []
        for hw in hws: seq += [(700, lambda h=hw: self.switch_to(h)), (400, lambda: None)] + self.macro_body(hw, steps) * loops
        seq.append((300, self.macro_finish))
        self.log(f"Macro '{name}' started on {len(hws)} account(s), {loops}x")
        self.macro_cb = on_done; self.macro_seq(seq, 0); return True

    # Runs a (delay, action) list one entry at a time; stops as soon as macro_on is cleared (added v41).
    def macro_seq(self, seq, i):
        if i >= len(seq): return
        d, fn = seq[i]
        # Runs one action, then schedules the next.
        def go():
            self._m_job = None
            try: fn()
            except Exception as ex: self.log(f"Macro error: {str(ex)[:70]}", "warn")
            if self.macro_on: self.macro_seq(seq, i + 1)
        self._m_job = self.after(d, go)

    # Stops a running macro right away (added v41).
    def macro_abort(self):
        if self.bg_job: self.bg_job["stop"].set(); return                # background job: its threads stop and bg_done reports it (added v42)
        if self._m_job: self.after_cancel(self._m_job); self._m_job = None
        self.macro_finish(); self.log("Macro stopped", "warn")

    # Releases mouse / keys, restores the previous tab, focused account and cursor (added v41).
    def macro_finish(self):
        if not self.macro_on: return
        self.macro_on = False; self.m_up(); self.m_keys(None, None, False)
        prev_tab, prev_active = self.afk_prev
        if prev_active in self.live() and prev_active != self.active: self.switch_to(prev_active)
        if prev_tab != "Viewer": self.after(800, lambda: self.tv.set(prev_tab))
        user32.SetCursorPos(*self.afk_cursor); self.afk_busy = False
        self.log("Macro done", "ok")
        cb, self.macro_cb = self.macro_cb, None
        if cb: cb()                                                      # (added v42)

    # Turns macro steps into (delay ms, action) pairs for one window; swipes become a series of small cursor moves (added v41).
    def macro_body(self, hw, steps):
        out = []
        for st in steps:
            t = st[0]
            if t == "wait": out.append((st[1], lambda: None))
            elif t == "key": out += [(100, lambda c=st[1]: self.m_keys(hw, c, True)), (70, lambda: self.m_keys(hw, None, False))]
            else:
                out += [(90, lambda a=st[1], b=st[2]: self.m_aim(hw, a, b)), (50, lambda r=st[-1] == "right": self.m_down(hw, r))]
                if t == "click": out.append((70, self.m_up))
                elif t == "hold": out.append((st[3], self.m_up))
                else:
                    x1, y1, x2, y2, ms = st[1:6]; n = max(2, min(40, ms // 25))
                    out += [(ms // n, lambda a=x1 + (x2 - x1) * k / n, b=y1 + (y2 - y1) * k / n: self.m_move(hw, a, b)) for k in range(1, n + 1)]
                    out.append((40, self.m_up))
        return out

    # Moves the real cursor to a fractional point of the window's client area (added v41).
    def m_aim(self, hw, fx, fy):
        if not user32.IsWindow(hw): return
        rc = wt.RECT(); user32.GetClientRect(hw, ctypes.byref(rc))
        pt = wt.POINT(int(fx * rc.right), int(fy * rc.bottom)); user32.ClientToScreen(hw, ctypes.byref(pt))
        self.m_pt = pt; user32.SetCursorPos(pt.x, pt.y)

    # Presses a mouse button only if the cursor is really over that game window (never clicks anything else) (added v41).
    def m_down(self, hw, right=False):
        pt = self.m_pt
        ok = bool(pt and user32.IsWindow(hw) and self.owner_of(user32.WindowFromPoint(pt)) == hw)
        self.m_held = (0x10 if right else 4) if ok else 0
        if ok: user32.mouse_event(8 if right else 2, 0, 0, 0, 0)

    # Moves the cursor while a button is held (swipe) (added v41).
    def m_move(self, hw, fx, fy):
        if self.m_held: self.m_aim(hw, fx, fy)

    # Releases the held mouse button, if any (added v41).
    def m_up(self):
        if self.m_held: user32.mouse_event(self.m_held, 0, 0, 0, 0); self.m_held = 0

    # Presses a key combo (down=True) only while the game window is in front, or releases what was pressed (down=False) (added v41).
    def m_keys(self, hw, combo, down):
        if not down:
            for v in reversed(self.m_kd): self.m_vk(v, True)
            self.m_kd = []; return
        vks = parse_combo(combo) or []
        if user32.GetForegroundWindow() != hw: self.give_focus(hw)
        if user32.GetForegroundWindow() != hw: return self.log(f"Macro: key '{combo}' skipped - the game window is not in front", "warn")
        self.m_kd = [v for v in vks if v in MODS] + [v for v in vks if v not in MODS]
        for v in self.m_kd: self.m_vk(v, False)

    # One key event by virtual-key code (added v41).
    def m_vk(self, v, up):
        user32.keybd_event(v, user32.MapVirtualKeyW(v, 0), (1 if v in EXT_KEYS else 0) | (2 if up else 0), 0)

    # Recorder button: shows the Viewer, then opens the see-through recording layer over the focused window (added v41).
    def macro_record(self):
        hw = self.active
        if self.builder: return self.say("Recorder: close the visual builder first")
        if self.rec or self.macro_on or self.afk_busy or hw not in self.live(): return self.say("Recorder: focus a running account in the Viewer first")
        self.tv.set("Viewer"); self.after(400, lambda: self.rec_open(hw))

    # The recording layer: a see-through window exactly over the game's client area. Click = click, press 0.5 s+ = hold,
    # drag = swipe (right button = right click), typed keys / combos = key steps, gaps become wait steps; the toolbar has
    # Done / Undo / Cancel (added v41).
    def rec_open(self, hw):
        if self.rec or not user32.IsWindow(hw): return
        rc = wt.RECT(); user32.GetClientRect(hw, ctypes.byref(rc)); org = wt.POINT(0, 0); user32.ClientToScreen(hw, ctypes.byref(org))
        cw, ch = max(rc.right, 50), max(rc.bottom, 50)
        top = self.rec = tk.Toplevel(self); top.overrideredirect(True); top.attributes("-topmost", True); top.attributes("-alpha", 0.45)
        top.geometry(f"{cw}x{ch}+{org.x}+{org.y}"); top.configure(bg="#0b1020")
        cv = tk.Canvas(top, bg="#0b1020", highlightthickness=0, cursor="crosshair"); cv.pack(fill="both", expand=True)
        st = {"steps": [], "undo": [], "press": None, "last": 0.0, "n": 0, "tmp": None}
        bar = tk.Frame(top, bg="#000000"); bar.place(x=8, y=8)
        info = tk.Label(bar, text="0 steps", width=9, bg="#000000", fg="#ffffff", font=("Segoe UI", 10)); info.pack(side="left")

        # Draws a numbered circle (hold = thick ring) and returns its canvas ids.
        def dot(x, y, n=None, ring=False):
            ids = [cv.create_oval(x - 22, y - 22, x + 22, y + 22, fill="#3b8ee8", outline="#cfe6ff", width=5 if ring else 2)]
            if n is not None: ids.append(cv.create_text(x, y, text=str(n), fill="#ffffff", font=("Segoe UI Semibold", 13)))
            return ids

        # Stores one recorded step (with a wait step for a pause of 0.3 s or more before it) and remembers how to undo it.
        def push(step, t0, ids):
            added = 1
            if st["last"] and t0 - st["last"] >= 0.3: st["steps"].append(["wait", min(60000, round((t0 - st["last"]) * 20) * 50)]); added = 2
            st["steps"].append(step); st["undo"].append((added, ids)); st["last"] = time.time(); info.configure(text=f"{len(st['steps'])} steps")

        # Mouse press: remembers where and when.
        def down(e): st["press"] = (e.x, e.y, time.time(), "right" if e.num == 3 else "left")

        # Mouse drag: shows the swipe line while the left button is held.
        def drag(e):
            if not st["press"]: return
            if st["tmp"]: cv.delete(st["tmp"])
            st["tmp"] = cv.create_line(st["press"][0], st["press"][1], e.x, e.y, fill="#3b8ee8", width=30, capstyle="round")

        # Mouse release: turns the gesture into a click, hold or swipe step.
        def up(e):
            p, st["press"] = st["press"], None
            if st["tmp"]: cv.delete(st["tmp"]); st["tmp"] = None
            if not p: return
            x0, y0, t0, btn = p; ms = int((time.time() - t0) * 1000)
            f = lambda v, m: min(1.0, max(0.0, round(v / m, 4)))
            st["n"] += 1; n = st["n"]
            if btn == "left" and (e.x - x0) ** 2 + (e.y - y0) ** 2 > 196:
                ids = [cv.create_line(x0, y0, e.x, e.y, fill="#3b8ee8", width=30, capstyle="round")] + dot(x0, y0, n) + dot(e.x, e.y)
                push(["swipe", f(x0, cw), f(y0, ch), f(e.x, cw), f(e.y, ch), max(100, min(3000, round(ms / 50) * 50))], t0, ids)
            elif btn == "left" and ms >= 500: push(["hold", f(x0, cw), f(y0, ch), round(ms / 50) * 50, "left"], t0, dot(x0, y0, n, True))
            else: push(["click", f(x0, cw), f(y0, ch), btn], t0, dot(x0, y0, n))

        # Key press: records a key or combo (ctrl / shift / alt + key).
        def keys(e):
            ks = e.keysym.lower()
            if ks.endswith(("_l", "_r", "_lock")): return
            name = {"return": "enter", "escape": "esc", "prior": "pageup", "next": "pagedown"}.get(ks, ks)
            if key_vk(name) is None: return
            mods = [m for m, bit in (("ctrl", 0x4), ("shift", 0x1), ("alt", 0x20000)) if e.state & bit]
            push(["key", "+".join(mods + [name])], time.time(), [])
            info.configure(text="key " + "+".join(mods + [name])[:14])

        # Removes the last recorded action (and its wait) from the list and the picture.
        def undo():
            if not st["undo"]: return
            k, ids = st["undo"].pop(); del st["steps"][-k:]; st["last"] = 0.0
            for i in ids: cv.delete(i)
            info.configure(text=f"{len(st['steps'])} steps")

        # Closes the layer; Done keeps the steps and asks for a name.
        def close(save):
            self.rec = None; steps = st["steps"]; top.destroy()
            if save and steps: self.after(50, lambda: self.rec_save(steps))

        for t, cmd in (("Done", lambda: close(True)), ("Undo", undo), ("Cancel", lambda: close(False))):
            b = tk.Label(bar, text=t, bg="#1e2024", fg="#ececee", padx=10, pady=5, cursor="hand2", font=("Segoe UI Semibold", 10))
            b.pack(side="left", padx=(6, 0)); b.bind("<Button-1>", lambda e, c=cmd: c())
        for ev, fn in (("<ButtonPress-1>", down), ("<ButtonPress-3>", down), ("<B1-Motion>", drag), ("<ButtonRelease-1>", up), ("<ButtonRelease-3>", up)):
            cv.bind(ev, fn)
        top.bind("<KeyPress>", keys); top.after(100, top.focus_force); top.after(120, cv.focus_set)

    # Saves a recorded step list under a name asked in-app and opens it in the Macros tab (added v41).
    def rec_save(self, steps):
        name = self.ask("Save macro", f"Name for the recorded macro ({len(steps)} steps):", default=f"Macro {len(self.cfg['macros']) + 1}")
        if not name or not name.strip(): return
        name = name.strip()[:40]; self.cfg["macros"][name] = steps[:500]; self.cfg["macro_sel"] = name
        self.macro_refresh(); self.tv.set("Macros"); self.log(f"Macro '{name}' recorded ({len(steps)} steps)", "ok")

    # ---------- background input and visual builder (added v42) ----------
    # Anti-AFK round without moving the cursor or taking focus: every selected window gets a posted click in its corner, a pause and a second
    # click, all windows at once; the focused window is skipped while you are using it, like in the normal round (added v42).
    def afk_bg_round(self, force=False):
        if self.bg_job: return self.say("Anti-AFK: a background job is still running") if force else None
        alive, skip = self.live(), set(self.cfg["afk_skip"])
        wins = [h for n, h in self.windows.items() if h in alive and n not in skip
                and not (h == self.active and not force and user_idle_seconds() < 60)]
        if not wins: return
        off, gap, wake = max(1, self.cfg["afk_off"]), max(300, self.cfg["afk_gap"]), self.cfg["bg_wake"]
        # Worker thread body for one window: click near the bottom-right corner, pause, click again (no Tk, no self.windows).
        def work(hw, stop):
            w, h = client_size(hw); fx, fy = max(0.0, (w - off) / max(w, 1)), max(0.0, (h - off) / max(h, 1))
            bg_play(hw, [["click", fx, fy, "left"], ["wait", gap], ["click", fx, fy, "left"]], stop, wake)
        self.log(f"Anti-AFK round started in the background ({len(wins)} instances)")
        self.bg_start("Anti-AFK round", wins, work)

    # Starts one background job: a coordinator thread runs worker(hw, stop) in one thread per window, waits for all of them and hands the
    # result to the main thread (bg_done). self.bg_job["stop"] (an Event) stops everything (added v42).
    def bg_start(self, label, hws, worker, on_done=None):
        stop = threading.Event(); self.bg_job = {"stop": stop, "label": label, "cb": on_done}
        # Coordinator thread body (see bg_start).
        def run():
            # One worker thread: errors go to the log, never to a Tk widget.
            def one(h):
                try: worker(h, stop)
                except Exception as ex: self.log(f"{label}: error {str(ex)[:70]}", "warn")
            ts = [threading.Thread(target=one, args=(h,), daemon=True) for h in hws]
            for t in ts: t.start()
            for t in ts: t.join()
            self.after(0, lambda: self.bg_done(stop.is_set()))
        threading.Thread(target=run, daemon=True).start()

    # Main thread: a background job has ended; logs it, frees the slot and calls the job's callback (added v42).
    def bg_done(self, stopped):
        job, self.bg_job = self.bg_job, None
        if not job: return
        self.log(f"{job['label']} {'stopped' if stopped else 'done'}", "warn" if stopped else "ok")
        if job["cb"]: job["cb"]()

    # Runs a macro with posted messages on all target windows at once; True when started (added v42).
    def macro_start_bg(self, name, steps, hws, loops, on_step=None, on_done=None):
        if self.bg_job: self.say("Macro: a background job is still running - press the macro hotkey to stop it"); return False
        wake, one = self.cfg["bg_wake"], len(hws) == 1
        self.log(f"Macro '{name}' started in the background on {len(hws)} account(s), {loops}x")
        self.bg_start(f"Macro '{name}'", hws, lambda h, stop: bg_play(h, steps, stop, wake, loops, on_step if one else None), on_done)
        return True

    # 'Visual builder' button: shows the Viewer, then opens the builder over the focused window (added v42).
    def builder_open(self):
        if self.builder: self.tv.set("Viewer"); return self.builder.front()
        if self.bld_wait: return
        if self.rec or self.macro_on or self.afk_busy or self.bg_job: return self.say("Builder: wait until the recorder / macro / Anti-AFK round is finished")
        if self.active not in self.live(): return self.say("Builder: focus a running account in the Viewer first")
        self.bld_wait = True; self.tv.set("Viewer")
        # Runs 0.4 s after the tab switch so the focused window is in place; opens the builder with the selected macro.
        def go():
            self.bld_wait = False
            if self.builder or self.active not in self.live(): return
            name = self.cfg["macro_sel"]
            try: MacroBuilder(self, name if name in self.cfg["macros"] else "", self.cfg["macros"].get(name, []))
            except Exception as ex:
                self.log(f"Visual builder failed to open: {str(ex)[:80]}", "warn")
                if self.builder: self.builder.close(False)
        self.after(400, go)

    # ---------- Discord alerts (added v41) ----------
    # Asks for the bot token in-app and stores it DPAPI-encrypted (added v41).
    def dc_token(self):
        tok = self.ask("Discord bot token", "Paste the bot token (an empty entry removes it):", secret=True)
        if tok is None: return
        self.cfg["dc_token"] = enc(tok.strip()) if tok.strip() else ""
        self.dc_lab.configure(text="Token: set" if self.cfg["dc_token"] else "Token: not set")

    # Send test button (added v41).
    def dc_test(self):
        self.collect(); threading.Thread(target=self.discord_send, args=("[Better RAM] test message - alerts work", True), daemon=True).start()

    # Queues one alert from a short background thread; the same text is skipped for 60 s (added v41).
    def notify(self, msg):
        now = time.time()
        if now - self.dc_seen.get(msg, 0) < 60: return
        self.dc_seen[msg] = now
        threading.Thread(target=self.discord_send, args=(f"[Better RAM] {msg}",), daemon=True).start()

    # Posts a message to the configured channel with the bot token (Discord REST, one retry on rate limit); runs in a thread.
    # test=True reports the result in an in-app note, otherwise failures go to the log as warnings (added v41).
    def discord_send(self, text, test=False):
        msg, ok = "Message sent - check your Discord channel.", True
        try:
            tok = dec(self.cfg["dc_token"]) if self.cfg["dc_token"] else ""; ch = self.cfg["dc_chan"].strip()
            if not tok or not ch.isdigit(): raise ValueError("set the channel ID (digits only) and the bot token first")
            for _ in range(2):
                r = requests.post(f"https://discord.com/api/v10/channels/{ch}/messages", headers={"Authorization": f"Bot {tok}"},
                                  json={"content": text[:1900]}, timeout=10)
                if r.status_code != 429: break
                time.sleep(min(10.0, float(r.json().get("retry_after", 1))))
            r.raise_for_status()
        except Exception as ex: msg, ok = f"Discord alert failed: {str(ex)[:100]}", False
        if test: self.after(0, lambda: self.note("Discord", msg))
        elif not ok: self.log(msg, "warn")

    # Background thread: runs the automatic RAM trim and starts the scheduled Anti-AFK rounds on their timers (v28 or earlier).
    def maintenance(self):
        last_trim = time.time()
        while True:
            time.sleep(2); now = time.time()
            try:
                if self.cfg["trim"] and now - last_trim >= max(10, self.cfg["trim_sec"]):
                    last_trim = now; self.do_trim()
                if self.cfg["afk"] and now >= self.afk_next:
                    self.afk_next = now + max(1, self.cfg["afk_min"]) * 60; self.after(0, self.start_afk)
            except Exception as ex:
                self.log(f"Maintenance error: {str(ex)[:60]}", "warn")

    # ---------- self-update ----------
    def check_update_now(self):
        self.collect(); threading.Thread(target=self.check_update, args=(True,), daemon=True).start()

    def check_update(self, manual=False):
        """Download the file behind the update link; install it only if it is valid and has a higher VERSION."""
        url = self.cfg["update_url"].strip() or UPDATE_URL
        if not url.lower().startswith("https://"):
            if manual: self.after(0, lambda: self.note("Updates", "Enter an https:// update link in Settings first."))
            return
        try:
            url = re.sub(r"^https://github\.com/([^/]+/[^/]+)/blob/", r"https://raw.githubusercontent.com/\1/", url)   # web-page link -> raw file
            r = requests.get(url, timeout=10); r.raise_for_status()
            text = r.content.decode("utf-8")
            if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")): raise ValueError("link is a web page, not the raw file")
            m = re.search(r"^VERSION\s*=\s*(\d+)", text, re.M)
            if not m or "class App" not in text or not 5000 < len(text) < 2_000_000: raise ValueError("link is not a Better RAM file")
            compile(text, "update", "exec")                       # never install something that doesn't even parse
            new = int(m.group(1))
            if new <= VERSION:
                if manual: self.log(f"Up to date (v{VERSION})", "ok")
                return
            path = os.path.abspath(__file__)
            shutil.copy2(path, path + ".bak")                     # one-step rollback: rename .bak back to .py
            with open(path + ".new", "w", encoding="utf-8", newline="") as fh: fh.write(text)
            os.replace(path + ".new", path)
            self.log(f"Update v{new} installed - restart to use it", "ok")
            self.after(0, lambda: self.offer_restart(new))
        except Exception as ex:
            self.log(f"Update check failed: {str(ex)[:80]}", "warn")

    # Asks whether to restart after an update was installed (v28 or earlier).
    def offer_restart(self, new):
        n = len(self.live())
        msg = f"Better RAM v{new} was downloaded and installed.\n\nRestart now to use it?"
        if n: msg += f"\n\n{n} Roblox window(s) will be released to the desktop (not closed)."
        if self.confirm("Update installed", msg, [("Restart", True), ("Later", False)]): self.restart()

    # Restarts the app (used after an update) (v28 or earlier).
    def restart(self):
        self.save()
        subprocess.Popen([sys.executable, os.path.abspath(__file__)], creationflags=0x00000008)   # DETACHED_PROCESS
        self.log("Restarting for update"); self.hotkeys(False); self.unembed_all(); self.destroy()

    # ---------- exit ----------
    def on_exit(self):
        if self.modal:                                       # the window's X while a prompt is open closes the prompt first
            if self.cancel: self.cancel()
            return
        if self.windows:
            ans = self.confirm("Close Better RAM",
                "Close the Roblox instances too?\n\nClose them = shut every Roblox window\nRelease = leave them open on the desktop",
                [("Close them", True), ("Release", False), ("Cancel", None)])
            if ans is None: return
            if ans:
                for hw in list(self.windows.values()): kill_pid(pid_of(hw))
        self.save(); self.log("Better RAM closed")
        if self.bg_job: self.bg_job["stop"].set(); time.sleep(0.2)       # lets running workers release held keys / buttons (added v42)
        self.hotkeys(False); self.unembed_all(); self.destroy()

if __name__ == "__main__":
    App().mainloop()
