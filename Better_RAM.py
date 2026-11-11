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
#  v43  Builder and recorder are ONE feature (the Record button is gone): three non-activating layers - numbered step widgets over the focused
#       window, the numbered step list over the tile area, all buttons over the Anti-AFK strip - that follow the app with the docked window's
#       timing (track_dock); recording is a mode of the builder. Macro per account (list on the Macros screen, cfg macro_map) replaces 'Run on';
#       New / Save / the text editor are gone; Run forever; End = panic button (also the macro hotkey while something runs); the macro hotkey is
#       three pickers (modifier / modifier / key, '_' = blank). Discord: custom alert text, custom commands (answered by polling the channel),
#       setup tutorial link. Removed dead code: system GPU total, parse_macro / fmt_step, the old recorder
#  v44  Log: the same warning at most once per 30 s, re-dock warning once a minute, the log no longer jumps to the bottom while you scroll.
#       Builder layers hide while another program is in front. Anti-AFK always runs in the background (posted clicks: no cursor, no focus, works
#       minimized / on any tab / during a macro; own job slot + per-window input lock; real-mouse round removed). Smooth builder circles and
#       swipe lines (sprite). Key step and Change read a real key press (capture). Macro hotkey key = button + searchable list (confirm choices).
#       Recorder reads the real mouse and keys (rec_poll), the game stays clickable while recording.
# =====================================================================================================================
import atexit, base64, ctypes, ctypes.wintypes as wt, json, os, random, re, shutil, socket, stat, struct, subprocess, sys, tempfile, threading, time, webbrowser
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

VERSION = 49                       # bump this in the file you publish; running copies update when it is higher
UPDATE_URL = "https://raw.githubusercontent.com/br0dax457-droid/Better-RAM/main/Better_RAM.py"   # built-in update link
DC_TUTORIAL = "https://docs.discord.com/developers/quick-start/getting-started"   # Discord's own guide: create the app + bot, copy the token, install it (added v43)

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
            "gfx": True, "gfx_lock": True, "hideui": True, "bare": True, "fps": 15, "quality": 1, "mute": True,
            "trim": True, "trim_sec": 90, "lowprio": True,
            "afk": False, "afk_min": 8, "afk_off": 8, "afk_gap": 1200,
            "watch": True, "watch_sec": 60, "auto_rejoin": False, "afk_skip": [], "idle_prio": [], "view_order": [],
            "update_url": "", "auto_update": True, "hotkeys": True, "compact": False, "perf": False,
            "join_mode": "game", "join_user": "", "users": [],
            "anim": True, "animMs": 160,
            "macros": {}, "macro_sel": "", "macro_map": {}, "macro_loops": 1, "macro_forever": False, "macro_key": "ctrl+alt+m",
            "dc_on": False, "dc_chan": "", "dc_token": "", "dc_fmt": "[Better RAM] {msg}", "dc_cmd_on": False, "dc_prefix": "!",
            "dc_cmds": [["status", "Running {running}/{total} - frozen {frozen}, disconnected {disc}, crashed {crashed}"],
                        ["accounts", "Running: {accounts}"], ["help", "Commands: {commands}"]],
            "afk_bg": False, "macro_bg": False, "bg_wake": True}
STR_KEYS = {"place", "update_url", "join_user", "dc_chan", "dc_fmt", "dc_prefix"}
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
    """-> ({pid: gpu %}, {pid: dedicated VRAM bytes} or None) or None when the counters are unavailable."""
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
            per = {}
            for name, status, val in rows:
                m = _GPU_RE.search(name)
                if not m or status not in (0, 1): continue
                pid, adapter, eng = int(m.group(1)), (m.group(2), m.group(3)), m.group(4).lower()
                v = max(0.0, val)
                per[(pid, adapter, eng)] = per.get((pid, adapter, eng), 0.0) + v
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
            return {p: min(100.0, v) for p, v in by_pid.items()}, vram
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

# Sets only the few keys it needs (FPS cap, quality, mute, window frame, leaderboard/chat closed) and leaves every other line of Roblox's
# settings file exactly as it is: same line endings, no rewrite when nothing changes, one-time backup (.bak). Optionally read-only after.
# Optional extras for "bare bones": switched off/quiet only when Roblox already wrote the key (never invented) (added v48).
BARE = [("bool", "ChatTranslationEnabled", "false"), ("bool", "BadgeVisible", "false"), ("bool", "PlayerNamesEnabled", "false"),
        ("bool", "VignetteEnabled", "false"), ("bool", "VignetteEnabledCustomOption", "false"), ("bool", "ReducedMotion", "true"),
        ("bool", "AllTutorialsDisabled", "true"), ("bool", "UiNavigationKeyBindEnabled", "false"), ("float", "HapticStrength", "0"),
        ("bool", "PerformanceStatsVisible", "false"), ("bool", "OnScreenProfilerEnabled", "false"),
        ("bool", "MicroProfilerWebServerEnabled", "false"), ("bool", "MaxQualityEnabled", "false")]
BARE_MUTE = [("float", "PartyVoiceVolume", "0"), ("float", "VoiceChatVolume", "0")]

def apply_graphics(fps, quality, mute, lock=True, hide_ui=True, bare=False):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    if os.path.exists(SETTINGS):
        unlock_settings()
        with open(SETTINGS, encoding="utf-8", newline="") as fh: old = xml = fh.read()
        bak = SETTINGS + ".bak"
        if "UserGameSettings" in old and not os.path.exists(bak):
            try: shutil.copyfile(SETTINGS, bak)
            except Exception: pass
    else:
        old, xml = None, SKELETON
    wanted = [("int", "FramerateCap", fps), ("int", "GraphicsQualityLevel", quality),
              ("token", "SavedQualityLevel", quality), ("bool", "Fullscreen", "false"), ("bool", "StartMaximized", "false")]
    if mute: wanted.append(("float", "MasterVolume", "0"))
    if hide_ui: wanted += [("bool", "PlayerListVisible", "false"), ("bool", "ChatVisible", "false")]
    if bare:
        for tag, name, val in BARE + (BARE_MUTE if mute else []):
            if re.search(rf'<(?:token|int|float|bool)\s+name="{name}">', xml): wanted.append((tag, name, val))
    for tag, name, val in wanted:
        pat = rf'(<(?:token|int|float|bool)\s+name="{name}">)[^<]*(</)'
        if re.search(pat, xml): xml = re.sub(pat, lambda m: m.group(1) + str(val) + m.group(2), xml, count=1)
        else: xml = xml.replace("</Properties>", f'<{tag} name="{name}">{val}</{tag}></Properties>', 1)
    if xml != old:                                       # untouched file stays byte-for-byte the same
        with open(SETTINGS, "w", encoding="utf-8", newline="") as fh: fh.write(xml)
    # read-only is the default (every launched instance rewrites this file); turn it off only to let Roblox save window state
    os.chmod(SETTINGS, stat.S_IREAD if lock else stat.S_IREAD | stat.S_IWRITE)

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
    return (sum({bits[v] for v in vks if v in bits}), main[0]) if len(main) == 1 else None

# Virtual-key code -> key name of every key the builder can record: a-z, 0-9, F1-F24 and the named keys of KEYMAP (canonical name first) (added v43).
REC_KEYS = {**{ord(c.upper()): c for c in "abcdefghijklmnopqrstuvwxyz0123456789"}, **{0x6F + i: f"f{i}" for i in range(1, 25)},
            **{v: k for k, v in reversed(list(KEYMAP.items())) if v not in MODS}}

# Modifier virtual-key code -> name, and every key the builder can capture or record.
MOD_NAMES = {0x11: "ctrl", 0x10: "shift", 0x12: "alt", 0x5B: "win"}
CAP_KEYS = {**REC_KEYS, **MOD_NAMES}

# Choices of the macro hotkey pickers: the first two boxes hold a modifier or '_' (blank), the third box the key (added v43).
HK_MODS = ["_", "ctrl", "shift", "alt", "win"]
HK_PICK = [*"abcdefghijklmnopqrstuvwxyz0123456789", *[f"f{i}" for i in range(1, 13)], "space", "enter", "tab", "esc", "backspace", "delete",
           "insert", "home", "end", "pageup", "pagedown", "left", "up", "right", "down"]

# 'ctrl+alt+m' -> ['ctrl', 'alt', 'm']; 'k' -> ['_', '_', 'k'] ('_' = blank picker); at most two modifiers are shown (added v43).
def hotkey_parts(text):
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    mods = [p for p in parts[:-1] if p in HK_MODS][:2]
    return mods + ["_"] * (2 - len(mods)) + [parts[-1] if parts else "f8"]

# Replaces {name} placeholders in a text from a dict; an unknown placeholder stays as typed (added v43).
def fill(text, vals): return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), text)

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

INPUT_LOCKS, WAKES, WAKE_LOCK = {}, {}, threading.Lock()

def input_lock(hw):
    """One lock per game window: a click, swipe or key press is never mixed with the one of another job (macro + Anti-AFK)."""
    return INPUT_LOCKS.setdefault(hw, threading.Lock())

def wake_count(hw, d):
    """Counts the jobs that told a window it is active (+1 / -1) and returns the new count, so the last job to finish undoes it."""
    with WAKE_LOCK:
        n = WAKES.get(hw, 0) + d
        if n > 0: WAKES[hw] = n
        else: WAKES.pop(hw, None)
        return max(n, 0)

def bg_step(hw, st, stop):
    """Plays ONE macro step on a window with posted messages. A pause does not hold the window's input lock; everything else does.
    Whatever it pressed is released again, also when `stop` is set Split out of bg_play."""
    t = st[0]
    if t == "wait": stop.wait(st[1] / 1000); return
    with input_lock(hw):
        if t == "key":
            vks = parse_combo(st[1]) or []; keys = [v for v in vks if v in MODS] + [v for v in vks if v not in MODS]
            try:
                for v in keys: bg_key(hw, v, False)
                stop.wait(0.08)
            finally:
                for v in reversed(keys): bg_key(hw, v, True)
            stop.wait(0.05)
        elif t == "swipe":
            x1, y1 = bg_pt(hw, st[1], st[2]); x2, y2 = bg_pt(hw, st[3], st[4]); ms = st[5]; k = max(2, min(40, ms // 25)); at = (x1, y1)
            bg_mouse(hw, WM_MOUSEMOVE, x1, y1); stop.wait(0.03)
            bg_mouse(hw, WM_LBUTTONDOWN, x1, y1, 1)
            try:
                for j in range(1, k + 1):
                    stop.wait(ms / 1000 / k)
                    if stop.is_set(): break
                    at = (x1 + (x2 - x1) * j // k, y1 + (y2 - y1) * j // k); bg_mouse(hw, WM_MOUSEMOVE, at[0], at[1], 1)
            finally: bg_mouse(hw, WM_LBUTTONUP, at[0], at[1], 0)
            stop.wait(0.04)
        else:
            x, y = bg_pt(hw, st[1], st[2])
            bg_click(hw, x, y, stop, st[-1] == "right", max(0.06, st[3] / 1000) if t == "hold" else 0.06)

# Plays macro steps (the builder's format) on one window with posted messages only; runs in a worker thread and never touches Tk.
# on_step(i) is called before each step; wake = send the fake activation while the window is not in front; loops=None repeats until `stop`
# is set (added v42; changed v43: loops=None = run forever; changed v44: steps run in bg_step, the fake activation is counted so a macro and
# Anti-AFK can use the same window at the same time).
def bg_play(hw, steps, stop, wake=True, loops=1, on_step=None):
    woke = wake and user32.GetForegroundWindow() != hw
    if woke and wake_count(hw, 1) == 1: bg_wake(hw, True)
    try:
        n = 0
        while loops is None or n < loops:
            n += 1
            for i, st in enumerate(steps):
                if stop.is_set() or not user32.IsWindow(hw): return
                if on_step: on_step(i)
                bg_step(hw, st, stop)
            if stop.wait(0.05): return                       # also keeps a forever loop of zero-length steps from spinning
    finally:
        if woke and wake_count(hw, -1) == 0 and user32.IsWindow(hw) and user32.GetForegroundWindow() != hw: bg_wake(hw, False)

# Makes a Tk top-level window non-activating: clicking it never takes the keyboard focus from the game or any other program (added v42).
def no_activate(win):
    hw = user32.GetAncestor(win.winfo_id(), 2)
    ex = user32.GetWindowLongPtrW(hw, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hw, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    user32.SetWindowPos(hw, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

SPRITES, LINES, RIM = {}, {}, "#0c1322"

def sprite(d, fill, edge, ew, ring=False):
    """Smooth filled circle for the builder as a Tk image: drawn 4x bigger and shrunk (anti-aliased), with a dark 2 px rim - the rim is
    nearly the see-through colour, so the soft edge blends away instead of showing a halo - and a faint top gloss. d = size in px,
    ew = outline width, ring = white inner ring (hold step). Cached per look."""
    key = (d, fill, edge, ew, ring)
    if key not in SPRITES:
        from PIL import Image, ImageDraw, ImageTk
        S = 4; big = d * S; rim = 2 * S; e = rim + ew * S
        im = Image.new("RGBA", (big, big), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        dr.ellipse((0, 0, big - 1, big - 1), fill=RIM)
        dr.ellipse((rim, rim, big - 1 - rim, big - 1 - rim), fill=edge)
        if big - 1 - e > e: dr.ellipse((e, e, big - 1 - e, big - 1 - e), fill=fill)
        if ring: r = (d // 2 - 9) * S; c = big // 2; dr.ellipse((c - r, c - r, c + r, c + r), outline="#ffffff", width=2 * S)
        gl = Image.new("RGBA", (big, big), (0, 0, 0, 0)); ImageDraw.Draw(gl).ellipse((big * .2, e, big * .8, big * .52), fill=(255, 255, 255, 38))
        im = Image.alpha_composite(im, gl).resize((d, d), Image.LANCZOS)
        SPRITES[key] = ImageTk.PhotoImage(Image.alpha_composite(Image.new("RGBA", (d, d), (1, 2, 3, 255)), im).convert("RGB"))
    return SPRITES[key]

def line_sprite(dx, dy, col, w=8):
    """Smooth rounded line (with the same dark rim) from (0, 0) to (dx, dy) as one Tk image -> (image, (ox, oy)): put it at the start point minus
    (ox, oy), anchor nw. Cached; the cache is emptied when it grows (lines change while a swipe is dragged)."""
    key = (dx, dy, col, w)
    if key not in LINES:
        from PIL import Image, ImageDraw, ImageTk
        if len(LINES) > 40: LINES.clear()
        pad = w + 4; W, H = abs(dx) + 2 * pad, abs(dy) + 2 * pad; S = 3 if W * H < 600000 else 1
        a = (pad if dx >= 0 else W - pad, pad if dy >= 0 else H - pad); b = (a[0] + dx, a[1] + dy)
        im = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
        for width, c in ((w + 4, RIM), (w, col)):
            r = width * S / 2; p, q = (a[0] * S, a[1] * S), (b[0] * S, b[1] * S)
            dr.line([p, q], fill=c, width=int(width * S))
            for x, y in (p, q): dr.ellipse((x - r, y - r, x + r, y + r), fill=c)
        im = im.resize((W, H), Image.LANCZOS)
        LINES[key] = (ImageTk.PhotoImage(Image.alpha_composite(Image.new("RGBA", (W, H), (1, 2, 3, 255)), im).convert("RGB")), a)
    return LINES[key]

# ======================= Visual macro builder (added v42; v43: merged with the recorder, three layers) =======================
# One feature, three floating windows that never take focus. App.track_dock calls follow(), so they follow the app with the same timing
# as the docked focused window (200 ms idle, 10 ms while the manager is being moved):
#   ov  see-through layer exactly over the focused game window: one numbered, draggable widget per click / hold / swipe step; it catches the
#       mouse only while a step is being placed or recorded (colour key = empty areas are click-through, the game stays usable)
#   ls  layer over the tile area (the unfocused accounts): the numbered list of every step in order, same numbers as on the focused window
#   st  layer over the Anti-AFK strip of the Viewer: all buttons ([+] [-] up / down, undo, record, test, load / save, input mode, ...)
# Positions are fractions of the window, so a macro built here runs on any account. Recording (click, hold, swipe, keys / combos, pauses
# -> wait steps) is a mode of the builder; recorded steps are the same numbered widgets. All layers hide while the Viewer is not showing,
# the manager is minimized or an in-app prompt is open, and are destroyed when the builder closes.
class MacroBuilder:
    KEY = "#010203"                                         # colour key: pixels of this colour are see-through AND click-through
    COL = {"click": "#3b8ee8", "hold": "#f0a030", "swipe": "#5fd38d"}
    R = 20                                                  # widget radius (px)
    HINT = "Drag a circle to move it  -  right-click it to delete"

    # Creates the three layers over the focused window and shows the given macro; sets app.builder (added v42; changed v43: three layers).
    def __init__(self, app, name, steps):
        app.builder = self
        self.app, self.name = app, name
        self.steps, self.hist = json.loads(json.dumps(steps)), []
        self.hw, self.rect = app.active, None
        self.sel = self.arm = self.run_i = self.pstart = self.dragging = self.pick = self.rec_job = None
        self.hits, self.layers, self.rects, self.shown, self.last_err = [], {}, {}, {}, ""
        self.alive, self.hidden, self.ov_off = True, False, False
        self.dirty = self.running = self.moved = self.rec = False
        self.rec_last, self.rec_down = 0.0, set()
        self.gone = 0.0                                     # since when another program has been in front (0 = none)
        self.cap = self.cap_job = None                      # key capture in progress
        self.rec_btn = set()                                # mouse buttons that were down at the last recording tick
        fg = user32.GetForegroundWindow()
        self.mk_overlay(); self.mk_steps(); self.mk_bar()
        for w in self.layers.values(): w.update_idletasks(); no_activate(w)
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

    def in_front(self):
        """True while the manager, the focused game window or one of these layers is the window in front."""
        fg = user32.GetForegroundWindow()
        if not fg: return False
        top = self.app.top_hwnd()
        return fg in {top, self.hw, *(user32.GetAncestor(w.winfo_id(), 2) for w in self.layers.values())} or user32.GetAncestor(fg, 3) == top

    def away(self):
        """True once another program has been in front for 0.3 s: the layers must not float over it."""
        if self.in_front(): self.gone = 0.0; return False
        self.gone = self.gone or time.time()
        return time.time() - self.gone > 0.3

    # Screen rectangle (x, y, w, h) of each layer that should be showing: the focused window's client area, the tile area (only when
    # there is one: 2+ running accounts) and the Anti-AFK strip. A layer that must hide is missing from the result;
    # force = ignore the hide rules (used while the layers are created) (added v43; changed v44: hidden while another program is in front).
    def layout(self, live, force=False):
        app = self.app
        if not force and (self.hidden or app.modal or app.state() == "iconic" or app.tv.get() != "Viewer" or self.away()): return {}
        out = {}
        m = self.measure() if self.hw in live and user32.IsWindowVisible(self.hw) and not app.unfocused else None
        if m and m[2] > 40 and m[3] > 40 and not self.ov_off: out["ov"] = m
        tw = app.dock_local[0] if app.dock_local and not app.unfocused else 0   # the focused window starts where the tile area ends
        if tw >= 150: out["ls"] = (app.stage.winfo_rootx(), app.stage.winfo_rooty(), tw, app.stage.winfo_height())
        b = app.sbar; out["st"] = (b.winfo_rootx(), b.winfo_rooty(), b.winfo_width(), b.winfo_height())
        return out

    # Creates one borderless, topmost, semi-transparent window at its current layout rectangle (added v43).
    def mk_layer(self, key, bg, alpha):
        r = self.layout(self.app.live(), True).get(key) or (0, 0, 300, 120)
        w = self.layers[key] = tk.Toplevel(self.app); w.overrideredirect(True); w.attributes("-topmost", True); w.attributes("-alpha", alpha)
        w.configure(bg=bg); w.geometry(f"{r[2]}x{r[3]}+{r[0]}+{r[1]}"); self.rects[key] = r
        return w

    # Creates the see-through canvas layer over the focused window (added v42; changed v43: made by mk_layer).
    def mk_overlay(self):
        ov = self.mk_layer("ov", self.KEY, 0.93); ov.attributes("-transparentcolor", self.KEY)
        cv = self.cv = tk.Canvas(ov, bg=self.KEY, highlightthickness=0, bd=0); cv.pack(fill="both", expand=True)
        for ev, fn in (("<ButtonPress-1>", self.c_down), ("<ButtonPress-3>", self.c_down), ("<B1-Motion>", self.c_move),
                       ("<ButtonRelease-1>", self.c_up), ("<ButtonRelease-3>", self.c_up)):
            cv.bind(ev, lambda e, f=fn: self.safe(f, e))

    # Creates the layer over the tile area: a title and the numbered list of all steps (added v43).
    def mk_steps(self):
        ls = self.mk_layer("ls", CARD, 0.95)
        self.title = tk.Label(ls, text="", bg="#000000", fg=TXT, font=("Segoe UI Semibold", 11), padx=10, pady=6, anchor="w"); self.title.pack(fill="x")
        lf = tk.Frame(ls, bg=CARD); lf.pack(fill="both", expand=True, padx=8, pady=8)
        sb = tk.Scrollbar(lf, orient="vertical"); self.lb = self.mk_list(lf, sb); sb.configure(command=self.lb.yview)
        self.lb.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self.safe(self.on_pick))

    # Small dark button made from a label (works in a window that never gets focus); .on = highlighted state in colour .col (added v42).
    def tb(self, parent, text, cmd, pad=8):
        b = tk.Label(parent, text=text, bg=BTN, fg=TXT, padx=pad, pady=4, cursor="hand2", font=("Segoe UI Semibold", 10)); b.on, b.col = False, "#3b8ee8"
        b.bind("<Button-1>", lambda e: self.safe(cmd))
        b.bind("<Enter>", lambda e: b.configure(bg=BTN_H)); b.bind("<Leave>", lambda e: b.configure(bg=b.col if b.on else BTN))
        return b

    # Switches a tb button's highlight on or off (added v42).
    def lit(self, b, on): b.on = on; b.configure(bg=b.col if on else BTN)

    # Creates the layer over the Anti-AFK strip: row 1 edit buttons + step properties, row 2 record / test / input mode, row 3 macro slots + hint (added v43).
    def mk_bar(self):
        st = self.mk_layer("st", CARD, 0.96); st.configure(highlightthickness=1, highlightbackground=BTN_H)
        ra, rb, rc = (tk.Frame(st, bg=CARD) for _ in range(3))
        for r in (ra, rb, rc): r.pack(fill="x", padx=8, pady=3)
        self.b_add = self.tb(ra, "+", self.toggle_add, 14); self.b_add.pack(side="left", padx=(0, 2))
        self.add_row, self.add_btns = tk.Frame(ra, bg=CARD), {}
        for k, t in (("click", "Click"), ("hold", "Hold"), ("swipe", "Swipe"), ("key", "Key"), ("wait", "Wait")):
            b = self.tb(self.add_row, t, lambda k=k: self.add(k), 9); b.pack(side="left", padx=2); self.add_btns[k] = b
        for t, c in (("−", self.remove), ("▲", lambda: self.move(-1)), ("▼", lambda: self.move(1)), ("Undo", self.undo)):
            self.tb(ra, t, c, 14 if len(t) == 1 else 10).pack(side="left", padx=2)
        self.tb(ra, "✕", self.close, 12).pack(side="right")
        self.prop = tk.Frame(ra, bg=CARD, height=30, width=300); self.prop.pack(side="left", padx=(12, 0)); self.prop.pack_propagate(False)
        self.p_lab = tk.Label(self.prop, bg=CARD, fg=TXT, font=("Segoe UI", 10), anchor="w")
        self.p_dec, self.p_inc = self.tb(self.prop, "−", lambda: self.bump(-1), 12), self.tb(self.prop, "+", lambda: self.bump(1), 12)
        self.p_btn = self.tb(self.prop, "", self.prop_btn)
        self.b_rec = self.tb(rb, "● Record", self.toggle_rec, 10); self.b_rec.col = "#d94a4a"; self.b_rec.pack(side="left", padx=(0, 2))
        self.tb(rb, "▶ Test", self.test, 12).pack(side="left", padx=2); self.tb(rb, "■ Stop", self.stop, 12).pack(side="left", padx=2)
        self.b_mode = self.tb(rb, "", self.toggle_mode); self.b_mode.pack(side="left", padx=(12, 2))
        self.b_tgt = self.tb(rb, "", self.assign); self.b_tgt.pack(side="left", padx=2)
        self.tb(rc, "◀", lambda: self.browse(-1), 8).pack(side="left")
        self.slot_lab = tk.Label(rc, text="", bg=CARD, fg=TXT, anchor="w", width=16, font=("Segoe UI Semibold", 10)); self.slot_lab.pack(side="left", padx=2)
        self.tb(rc, "▶", lambda: self.browse(1), 8).pack(side="left", padx=(0, 6))
        for t, c in (("Load", self.slot_load), ("Save", self.save), ("Save as", lambda: self.save(True)), ("New", self.new), ("Delete", self.slot_delete)):
            self.tb(rc, t, c, 7).pack(side="left", padx=2)
        self.hint = tk.Label(rc, text=self.HINT, bg=CARD, fg=MUTED, anchor="w", font=("Segoe UI", 9)); self.hint.pack(side="left", fill="x", expand=True, padx=(10, 0))

    # A dark Listbox that never asks for the keyboard focus (added v42).
    def mk_list(self, parent, sb=None):
        return tk.Listbox(parent, height=9, width=38, bg=FIELD, fg=TXT, selectbackground="#3b8ee8", selectforeground="#ffffff", highlightthickness=0,
                          bd=0, activestyle="none", exportselection=False, takefocus=0, font=("Consolas", 10), yscrollcommand=sb.set if sb else None)

    # Account shown in the focused window, or "" (added v43).
    def who(self): return next((n for n, h in self.app.windows.items() if h == self.hw), "")

    # Updates the 'Input: ...' and 'Assign to ...' buttons (added v42; changed v43: Assign replaces the 'On:' target).
    def foot(self):
        who = self.who()
        self.b_mode.configure(text="Input: Background" if self.app.cfg["macro_bg"] else "Input: Real mouse")
        self.b_tgt.configure(text=("Assign to " + who)[:26] if who else "Assign")

    # Panel button: flips background input for macros (same setting as the checkbox in the Macros tab) (added v42).
    def toggle_mode(self):
        v = not self.app.cfg["macro_bg"]; self.app.cfg["macro_bg"] = v; self.app.v["macro_bg"].set(v); self.foot()

    # Assign button: makes the saved macro the macro of the focused account (the same list as on the Macros screen) (added v43).
    def assign(self):
        a, who = self.app, self.who()
        if not who: return
        if not self.name or self.dirty: return self.set_hint("Save the macro first, then assign it")
        a.cfg["macro_map"][who] = self.name; a.macro_refresh(); self.set_hint(f"{who} now runs '{self.name}'")

    # Shows a short message in the strip (added v42).
    def set_hint(self, text): self.hint.configure(text=text)

    # Redraws everything that depends on the steps: list, overlay widgets, property row, slot name, buttons, title (added v42).
    def refresh(self):
        self.fill_list(); self.render(); self.props(); self.slot_text(); self.foot()
        who = self.who(); self.title.configure(text=f"Macro steps  -  {who}  ({len(self.steps)})" if who else f"Macro steps  ({len(self.steps)})")

    # Shows the slot name (* = unsaved changes) or, while browsing with the arrows, the saved macro that Load / Delete will use (added v42).
    def slot_text(self):
        t = f"▸ {self.pick}" if self.pick else (self.name or "(unsaved)") + (" *" if self.dirty else "")
        self.slot_lab.configure(text=t[:16])

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
    # or currently running; red R = right button. While a placement tool is armed or recording, the whole area is tinted so the mouse
    # lands on it (added v42; changed v43: recording banner; changed v44: smooth circles and swipe lines, see sprite; while recording only a
    # banner is drawn so the clicks reach the game).
    def render(self):
        if not self.rect: return
        cv, w, h, R = self.cv, self.rect[2], self.rect[3], self.R
        cv.delete("all"); self.hits = []
        if self.rec:                                         # only a small banner: everything else stays click-through, the game is played for real
            bw = min(w - 20, 560); x0 = (w - bw) // 2
            cv.create_rectangle(x0, 6, x0 + bw, 44, fill="#0b1020", outline="#d94a4a", width=3)
            cv.create_text(w // 2, 25, fill="#ffffff", font=("Segoe UI Semibold", 12), text="● Recording: play on the game  (press Record again to stop)")
            return
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
                img, o = line_sprite(round(qx - px), round(qy - py), col)
                cv.create_image(round(px) - o[0], round(py) - o[1], image=img, anchor="nw")
                cv.create_image(qx, qy, image=sprite(26, col, edge, 3 if hot else 1))
                self.hits.append((i, "b", qx, qy, 14))
            cv.create_image(px, py, image=sprite(2 * R + 4, col, edge, 4 if hot else 2, t == "hold"))
            cv.create_text(px, py, text=str(i + 1), fill="#ffffff", font=("Segoe UI Semibold", 13))
            if t != "swipe" and st[-1] == "right": cv.create_text(px + R - 2, py - R + 2, text="R", fill="#ff6b6b", font=("Segoe UI Semibold", 11))
            self.hits.append((i, "a", px, py, R))

    # Remembers the steps for Undo (the last 50 states) and marks the macro as changed (added v42).
    def push(self):
        self.hist.append(json.dumps(self.steps)); del self.hist[:-50]; self.dirty = True; self.slot_text()

    # Undo button: goes back to the previous state of the step list (added v42).
    def undo(self):
        if not self.hist: return self.set_hint("Nothing to undo")
        self.steps = json.loads(self.hist.pop()); self.rec_last = 0.0
        if self.sel is not None and self.sel >= len(self.steps): self.sel = None
        self.refresh()

    # Inserts one or more steps after the selected one (or at the end) as ONE undo step, selects the last one and redraws (added v42; changed v43: several steps).
    def insert(self, *new):
        if len(self.steps) + len(new) > 500: return self.set_hint("A macro can have at most 500 steps.")
        self.push(); i = self.sel + 1 if self.sel is not None else len(self.steps)
        self.steps[i:i] = new; self.sel = i + len(new) - 1; self.refresh()

    # [+] button: shows or hides the row with the step types (hiding also stops placing) (added v42).
    def toggle_add(self):
        if self.add_row.winfo_ismapped(): self.add_row.pack_forget(); self.arm = None; self.lit(self.b_add, False)
        else: self.add_row.pack(side="left", padx=2, after=self.b_add); self.lit(self.b_add, True)
        self.lit_add(); self.render()

    # Highlights the armed step type's button (added v42).
    def lit_add(self):
        for k, b in self.add_btns.items(): self.lit(b, k == self.arm)
        self.set_hint(f"Click on the game to place a {self.arm}" if self.arm else self.HINT)

    # Step type button: click / hold / swipe arm the placement tool (press again to stop), key waits for you to press the key or combo,
    # wait adds a 500 ms pause (added v42; changed v44: Key reads the real key press instead of asking you to type it).
    def add(self, kind):
        if self.rec: self.rec_stop()
        if kind == "wait": return self.insert(["wait", 500])
        if kind == "key":
            if self.cap: self.cap = None; return self.lit_add()
            return self.capture(lambda combo: self.insert(["key", combo]))
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
        self.p_lab.configure(text=f"Wait {st[1]} ms" if t == "wait" else f"Hold {st[3]} ms" if t == "hold" else f"Swipe {st[5]} ms"
                             if t == "swipe" else f"Key {st[1]}" if t == "key" else "Click")
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

    # Property row button: toggles left / right click, or changes the key of a key step (added v42; changed v44: Change reads a key press).
    def prop_btn(self):
        i = self.sel
        if i is None or i >= len(self.steps): return
        st = self.steps[i]
        if st[0] in ("click", "hold"): self.push(); st[-1] = "left" if st[-1] == "right" else "right"; self.refresh()
        elif st[0] == "key": self.capture(lambda combo, i=i: self.set_key(i, combo), "Press the new key or combo now")

    # Mouse press on the overlay: while recording or placing = start of a gesture; otherwise on a widget = select it and start dragging
    # (right button = delete it) (added v42; changed v43: recording).
    def c_down(self, e):
        btn = "right" if e.num == 3 else "left"
        if self.rec: return
        hit = next((h for h in reversed(self.hits) if (e.x - h[2]) ** 2 + (e.y - h[3]) ** 2 <= h[4] ** 2), None)
        if hit:
            if btn == "right": return self.remove(hit[0])
            self.dragging, self.moved = hit, False; return self.select(hit[0])
        if self.arm: self.pstart = (e.x, e.y, time.time(), btn)

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
        elif self.arm == "swipe" and self.pstart and self.pstart[3] == "left":
            self.cv.delete("rb"); self.cv.create_line(self.pstart[0], self.pstart[1], e.x, e.y, fill="#5fd38d", width=8, capstyle="round", tags="rb")

    # Mouse release on the overlay: ends a drag, or turns the gesture into a step by the armed tool (click / hold / swipe)
    # (added v42; changed v43: recording; changed v44: recording no longer goes through here, see rec_poll).
    def c_up(self, e):
        if self.dragging: self.dragging = None; return
        if not (self.arm and self.pstart): return
        x0, y0, t0, btn = self.pstart; self.pstart = None; self.cv.delete("rb")
        w, h = self.rect[2], self.rect[3]; f = lambda v, m: round(min(max(v / m, 0), 1), 4)
        far, ms = (e.x - x0) ** 2 + (e.y - y0) ** 2 >= 196, int((time.time() - t0) * 1000)
        if self.arm == "swipe":
            if not far: return self.set_hint("Swipe: press at the start, drag to the end")
            self.insert(["swipe", f(x0, w), f(y0, h), f(e.x, w), f(e.y, h), 400])
        elif self.arm == "hold": self.insert(["hold", f(x0, w), f(y0, h), 1000, btn])
        else: self.insert(["click", f(x0, w), f(y0, h), btn])

    # Record button: starts / stops recording. You play on the game as usual: the real mouse (click, hold 0.5 s+, drag = swipe) and every key or
    # combo typed while the game or the manager is in front are recorded; pauses of 0.3 s or more become wait steps
    # (added v43; replaces the old Record button; changed v44: reads the real mouse and keys, the game stays clickable).
    def toggle_rec(self):
        if self.rec: return self.rec_stop()
        if self.running: return
        self.arm = self.cap = None; self.lit_add(); self.rec, self.rec_last, self.rec_down = True, 0.0, self.keys_down()
        self.rec_btn, self.pstart = self.mouse_down(), None            # a button that is already down does not start a gesture
        self.lit(self.b_rec, True); self.set_hint("Recording - play on the game: click, hold, drag, type keys"); self.render()
        self.app.give_focus(self.hw); self.rec_poll()

    # Stops recording (added v43).
    def rec_stop(self):
        self.rec, self.pstart = False, None; self.lit(self.b_rec, False); self.set_hint(self.HINT); self.render()
        if self.rec_job:
            try: self.app.after_cancel(self.rec_job)
            except Exception: pass
            self.rec_job = None

    # Virtual-key codes of the recordable keys that are down right now (added v43).
    def keys_down(self): return {vk for vk in REC_KEYS if user32.GetAsyncKeyState(vk) & 0x8000}

    # Recording: adds one recorded step; a pause of 0.3 s or more since the previous action is added first as a wait step (added v43).
    def rec_add(self, step, t0):
        gap = t0 - self.rec_last
        self.insert(*([["wait", min(60000, round(gap * 20) * 50)], step] if self.rec_last and gap >= 0.3 else [step]))
        self.rec_last = time.time()

    def mouse_down(self):
        """Mouse buttons that are down right now: a subset of {'left', 'right'}."""
        return {b for b, vk in (("left", 1), ("right", 2)) if user32.GetAsyncKeyState(vk) & 0x8000}

    def rec_poll(self):
        """Recording: every 15 ms reads the REAL mouse buttons, cursor and keys from Windows (nothing depends on a window getting focus or events).
        A press inside the game area followed by its release becomes click / hold (left 0.5 s+) / swipe (moved 14+ px); a new non-modifier key, with
        the Ctrl / Shift / Alt / Win that are held, becomes a key step. Only counts while the game or the manager is in front, and the macro
        hotkey itself is not recorded. Runs only while recording (added v43 as a key poll; changed v44: mouse too)."""
        self.rec_job = None
        if not (self.alive and self.rec): return
        try:
            front = self.in_front() and not self.hidden and bool(self.shown.get("ov")); rc = self.rect
            pt = wt.POINT(); user32.GetCursorPos(ctypes.byref(pt)); down = self.mouse_down(); new, self.rec_btn = down - self.rec_btn, down
            if self.pstart is None:
                if new and front and rc and rc[0] <= pt.x < rc[0] + rc[2] and rc[1] <= pt.y < rc[1] + rc[3]:
                    self.pstart = (pt.x, pt.y, time.time(), "left" if "left" in new else "right")
            elif self.pstart[3] not in down:                       # released: turn the gesture into a step
                x0, y0, t0, btn = self.pstart; self.pstart = None
                if rc:
                    f = lambda v, o, m: round(min(max((v - o) / max(m, 1), 0), 1), 4)
                    far, ms = (pt.x - x0) ** 2 + (pt.y - y0) ** 2 >= 196, int((time.time() - t0) * 1000)
                    if btn == "left" and far: st = ["swipe", f(x0, rc[0], rc[2]), f(y0, rc[1], rc[3]), f(pt.x, rc[0], rc[2]), f(pt.y, rc[1], rc[3]), max(100, min(3000, round(ms / 50) * 50))]
                    elif btn == "left" and ms >= 500: st = ["hold", f(x0, rc[0], rc[2]), f(y0, rc[1], rc[3]), min(60000, round(ms / 50) * 50), "left"]
                    else: st = ["click", f(x0, rc[0], rc[2]), f(y0, rc[1], rc[3]), btn]
                    self.rec_add(st, t0)
            keys = self.keys_down(); newk, self.rec_down = keys - self.rec_down, keys
            if newk and front:
                mods = [n for vk, n in MOD_NAMES.items() if user32.GetAsyncKeyState(vk) & 0x8000]
                for vk in sorted(newk):
                    combo = "+".join(mods + [REC_KEYS[vk]])
                    if combo != self.app.cfg["macro_key"]: self.rec_add(["key", combo], time.time())
        except Exception as ex:
            self.app.log(f"Builder: recording stopped ({str(ex)[:60]})", "warn"); return self.rec_stop()
        self.rec_job = self.app.after(15, self.rec_poll)

    def capture(self, done, hint="Press the key or combo now  (Key again = cancel)"):
        """Reads the next key press from Windows (the layers never take the keyboard): hold Ctrl / Shift / Alt / Win and press a key, or press
        a single key; it ends when everything is released. done(combo) gets e.g. 'f5' or 'ctrl+shift+a'. Gives up after 10 s."""
        if self.rec: self.rec_stop()
        self.cap = {"done": done, "order": [], "t0": time.time(), "base": {vk for vk in CAP_KEYS if user32.GetAsyncKeyState(vk) & 0x8000}}
        self.arm = None; self.lit_add(); self.set_hint(hint); self.lit(self.add_btns["key"], True)
        if not self.cap_job: self.cap_poll()

    def cap_poll(self):
        """Every 20 ms: collects the keys that went down since the capture started; when all are released the combo is handed over."""
        self.cap_job = None; c = self.cap
        if not (self.alive and c): return
        down = {vk for vk in CAP_KEYS if user32.GetAsyncKeyState(vk) & 0x8000} - c["base"]
        c["order"] += sorted(down - set(c["order"]))
        if c["order"] and not down:
            order = c["order"]; self.cap = None; self.lit_add()
            combo = "+".join([n for vk, n in MOD_NAMES.items() if vk in order] + [REC_KEYS[vk] for vk in order if vk in REC_KEYS][:1])
            return c["done"](combo)
        if time.time() - c["t0"] > 10: self.cap = None; self.lit_add(); return self.set_hint("No key pressed - cancelled")
        self.cap_job = self.app.after(20, self.cap_poll)

    def set_key(self, i, combo):
        """Capture result for the Change button: puts the new key into step i."""
        if i < len(self.steps) and self.steps[i][0] == "key": self.push(); self.steps[i][1] = combo; self.refresh()

    # Runs an in-app prompt (ask / confirm / note) from the builder: all layers hide meanwhile and the manager gets the keyboard, because the
    # prompt is drawn inside the manager window (added v42; changed v43: layers come back at once).
    def prompt(self, fn, *a, **k):
        self.hidden = True; self.hide_all()
        try:
            user32.SetForegroundWindow(self.app.top_hwnd())
            return fn(*a, **k)
        finally:
            self.hidden = False; self.follow()

    # Shows or hides one layer without activating it (ShowWindow SW_SHOWNOACTIVATE / SW_HIDE) and only when its state changes (added v43).
    def show(self, key, on):
        if self.shown.get(key) == on: return
        self.shown[key] = on; user32.ShowWindow(user32.GetAncestor(self.layers[key].winfo_id(), 2), 4 if on else 0)

    # Hides every layer (added v43).
    def hide_all(self):
        for k in self.layers: self.show(k, False)

    # Re-shows the layers on top of everything, without activating them (builder button pressed again) (added v42).
    def front(self):
        self.hidden = False
        for w in self.layers.values(): user32.SetWindowPos(user32.GetAncestor(w.winfo_id(), 2), -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        self.follow()

    # Called by App.track_dock with the docked window's timing (200 ms idle, 10 ms while the manager moves): follows the focused account, puts
    # every layer exactly over its area (geometry is only touched when the rectangle changed) and hides them all while the Viewer is not
    # showing / the manager is minimized / a prompt is open (added v42 as a 150 ms timer; changed v43: driven by track_dock, three layers).
    def follow(self):
        if not self.alive: return
        app = self.app
        try:
            live = app.live()
            if app.active in live and app.active != self.hw and not self.running:
                self.hw = app.active; self.refresh()
            want = self.layout(live)
            for k, w in self.layers.items():
                r = want.get(k)
                if r is None: self.show(k, False); continue
                if r != self.rects.get(k): self.rects[k] = r; w.geometry(f"{r[2]}x{r[3]}+{r[0]}+{r[1]}")
                if k == "ov" and r != self.rect: self.rect = r; self.render()
                self.show(k, True)
        except Exception as ex:
            msg = str(ex)[:80]
            if msg != self.last_err: self.last_err = msg; app.log(f"Builder error: {msg}", "warn")

    # Save / Save as: stores the steps under a name in the same macro list as the Macros screen (asks for the name in-app) (added v42).
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
        self.name, self.dirty, self.pick = name, False, None; a.macro_refresh(); self.slot_text(); self.set_hint(f"Saved '{name}' ({len(self.steps)} steps)")
        a.log(f"Macro '{name}' saved from the visual builder ({len(self.steps)} steps)", "ok")

    # New button: empties the editor (Undo brings the old steps back) (added v42).
    def new(self):
        self.push(); self.steps, self.name, self.sel, self.arm, self.pick = [], "", None, None, None; self.lit_add(); self.refresh()

    # Arrow buttons: browse the saved macros; the one shown is what Load / Delete use (added v43; replaces the slot list page).
    def browse(self, d):
        names = list(self.app.cfg["macros"])
        if not names: return self.set_hint("No saved macros yet - build one and press Save")
        cur = self.pick if self.pick in names else self.name
        self.pick = names[(names.index(cur) + d) % len(names) if cur in names else 0 if d > 0 else -1]; self.slot_text()

    # Load button: replaces the steps with the browsed macro and makes it the selected macro of the Macros screen (added v42; changed v43).
    def slot_load(self):
        a = self.app; steps = a.cfg["macros"].get(self.pick) if self.pick else None
        if steps is None: return self.set_hint("Pick a saved macro with the arrows first")
        name = self.pick; self.push(); self.steps = json.loads(json.dumps(steps))
        self.name, self.dirty, self.sel, self.arm, self.pick = name, False, None, None, None
        a.cfg["macro_sel"] = name; a.macro_refresh(); self.lit_add(); self.refresh()

    # Delete button: removes the browsed (or current) saved macro after a confirmation; the steps in the editor stay (added v42; changed v43).
    def slot_delete(self):
        a = self.app; name = self.pick or self.name
        if name not in a.cfg["macros"]: return self.set_hint("Pick a saved macro with the arrows first")
        if self.prompt(a.confirm, "Delete macro", f"Delete the macro '{name}'?", [("Delete", True), ("Cancel", None)]) is not True: return
        a.cfg["macros"].pop(name, None); a.macro_refresh(); self.pick = None
        if name == self.name: self.name = ""; self.dirty = True
        self.slot_text()

    # Test button: runs the steps ONCE on the focused account only, using the 'Input:' mode. Background input keeps the overlay visible and
    # lights up each step as it runs; real-mouse input hides the overlay (it would catch the clicks) until the run ends (added v42; changed v43).
    def test(self):
        a = self.app
        if not self.steps: return self.set_hint("Nothing to test - add some steps")
        if self.running: return
        if self.rec: self.rec_stop()
        self.arm = None; self.lit_add(); a.collect(); bg = a.cfg["macro_bg"]
        self.running, self.ov_off = True, not bg; self.render(); self.follow()
        if not a.macro_start([(None, self.hw, json.loads(json.dumps(self.steps)))], self.name or "builder test", self.test_done, self.on_run_step if bg else None, True):
            self.test_done()

    # Called from the worker thread before each step: hands the number over to the main thread (added v42).
    def on_run_step(self, i): self.app.after(0, lambda: self.set_run(i))

    # Main thread: marks the running step on screen and in the list (added v42).
    def set_run(self, i):
        if self.alive and self.running: self.run_i = i; self.render(); self.lb.see(i)

    # The test run finished or failed to start: shows the overlay again (added v42).
    def test_done(self):
        self.running, self.run_i, self.ov_off = False, None, False
        if self.alive: self.render(); self.follow()

    # Stop button: stops a running test (added v42).
    def stop(self):
        if self.running: self.app.macro_panic()

    # Closes the builder and its three layers; asks first when there are unsaved changes (added v42).
    def close(self, ask=True):
        if ask and self.dirty and self.steps:
            r = self.prompt(self.app.confirm, "Macro builder", "Save the changes before closing?", [("Save", True), ("Discard", False), ("Cancel", None)])
            if r is None: return
            if r:
                self.save()
                if self.dirty: return                          # the name prompt was cancelled: stay open
        if self.rec: self.rec_stop()
        if self.running: self.app.macro_panic()
        self.alive, self.cap = False, None; self.app.builder = None
        for w in self.layers.values():
            try: w.destroy()
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
        if "macro_map" not in saved and saved.get("macro_sel"):      # v42 'Run on' -> v43 macro per account: keep what it ran
            t, names = saved.get("macro_target", ""), [a["name"] for a in self.cfg["accounts"]]
            self.cfg["macro_map"] = {n: saved["macro_sel"] for n in (names if t == "All running accounts" else [t] if t in names else [])}
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
        self.unfocused = False                              # True = nobody is focused, every instance is a tile (added v45)
        self.dock_local = self.last_dock = self._relayout = None
        self.dock_fast_until, self.hires, self._td, self._winpos = 0.0, False, None, None
        self.press, self.was_down, self.app_fg_top, self._tab, self._dirty, self.dock_fix = None, False, False, "", False, 0
        self._lay_job = None                                # pending live layout commit (added v39)
        self._lay_note = ""                                 # last layout warning written to the log
        self.redock_log, self._last_warn = 0.0, ("", 0.0)   # time of the last re-dock warning / last warning written to the log
        self.anim, self.flashes, self._anim_job = {}, {}, None   # running tile slides / border flashes / shared ticker (added v40)
        self.macro_on, self.m_pt, self.m_held, self.m_kd, self._m_job = False, None, 0, [], None   # macro run state (added v41; the recorder is part of the builder since v43)
        self.dc_seen = {}                                   # Discord alert text -> last time sent (added v41)
        self.dc_last, self.dc_busy, self.dc_err, self.dc_warned = None, False, "", False   # Discord command polling: newest message id / request running / last error / empty-content hint (added v43)
        self.counts, self.mrows = (0, 0, 0, 0), {}          # running / frozen / disconnected / crashed accounts; macro-per-account menus (added v43)
        self.builder, self.bld_wait, self.bg_job, self.afk_job, self.macro_cb = None, False, None, None, None   # visual builder / opening / running background job / macro-end callback (added v42)
        # background work
        self.launch_jobs, self.launch_lock = 0, threading.Lock()
        self.afk_busy, self.afk_next = False, time.time() + 480
        self.afk_hw = self.afk_pt = self.afk_fg = None; self.afk_pressed = self.afk_icon = False
        self.sel, self.rows, self.v = {}, {}, {}
        self.latest_ver, self.pid_build, self.out_logged = None, {}, set()     # newest Roblox build, pid -> running build, warned pids
        self.vram, self.vram_ok, self.io_prev = {}, None, {}
        self.gpu, self.gpu_ok = {}, None                           # pid -> GPU %, counters available?
        self.build(); self.refresh()
        self.bind("<Configure>", self.on_resize, add="+"); self.bind("<Configure>", self.on_move, add="+"); self.after(1500, lambda: setattr(self, "ready", True))
        for delay, fn in ((40, self.poll), (1000, self.sync), (2000, self.dash), (600, self.badge_loop),
                          (1500, self.heal_loop), (100, self.track_dock), (6000, self.dc_poll)):
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

    # Dark-red button for destructive or stop actions (Delete, End); w=0 lets a grid cell size it (added v43, replaces three copies of the same style).
    def red_btn(self, parent, text, cmd, w=100, h=34, size=13):
        return ctk.CTkButton(parent, text=text, command=cmd, width=w or 140, height=h, corner_radius=12, fg_color="#4a1d24", hover_color="#6b2833",
                             text_color="#ff9a9a", font=("Segoe UI Semibold", size))

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

    def confirm(self, title, text, buttons, field=None, secret=False, choices=None):
        """In-app prompt drawn over the whole window. Docked game windows are hidden meanwhile so nothing can cover it.
        buttons = [(label, value), ...]; the first is the primary action, the last one also answers Escape.
        field = initial text adds an entry (the primary button then returns its text, the others None);
        choices = list of names adds a search bar and a list (the primary button, Enter or a double click returns the chosen name) (changed v44);
        The X in the top-right corner (and the app's own close button) answers like the last button. Returns the clicked value."""
        if self.modal: return None
        self.modal = True
        if self.builder: self.builder.follow()                   # its layers would cover the prompt (added v43)
        hidden = [h for h in DOCKED if user32.IsWindow(h)]
        for h in hidden: user32.ShowWindow(h, 0)
        ov = ctk.CTkFrame(self, fg_color=BG, corner_radius=0); ov.place(x=0, y=0, relwidth=1, relheight=1); ov.lift()
        card = ctk.CTkFrame(ov, fg_color=CARD, corner_radius=18); card.place(relx=0.5, rely=0.5 if choices is not None else 0.4, anchor="center")
        ctk.CTkLabel(card, text=title, font=("Segoe UI Semibold", 17), text_color=TXT).pack(padx=34, pady=(26, 6))
        ctk.CTkLabel(card, text=text, justify="left", text_color=MUTED, wraplength=420).pack(padx=34, pady=(0, 18))
        e = None
        if field is not None:
            e = ctk.CTkEntry(card, width=400, height=38, corner_radius=10, fg_color=FIELD, border_width=0, show="•" if secret else "")
            e.insert(0, field); e.pack(padx=34, pady=(0, 18))
        out = tk.StringVar(); res = {}; lb = None
        # Button handler of the in-app prompt: stores which button (or the typed text / chosen name) was chosen and closes the prompt.
        def pick(i):
            if i == 0 and lb is not None:
                s = lb.curselection()
                if not s: return
                res["v"] = lb.get(s[0])
            else: res["v"] = e.get() if e is not None and i == 0 else buttons[i][1]
            out.set("x")
        if choices is not None:
            e = ctk.CTkEntry(card, width=400, height=38, corner_radius=10, fg_color=FIELD, border_width=0, placeholder_text="Search...")
            e.pack(padx=34, pady=(0, 8))
            lf = tk.Frame(card, bg=FIELD); lf.pack(padx=34, pady=(0, 18)); sb = tk.Scrollbar(lf, orient="vertical")
            lb = tk.Listbox(lf, height=10, width=34, bg=FIELD, fg=TXT, selectbackground="#3b8ee8", selectforeground="#ffffff", highlightthickness=0, bd=0,
                            activestyle="none", exportselection=False, font=("Consolas", 12), yscrollcommand=sb.set)
            sb.configure(command=lb.yview); lb.pack(side="left"); sb.pack(side="right", fill="y")
            # Search bar: shows only the choices that contain the typed text and selects the first one.
            def refill(ev=None):
                if ev is not None and ev.keysym in ("Up", "Down", "Return"): return
                q = e.get().strip().lower(); lb.delete(0, "end")
                for c in choices:
                    if q in c: lb.insert("end", c)
                if lb.size(): lb.select_set(0)
            # Up / Down in the search bar move the selection.
            def move(d):
                s = lb.curselection(); i = min(max((s[0] if s else 0) + d, 0), lb.size() - 1)
                lb.selection_clear(0, "end"); lb.select_set(i); lb.see(i)
            refill(); e.bind("<KeyRelease>", refill); e.bind("<Down>", lambda _: move(1)); e.bind("<Up>", lambda _: move(-1))
            lb.bind("<Double-Button-1>", lambda _: pick(0))
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
        self.unf = self.btn(top, "Unfocus", self.toggle_unfocus, w=110, h=32); self.unf.pack(side="right", padx=0)
        sb = self.sbar = ctk.CTkFrame(view, fg_color="transparent", height=124); sb.pack(side="bottom", fill="x", padx=6, pady=(0, 4))   # (self.sbar: the builder covers it, v43)
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
        self.afk_list = ctk.CTkScrollableFrame(rc, height=60, fg_color="transparent", corner_radius=0)
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
        self.red_btn(f, "Delete", self.del_target, 64).grid(row=0, column=4)
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
        self.perf_btn = self.btn(hd, "Performance", self.toggle_perf, w=110, h=30); self.perf_btn.pack(side="right", padx=6)          # v49: next to Roll call, moves with the layout
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
        self.red_btn(bar, "Delete selected accounts", self.remove, 0, 32, 12).grid(row=4, column=1, padx=2, pady=3, sticky="ew")

        # --- macros ---
        mc = self.card(mac, "Macro")
        f = self.line(mc)
        ctk.CTkLabel(f, text="Macro", text_color=MUTED).pack(side="left")
        self.mm = ctk.CTkOptionMenu(f, values=["-"], width=200, height=34, corner_radius=10, fg_color=BTN, button_color=BTN_H,
                                    button_hover_color=BTN_H, dropdown_fg_color=CARD, command=self.macro_pick)
        self.mm.pack(side="left", padx=(8, 14))
        self.btn(f, "Visual builder", self.builder_open, primary=True, w=130, h=34).pack(side="left", padx=(0, 6))
        self.red_btn(f, "Delete", self.macro_delete, 84).pack(side="left", padx=3)
        ctk.CTkLabel(mc, text="Macro per account", text_color=MUTED).pack(anchor="w", padx=18, pady=(8, 0))
        self.mlist = ctk.CTkScrollableFrame(mc, height=220, fg_color=FIELD, corner_radius=10); self.mlist.pack(fill="x", padx=14, pady=6)
        for c in range(3): self.mlist.grid_columnconfigure(c, weight=1, uniform="mc")
        f = self.line(mc)
        self.check(f, "Background input", "macro_bg")
        self.entry(f, "Repeat", "macro_loops", 50)
        self.check(f, "Run forever", "macro_forever")
        self.btn(f, "Run", self.macro_start, primary=True, w=100, h=34).pack(side="left", padx=(0, 8))
        self.red_btn(f, "End", self.macro_panic, 100).pack(side="left")
        ctk.CTkLabel(mc, wraplength=900, justify="left", text_color=MUTED,
                     text="Visual builder: record or place clicks, holds, swipes and keys on the focused game, then save the macro.\n"
                          "Pick a macro for every account above (None = that account does nothing), then press Run.\n"
                          "Background input: clicks and keys are posted to the game windows - no cursor, no focus change, all accounts at once.\n"
                          "Run forever repeats until you press End. End (or the macro hotkey) stops the macro at once and lets go of every key."
                     ).pack(anchor="w", padx=18, pady=(0, 14))

        # --- settings ---
        sc = ctk.CTkScrollableFrame(sett, fg_color=BG); sc.pack(fill="both", expand=True)
        c = self.card(sc, "Layout")
        f = self.line(c); self.entry(f, "Launch delay (s)", "delay", 60)
        f = self.line(c); self.check(f, "Custom tile size (unfocused window)", "micro")
        self.entry(f, "Width px", "windowWidth", 60); self.entry(f, "Height px", "windowHeight", 60)
        ctk.CTkLabel(f, text="Limits: 40-4000 px. Applies at once; tiles shrink (same proportions) when they do not fit", text_color=MUTED).pack(side="left")
        f = self.line(c)
        ctk.CTkLabel(f, text="Presets", text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(f, values=["320x240", "240x180", "200x150", "160x120", "120x90"], width=120, height=34,
                          corner_radius=10, fg_color=BTN, button_color=BTN_H, button_hover_color=BTN_H,
                          dropdown_fg_color=CARD, command=self.pick_size).pack(side="left", padx=(8, 22))
        f = self.line(c); self.check(f, "Username badges", "badges")
        f = self.line(c); self.check(f, "Animations", "anim"); self.entry(f, "Duration ms", "animMs", 60)
        ctk.CTkLabel(f, text="Limits: 0-600 ms (0 = off)", text_color=MUTED).pack(side="left")
        for k in ("windowWidth", "windowHeight", "micro"): self.v[k].trace_add("write", self.layout_changed)
        c = self.card(sc, "Graphics")
        f = self.line(c); self.check(f, "Apply low graphics on launch", "gfx"); self.check(f, "Mute", "mute")
        f = self.line(c); self.check(f, "Keep file read-only", "gfx_lock"); self.check(f, "Start with leaderboard and chat closed", "hideui")
        f = self.line(c); self.check(f, "Bare-bones Roblox settings", "bare")
        ctk.CTkLabel(f, text="Turns off chat translation, vignette, player names, badges, tutorials, haptics, profilers; only keys already in the file", text_color=MUTED).pack(side="left")
        ctk.CTkLabel(f, text="On (recommended) = each launched instance keeps your FPS/quality. Off = Roblox can also save window position / leaderboard state, but may overwrite FPS/quality", text_color=MUTED).pack(side="left")
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
        f = self.line(c); self.check(f, "Background input (no focus change, but the game may ignore it)", "afk_bg"); self.check(f, "Fake window activation", "bg_wake")
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Default: every account is brought to the front for a moment and gets two real clicks (works from any tab, also minimized; "
                          "your tab, cursor and program are put back afterwards; it waits while you are using the mouse). 'Background input' posts the "
                          "clicks instead - no focus change and it also runs during macros, but many games ignore it. 'Fake window activation' only "
                          "affects background input."
                     ).pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, "Connection watch")
        f = self.line(c); self.check(f, "Auto-rejoin (max 3 per 30 min)", "auto_rejoin")
        f = self.line(c); self.entry(f, "Check every (s)", "watch_sec", 60)
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Asks Roblox whether each account is still in a game. A disconnect is flagged after 2 checks in a "
                          "row, so expect 1-2+ minutes. If an account uses 'appear offline', turn it off in the Viewer tab.").pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, "Hotkeys")
        f = self.line(c); self.check(f, "Hotkeys", "hotkeys", lambda: self.hotkeys(self.v["hotkeys"].get()))
        f = self.line(c); ctk.CTkLabel(f, text="Macro hotkey", text_color=MUTED).pack(side="left")
        self.hk_v = []
        for i, vals in enumerate((HK_MODS, HK_MODS, HK_PICK)):
            if i: ctk.CTkLabel(f, text="+", text_color=MUTED).pack(side="left", padx=5)
            var = tk.StringVar(value=hotkey_parts(self.cfg["macro_key"])[i]); self.hk_v.append(var)
            if i < 2: ctk.CTkOptionMenu(f, values=vals, variable=var, width=100, height=34, corner_radius=10, fg_color=BTN, button_color=BTN_H,
                                        button_hover_color=BTN_H, dropdown_fg_color=CARD, command=self.hk_pick).pack(side="left", padx=(8 if i == 0 else 0, 0))
            else: self.hk_btn = self.btn(f, var.get(), self.hk_key, w=100, h=34); self.hk_btn.pack(side="left")
        ctk.CTkLabel(f, text="_ = blank", text_color=MUTED).pack(side="left", padx=12)
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Starts the macros, or stops everything while they run. The first two boxes are Ctrl / Shift / Alt / Win or blank, the last box is the key "
                          "(ctrl + shift + k, or _ + _ + k for just K). A key without Ctrl / Shift / Alt / Win is blocked in every program while Hotkeys is on."
                     ).pack(anchor="w", padx=18, pady=(0, 6))
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Ctrl+Shift+1..9 focus the 1st..9th running account (tile order), Ctrl+Shift+Left / Right = previous / next. "
                          "Works while a game window has focus. If another program already uses a key, it is listed in the log."
                     ).pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, "Discord alerts")
        f = self.line(c); self.check(f, "Message when an account crashes, disconnects or fails to launch", "dc_on")
        f = self.line(c); self.btn(f, "Setup tutorial", lambda: webbrowser.open(DC_TUTORIAL), primary=True, w=130, h=34).pack(side="left")
        f = self.line(c); self.entry(f, "Channel ID", "dc_chan", 200); self.btn(f, "Set bot token", self.dc_token, w=130, h=34).pack(side="left", padx=(0, 8))
        self.dc_lab = ctk.CTkLabel(f, width=110, anchor="w", text_color=MUTED, text="Token: set" if self.cfg["dc_token"] else "Token: not set")
        self.dc_lab.pack(side="left", padx=(0, 8)); self.btn(f, "Send test", self.dc_test, w=110, h=34).pack(side="left")
        f = self.line(c); self.entry(f, "Alert text", "dc_fmt", 430)
        ctk.CTkLabel(f, text="{msg} {account} {time}", text_color=MUTED).pack(side="left")
        f = self.line(c); self.check(f, "Answer commands written in the channel", "dc_cmd_on"); self.entry(f, "Prefix", "dc_prefix", 50)
        self.btn(f, "Apply commands", self.dc_cmds_apply, w=150, h=34).pack(side="left")
        self.dc_box = ctk.CTkTextbox(c, height=110, fg_color=FIELD, corner_radius=10, font=("Consolas", 13), text_color=TXT)
        self.dc_box.pack(fill="x", padx=14, pady=(2, 6)); self.dc_box.insert("1.0", "\n".join(f"{n} = {r}" for n, r in self.cfg["dc_cmds"]))
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Commands: one per line, name = reply (press Apply commands). Replies can use {running} {total} {frozen} {disc} {crashed} {accounts} "
                          "{commands} {time} {version}. Setup: 1) create an app in the Discord developer portal (Setup tutorial), add a Bot, copy its token; "
                          "2) for commands switch on 'Message Content Intent' on the Bot page; 3) invite the bot with View Channel, Send Messages and Read "
                          "Message History; 4) paste the channel's ID (Developer Mode > right-click the channel > Copy ID) and set the token. The token is "
                          "stored encrypted for this Windows user. The same alert is sent at most once a minute; commands are checked every 6 s."
                     ).pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, f"Updates  (installed: v{VERSION})")
        f = self.line(c); self.entry(f, "Update link (https)", "update_url", 430)
        f = self.line(c); self.check(f, "Check at launch", "auto_update"); self.btn(f, "Check now", self.check_update_now, w=120).pack(side="left")
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Link to your newest Better RAM .py file (for example its GitHub 'Raw' link). It is only installed when its "
                          "VERSION number is higher than this one. Only use a link that you alone can edit.").pack(anchor="w", padx=18, pady=(0, 14))

    # ---------- logging ----------
    def log(self, msg, kind="info"):
        """Timestamped event -> log panel + file. Safe to call from any thread.
        Changed v44: the same warning is written at most once per 30 s, so a repeating problem cannot flood the log."""
        if kind == "warn":
            if msg == self._last_warn[0] and time.time() - self._last_warn[1] < 30: return
            self._last_warn = (msg, time.time())
        stamp = time.strftime("%H:%M:%S")
        try:
            with open(LOG, "a", encoding="utf-8") as fh: fh.write(f"{time.strftime('%Y-%m-%d')} {stamp}  {msg}\n")
        except Exception: pass
        self.after(0, lambda: self.log_line(stamp, msg, kind))
        if kind == "bad" and self.cfg["dc_on"]: self.notify(msg)

    # Writes one timestamped line into the log panel; called on the main thread (added v33, split out of log).
    def log_line(self, stamp, msg, kind):
        at_end = self.logbox.yview()[1] >= 0.999          # changed v44: only follow new lines when already at the bottom
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{stamp}  {msg}\n", kind)
        if int(self.logbox.index("end-1c").split(".")[0]) > 1500: self.logbox.delete("1.0", "300.0")
        self.logbox.configure(state="disabled")
        if at_end: self.logbox.see("end")

    # Short hint such as 'tick accounts first': shown in the log panel only, not saved to the log file (v28; reworked v33).
    def say(self, text):                                    # short hint ("tick accounts first"): shown in the log panel only
        stamp = time.strftime("%H:%M:%S"); self.after(0, lambda: self.log_line(stamp, text, "warn"))

    # Empties the log panel (the log file is untouched) (v28 or earlier).
    def clear_log(self):
        self.logbox.configure(state="normal"); self.logbox.delete("1.0", "end"); self.logbox.configure(state="disabled")

    # ---------- config ----------
    PENDING = {"micro", "windowWidth", "windowHeight"}              # committed by live_layout only

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
        self.macro_refresh()

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

    def afk_chip(self, parent, n):
        """One Anti-AFK pill for an account: bright = Anti-AFK on, dim = skipped. Clicking flips it."""
        var, b = self.afk_sel[n], ctk.CTkButton(parent, text=n, width=150, height=26, corner_radius=13, font=("Segoe UI", 12))
        # Colours the pill by its state.
        def style(): on = var.get(); b.configure(fg_color=TXT if on else CARD, hover_color="#ffffff" if on else BTN, text_color=BG if on else MUTED)
        # Click: flips the account and stores the change.
        def flip(): var.set(not var.get()); style(); self.afk_toggle()
        b.configure(command=flip); style(); b.restyle = style
        return b

    # Rebuilds the Viewer's Anti-AFK account list (v28; grid of columns with an auto scrollbar since v32).
    def build_afk_list(self, names):
        for w in self.afk_list.winfo_children(): w.destroy()
        skip = set(self.cfg["afk_skip"])
        self.afk_sel = {n: tk.BooleanVar(value=n not in skip) for n in names}     # the one source of truth
        self.afk_cells = [self.afk_chip(self.afk_list, n) for n in names]
        self.afk_cols = 0; self.layout_afk()
        self.afk_count()

    def layout_afk(self):
        """Accounts sit side by side in as many columns as fit; extra accounts add rows. The scrollbar (top to bottom)
        only appears when there are more than 3 rows."""
        try:
            w = self.afk_rc.winfo_width()
            n = len(self.afk_cells)
            cols = max(1, (max(w, 200) - (24 if n > 3 else 4)) // 160)
            rows = -(-n // cols) if n else 0
            if rows > 3 and cols > 1:                       # the scrollbar costs width: recount without it
                cols = max(1, (max(w, 200) - 24) // 160); rows = -(-n // cols)
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
        for c in self.afk_cells: c.restyle()
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
            lock = bool(self.cfg.get("gfx_lock"))
            apply_graphics(self.cfg["fps"], self.cfg["quality"], self.cfg["mute"], lock, self.cfg["hideui"], self.cfg["bare"])
            self.log(f"Graphics written (FPS {self.cfg['fps']}, quality {self.cfg['quality']}), file is {'read-only' if lock else 'writable'}")
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
    def plan(self, n, full=False):
        """-> (tile slots, focus-pane rect, tiles fit?) in stage coordinates. full=True: no focus pane, the tiles may use the whole viewer."""
        W, H = self.stage_size()
        multi = n > 1 and not full
        tw = int(W * (0.60 if self.cfg["micro"] else 0.38)) if multi else W       # changed v45: fixed share, no tile-area setting
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
        unf = self.unfocused
        slots, fr, fits = self.plan(len(wins), unf)
        for i, hw in enumerate(wins):
            self.place(hw, fr if hw == self.active and not unf else slots[i])
        if unf: self.placeholder(None)
        else: self.sync_ph(wins, slots)
        self.stage.update_idletasks()
        big = sum(1 for i, hw in enumerate(wins) if (unf or hw != self.active)
                  and (win_rect(hw).right - win_rect(hw).left > slots[i][2] + 3 or win_rect(hw).bottom - win_rect(hw).top > slots[i][3] + 3))
        note = ""
        if big: note = f"Layout: {big} tile(s) refuse to get as small as {slots[0][2]}x{slots[0][3]} (Roblox has a minimum window size) - cropped to the tile. "
        if not fits: note += "Custom tile size does not fit, scaled down. "
        if note != self._lay_note:
            self._lay_note = note
            if note: self.log(note.strip(), "warn")
        extra = tuple(sorted(h for h in roblox_windows() if h not in wins))
        if extra and extra != getattr(self, "_extra", ()):
            self.log("Roblox window(s) open but not managed by Better RAM (pid " + ", ".join(str(pid_of(h)) for h in extra) +
                     ") - leftover from an earlier session? Close them, they cannot be placed in the viewer", "warn")
        self._extra = extra
        self.after(30, self.update_badges); self.set_active_label()

    # Positions one tile cell at a rectangle and rounds its corners (v28 or earlier).
    def place(self, hw, rect):
        x, y, w, h = rect
        cell = self.cell_for(hw)
        self.move_cell(cell, hw, x, y, w, h)
        if cell.rgn != (w, h): cell.rgn = (w, h); round_region(cell.winfo_id(), w, h, RADIUS)
        if hw == self.active and not self.unfocused:         # focused instance = real window docked over the pane
            self.dock_local = rect; self.dock(hw)
        else:
            if hw in DOCKED: self.undock(hw, cell)           # just lost focus -> back into its tile
            elif user32.GetParent(hw) != cell.winfo_id(): embed_window(hw, cell.winfo_id())   # never size a top-level as a tile
            fit_child(hw, w, h)

    # Puts a tile cell at its rectangle; an unfocused tile that only changes position (same size) slides there (added v40).
    def move_cell(self, cell, hw, x, y, w, h):
        ms = min(600, max(0, self.cfg["animMs"])) if self.cfg["anim"] else 0
        old = getattr(cell, "cur", None)
        if ms and (hw != self.active or self.unfocused) and old and old != (x, y) and cell.rgn == (w, h) and cell.winfo_ismapped():
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
        self.active_label.configure(text="Focused: none" if self.unfocused else f"Focused: {name}" if name else "Focused: -")

    # Makes a window the focused one (swaps it with the previous focused tile) (v28 or earlier).
    def switch_to(self, hw):
        """Changed v45: from the unfocused layout the instance gets the focus and everything is laid out again."""
        if hw == self.active and not self.unfocused: return
        if self.unfocused:
            self.unfocused, self.active = False, hw; self.retile(); self.after(80, lambda: self.give_focus(hw)); return
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
        elif self.live() and self.active: self.maxed, self.unfocused = self.active, False
        else: return self.say("No instance running")
        self.retile()

    def toggle_unfocus(self):
        """Top-right button: nobody is focused, every instance sits in its own tile; press again to focus one again."""
        if not self.live(): return self.say("No instance running")
        self.unfocus(not self.unfocused)

    def unfocus(self, on):
        """Switches the unfocused layout on or off and lays everything out again (a docked game window goes back into its tile)."""
        if on == self.unfocused: return
        self.unfocused = on
        if on: self.maxed = None
        self.retile()
        if not on and self.active: self.after(80, lambda h=self.active: self.give_focus(h))

    # Keeps the Fullscreen button text in sync (v28 or earlier).
    def sync_fs(self):
        t = "Exit fullscreen" if self.maxed else "Fullscreen"
        if self.fs.cget("text") != t: self.fs.configure(text=t)
        t = "Focus" if self.unfocused else "Unfocus"
        if self.unf.cget("text") != t: self.unf.configure(text=t)

    # Preset menu for tile size: only fills the fields, 'Apply' commits (v28 or earlier).
    def pick_size(self, choice):                             # only fills the fields; "Apply" commits them
        w, h = choice.split("x"); self.v["windowWidth"].set(w); self.v["windowHeight"].set(h)

    # Typing in a layout entry (or ticking Custom tile size) schedules live_layout 0.7 s after the last change (added v39).
    def layout_changed(self, *_):
        if self._lay_job: self.after_cancel(self._lay_job)
        self._lay_job = self.after(700, self.live_layout)

    # Commits tile size / tile area from the entries without rewriting them (so typing is not disturbed) and re-tiles
    # when the Viewer is next shown; the Apply buttons still confirm in the log (added v39).
    def live_layout(self):
        self._lay_job = None
        try:
            for k, lo, hi in (("windowWidth", 40, 4000), ("windowHeight", 40, 4000)):
                m = re.search(r"\d+", str(self.v[k].get()))
                if m: self.cfg[k] = min(hi, max(lo, int(m.group())))
            self.cfg["micro"] = bool(self.v["micro"].get())
        except tk.TclError: return
        if self.tv.get() == "Viewer": self.retile()
        else: self._dirty = True

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
                    # v45: park it far offscreen instead of hiding it, so Roblox keeps its surface and does not reload on return
                    r = win_rect(hw)
                    if r.left != -32000 or r.top != -32000 or not user32.IsWindowVisible(hw):
                        user32.SetWindowPos(hw, 0, -32000, -32000, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
                    self.last_dock = None                      # forces the move back into the pane when the Viewer tab returns
                else:
                    x, y, w, h = self.dock_local
                    want = (self.stage.winfo_rootx() + x, self.stage.winfo_rooty() + y, w, h)
                    r = win_rect(hw)
                    bad = (user32.GetWindowLongPtrW(hw, GWL_STYLE) & WS_CAPTION == WS_CAPTION or user32.GetWindowLongPtrW(hw, GWL_STYLE) & WS_THICKFRAME) or \
                          max(abs(r.left - want[0]), abs(r.top - want[1]), abs(r.right - r.left - w), abs(r.bottom - r.top - h)) > 2
                    if bad: self.dock_fast_until = time.time() + 0.5
                    if bad and self.dock_fix < 25:           # Roblox put its frame/size back (e.g. while still starting): dock it again
                        if not self.dock_fix and time.time() - self.redock_log > 60:      # changed v44: at most one warning a minute
                            self.redock_log = time.time(); self.log("Focused window left its pane - re-docking", "warn")
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
            if self.builder: self.builder.follow()               # builder layers follow with the same timing (added v43)
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
        self.counts = (run, frozen, disc, crashed)            # read by the Discord commands (added v43)

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
                self.gpu, self.gpu_ok = r[0], True
                self.vram_ok = r[1] is not None; self.vram = r[1] or {}
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
        if i == 20: return self.macro_toggle()               # macro hotkey: End while running, otherwise Run (added v41; changed v43)
        if self.modal or self.busy: return
        alive = self.live(); names = [n for n, h in self.windows.items() if h in alive]
        if not names: return
        if i <= 9: idx = i - 1
        else:
            cur = next((k for k, n in enumerate(names) if self.windows[n] == self.active), -1)
            idx = (cur + (-1 if i == 10 else 1)) % len(names)
        if idx < len(names): self.show(names[idx])

    # ---------- anti-AFK ----------
    def start_afk(self, force=False):
        """Anti-AFK round. Default (real click): each account is brought to the front for a moment and gets two REAL clicks in its corner,
        because many games ignore clicks posted to a window that has no focus. It does not need the Viewer tab or the app in front: a
        minimized app is restored for the round, then the tab, focused account, cursor, minimized state and the program you were using
        are put back. With 'Background input' ticked it posts the clicks instead (no focus change, but the game may ignore them).
        Changed v44: real round restored, works from any tab / minimized, restores your foreground program."""
        if self.afk_busy or self.afk_job: return
        if self.cfg["afk_bg"]: return self.afk_bg_round(force)
        if self.macro_on: self.afk_next = time.time() + 30; return
        if not force and user_idle_seconds() < 8:
            self.afk_next = time.time() + 30; return          # you're busy: try again shortly
        alive, skip = self.live(), set(self.cfg["afk_skip"])
        wins = [h for n, h in self.windows.items() if h in alive and n not in skip]
        if not wins: return
        gap = max(300, self.cfg["afk_gap"])
        self.afk_busy = True
        self.afk_prev = (self.tv.get(), self.active, self.unfocused)
        self.afk_fg, self.afk_icon = user32.GetForegroundWindow(), self.state() == "iconic"
        old = wt.POINT(); user32.GetCursorPos(ctypes.byref(old)); self.afk_cursor = (old.x, old.y)
        if self.afk_icon: self.state("normal")
        if self.tv.get() != "Viewer": self.tv.set("Viewer")
        steps = [(900 if self.afk_icon else 1, lambda: None)]
        for hw in wins:
            steps += [(700, lambda h=hw: self.switch_to(h)), (900, lambda h=hw: self.afk_aim(h)),
                      (300, self.afk_down), (150, self.afk_up), (gap, self.afk_down), (150, self.afk_up)]
        steps.append((600, self.afk_finish))
        self.log(f"Anti-AFK round started ({len(wins)} instances)")
        self.run_seq(steps)

    def run_seq(self, steps):
        """Runs (delay ms, action) pairs one after another on the main thread."""
        if not steps: return
        d, fn = steps[0]
        # Runs one step, then the rest.
        def go():
            try: fn()
            finally: self.run_seq(steps[1:])
        self.after(d, go)

    def afk_aim(self, hw):
        """Moves the cursor to the Anti-AFK click spot of a window."""
        self.afk_hw = hw
        rc = wt.RECT(); user32.GetClientRect(hw, ctypes.byref(rc)); off = max(1, self.cfg["afk_off"])
        pt = wt.POINT(max(1, rc.right - off), max(1, rc.bottom - off)); user32.ClientToScreen(hw, ctypes.byref(pt))
        user32.SetCursorPos(pt.x, pt.y); self.afk_pt = pt

    def afk_down(self):
        """Presses the mouse only if the cursor is really over that game window."""
        pt = self.afk_pt
        self.afk_pressed = bool(pt and self.afk_hw and user32.IsWindow(self.afk_hw)
                                and self.owner_of(user32.WindowFromPoint(pt)) == self.afk_hw)   # never click anything else
        if self.afk_pressed: user32.mouse_event(2, 0, 0, 0, 0)

    def afk_up(self):
        """Releases the mouse button after afk_down."""
        if self.afk_pressed: user32.mouse_event(4, 0, 0, 0, 0); self.afk_pressed = False

    def afk_finish(self):
        """Puts back the tab, focused account, cursor, minimized state and the program that was in front before the round."""
        prev_tab, prev_active, prev_unf = self.afk_prev
        if prev_active in self.live() and prev_active != self.active: self.switch_to(prev_active)
        if prev_unf: self.unfocus(True)                      # back to every instance minimized into its tile
        if prev_tab != "Viewer": self.after(800, lambda: self.tv.set(prev_tab))
        user32.SetCursorPos(*self.afk_cursor)
        fg = self.afk_fg
        if fg and user32.IsWindow(fg) and fg != self.top_hwnd() and fg not in self.windows.values(): user32.SetForegroundWindow(fg)
        if self.afk_icon: self.after(900, self.iconify)
        self.afk_busy = False
        self.log("Anti-AFK round done", "ok")

    def afk_bg_round(self, force=False):
        """Background Anti-AFK: every selected account gets a posted click in its bottom-right corner, a pause and a second click, all at once,
        with no cursor movement or focus change. Runs in its own job slot, also while a macro runs. The focused account is skipped only while
        you are playing it. Changed v44: own job slot, works during macros."""
        if self.afk_job: return
        alive, skip, fg = self.live(), set(self.cfg["afk_skip"]), user32.GetForegroundWindow()
        wins = [h for n, h in self.windows.items() if h in alive and n not in skip
                and not (h == self.active and not force and fg == h and user_idle_seconds() < 60)]
        if not wins: return
        off, gap, wake = max(1, self.cfg["afk_off"]), max(300, self.cfg["afk_gap"]), self.cfg["bg_wake"]
        # Worker thread body for one window: click near the bottom-right corner, pause, click again (no Tk, no self.windows).
        def work(hw, stop):
            w, h = client_size(hw); fx, fy = max(0.0, (w - off) / max(w, 1)), max(0.0, (h - off) / max(h, 1))
            bg_play(hw, [["click", fx, fy, "left"], ["wait", gap], ["click", fx, fy, "left"]], stop, wake)
        self.log(f"Anti-AFK round started in the background ({len(wins)} instances)")
        self.bg_start("Anti-AFK round", wins, work, slot="afk_job")

    # ---------- macros (added v41; v43: one macro per account, Run forever, End button, recorder merged into the builder) ----------
    # Fills the Macros screen from the config: the macro menu (used by the builder and Delete) and one macro menu per account. Assignments of
    # deleted macros and removed accounts are dropped, so the lists are right after builder saves, Delete and account changes (added v41; changed v43).
    def macro_refresh(self):
        cfg = self.cfg; names = list(cfg["macros"]); accts = [a["name"] for a in cfg["accounts"]]
        if cfg["macro_sel"] not in cfg["macros"]: cfg["macro_sel"] = names[0] if names else ""
        self.mm.configure(values=names or ["-"]); self.mm.set(cfg["macro_sel"] or "-")
        mp = cfg["macro_map"]
        for n in [n for n in mp if n not in accts or mp[n] not in cfg["macros"]]: del mp[n]
        for n in [n for n in self.mrows if n not in accts]: self.mrows.pop(n)[0].destroy()
        for i, n in enumerate(accts):                       # roll call look: cards, 3 per row [account | macro]
            if n not in self.mrows:
                row = ctk.CTkFrame(self.mlist, fg_color=CARD, corner_radius=10); row.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(row, text=n, anchor="w", width=96, text_color=TXT, font=("Segoe UI", 12)).grid(row=0, column=0, padx=(10, 4), pady=8, sticky="w")
                menu = ctk.CTkOptionMenu(row, values=["None"], height=28, corner_radius=8, fg_color=BTN, button_color=BTN_H, font=("Segoe UI", 12),
                                         button_hover_color=BTN_H, dropdown_fg_color=CARD, command=lambda v, n=n: self.macro_assign(n, v))
                menu.grid(row=0, column=1, padx=(0, 8), sticky="ew"); self.mrows[n] = (row, menu)
            self.mrows[n][0].grid(row=i // 3, column=i % 3, padx=3, pady=3, sticky="ew")
            self.mrows[n][1].configure(values=["None"] + names); self.mrows[n][1].set(mp.get(n, "None"))

    # Macro menu handler: chooses the macro the builder opens and Delete removes (added v41; changed v43).
    def macro_pick(self, name):
        if name in self.cfg["macros"]: self.cfg["macro_sel"] = name

    # Handler of an account's macro menu: 'None' = this account does not run anything (added v43).
    def macro_assign(self, acct, name):
        if name in self.cfg["macros"]: self.cfg["macro_map"][acct] = name
        else: self.cfg["macro_map"].pop(acct, None)

    # Deletes the macro chosen in the macro menu after a confirmation (added v41).
    def macro_delete(self):
        sel = self.cfg["macro_sel"]
        if not sel: return
        if self.builder: return self.say("Close the visual builder first")
        if self.confirm("Delete macro", f"Delete the macro '{sel}'?", [("Delete", True), ("Cancel", None)]) is not True: return
        self.cfg["macros"].pop(sel, None); self.macro_refresh()

    def hk_key(self):
        """Last macro-hotkey box: opens a window with a search bar and the list of keys instead of one huge drop-down menu."""
        k = self.confirm("Macro hotkey key", "Type to search, then pick the key.", [("Select", True), ("Cancel", None)], choices=HK_PICK)
        if not k: return
        self.hk_v[2].set(k); self.hk_btn.configure(text=k); self.hk_pick()

    # The macro hotkey pickers changed: validates the combination, stores it as text (e.g. 'ctrl+shift+k' or 'k') and restarts the hotkey
    # thread so it takes effect (added v43; replaces the typed hotkey entry).
    def hk_pick(self, _=None):
        a, b, k = (v.get() for v in self.hk_v)
        if a == b != "_":
            b = "_"; self.hk_v[1].set(b); self.note("Macro hotkey", "Each modifier can only be used once.")
        self.cfg["macro_key"] = "+".join(p for p in (a, b, k) if p != "_")
        if self.cfg["hotkeys"]: self.hotkeys(False); self.hotkeys(True)
        self.log(f"Macro hotkey: {self.cfg['macro_key']}" + ("" if self.cfg["hotkeys"] else " (turn Hotkeys on to use it)"))

    # Running accounts that have a macro: [(account, window, steps)] in viewer order (added v43; replaces macro_targets / 'Run on').
    def macro_jobs(self):
        alive, mp = self.live(), self.cfg["macro_map"]
        return [(n, h, self.cfg["macros"][mp[n]]) for n, h in self.windows.items() if h in alive and mp.get(n) in self.cfg["macros"]]

    # Hotkey: stops everything when something runs, otherwise starts the macros; ignored while the builder records (added v41; changed v42, v43).
    def macro_toggle(self):
        if self.builder and self.builder.rec: return
        if self.macro_on or self.bg_job: self.macro_panic()
        else: self.macro_start()

    # Run button / hotkey: every running account plays its own macro (account -> macro list) - one account after another with the real mouse,
    # or all at once with Background input. jobs = [(account or None, window, steps)] plays exactly these (the builder's Test, with once=True
    # = a single time); on_done is called when the run ends, on_step(i) before each step in background mode. Run forever repeats until End.
    # Returns True when a run was started (added v41; changed v42: jobs / callbacks / background; changed v43: per-account macros, Run forever).
    def macro_start(self, jobs=None, name="", on_done=None, on_step=None, once=False):
        if self.afk_busy or self.bg_job: return self.say("Macro: a run is still going - press End to stop it")
        jobs = jobs or self.macro_jobs()
        if not jobs: return self.say("Macro: no running account has a macro - pick one per account first")
        self.collect(); loops = None if self.cfg["macro_forever"] and not once else 1 if once else min(999, max(1, self.cfg["macro_loops"]))
        what = f"Macro '{name}'" if name else "Macros"; how = "until End" if loops is None else f"{loops}x"
        if self.cfg["macro_bg"]:
            wake, one, steps = self.cfg["bg_wake"], len(jobs) == 1, {hw: st for _, hw, st in jobs}
            self.log(f"{what} started in the background on {len(steps)} account(s), {how}")
            self.bg_start(what, list(steps), lambda h, stop: bg_play(h, steps[h], stop, wake, loops, on_step if one else None), on_done)
            return True
        if self.state() == "iconic": return self.say("Macro waiting: the manager is minimized")
        self.afk_busy = self.macro_on = True
        self.afk_prev = (self.tv.get(), self.active, self.unfocused)
        old = wt.POINT(); user32.GetCursorPos(ctypes.byref(old)); self.afk_cursor = (old.x, old.y)
        if self.tv.get() != "Viewer": self.tv.set("Viewer")
        self.log(f"{what} started on {len(jobs)} account(s), {how}")
        self.macro_cb = on_done; self.macro_seq(self.macro_gen(jobs, loops)); return True

    # Yields the (delay ms, action) list of a real-mouse run lazily: each account is switched to (unless it is already in front) and plays
    # its macro `loops` times; with loops=None the whole round repeats, one pass per account, until the run is stopped (added v43).
    def macro_gen(self, jobs, loops):
        while True:
            for _, hw, steps in jobs:
                if hw != self.active: yield 700, lambda h=hw: self.switch_to(h); yield 400, lambda: None
                for _ in range(loops or 1): yield from self.macro_body(hw, steps)
            if loops: break
        yield 300, self.macro_finish

    # Runs a (delay, action) iterator one entry at a time; stops as soon as macro_on is cleared (added v41; changed v43: takes an iterator).
    def macro_seq(self, it):
        nxt = next(it, None)
        if nxt is None: return
        d, fn = nxt
        # Runs one action, then schedules the next.
        def go():
            self._m_job = None
            try: fn()
            except Exception as ex: self.log(f"Macro error: {str(ex)[:70]}", "warn")
            if self.macro_on: self.macro_seq(it)
        self._m_job = self.after(max(1, d), go)

    # End button / macro hotkey while something runs: stops the macro at once - the real-mouse macro, the background macro or the builder test -
    # lets go of every held key and mouse button, restores tab, focused account and cursor, and logs it. Anti-AFK keeps running
    # (added v43; replaces macro_abort; changed v44).
    def macro_panic(self):
        if not (self.macro_on or self.bg_job): return self.say("End: nothing is running")
        if self.bg_job: self.bg_job["stop"].set()                         # workers wake up at once, release their keys / buttons; bg_done reports it
        if self.macro_on:
            if self._m_job: self.after_cancel(self._m_job); self._m_job = None
            self.macro_finish(True)
        self.log("END: macro stopped, keys and mouse buttons released", "warn")

    # Releases mouse / keys, restores the previous tab, focused account and cursor, then calls the run's end callback (added v41; changed v42, v43).
    def macro_finish(self, stopped=False):
        if not self.macro_on: return
        self.macro_on = False; self.m_up(); self.m_keys(None, None, False)
        prev_tab, prev_active, prev_unf = self.afk_prev
        if prev_active in self.live() and prev_active != self.active: self.switch_to(prev_active)
        if prev_unf: self.unfocus(True)
        if prev_tab != "Viewer": self.after(800, lambda: self.tv.set(prev_tab))
        user32.SetCursorPos(*self.afk_cursor); self.afk_busy = False
        if not stopped: self.log("Macro done", "ok")
        cb, self.macro_cb = self.macro_cb, None
        if cb: cb()

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

    # ---------- background input and visual builder (added v42) ----------
    # Starts one background job: a coordinator thread runs worker(hw, stop) in one thread per window, waits for all of them and hands the
    # result to the main thread (bg_done). The job is stored in self.<slot> (bg_job = macro / test, afk_job = Anti-AFK); its ["stop"]
    # (an Event) stops it (added v42; changed v44: slot, so Anti-AFK and a macro can run together).
    def bg_start(self, label, hws, worker, on_done=None, slot="bg_job"):
        stop = threading.Event(); setattr(self, slot, {"stop": stop, "label": label, "cb": on_done})
        # Coordinator thread body (see bg_start).
        def run():
            # One worker thread: errors go to the log, never to a Tk widget.
            def one(h):
                try: worker(h, stop)
                except Exception as ex: self.log(f"{label}: error {str(ex)[:70]}", "warn")
            ts = [threading.Thread(target=one, args=(h,), daemon=True) for h in hws]
            for t in ts: t.start()
            for t in ts: t.join()
            self.after(0, lambda: self.bg_done(slot, stop.is_set()))
        threading.Thread(target=run, daemon=True).start()

    # Main thread: a background job has ended; logs it, frees the slot and calls the job's callback (added v42; changed v44: slot).
    def bg_done(self, slot, stopped):
        job = getattr(self, slot); setattr(self, slot, None)
        if not job: return
        self.log(f"{job['label']} {'stopped' if stopped else 'done'}", "warn" if stopped else "ok")
        if job["cb"]: job["cb"]()

    # 'Visual builder' button: shows the Viewer, then opens the builder over the focused window (added v42).
    def builder_open(self):
        if self.builder: self.tv.set("Viewer"); return self.builder.front()
        if self.bld_wait: return
        if self.macro_on or self.afk_busy or self.bg_job: return self.say("Builder: wait until the macro / Anti-AFK round is finished (End stops it)")
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

    # The alert text from the 'Alert text' setting: {msg} = the event, {account} = the account it is about (or empty), {time} (added v43).
    def dc_text(self, msg):
        acct = next((a["name"] for a in self.cfg["accounts"] if msg.startswith(a["name"] + ":")), "")
        return fill(self.cfg["dc_fmt"] or DEFAULTS["dc_fmt"], {"msg": msg, "account": acct, "time": time.strftime("%H:%M:%S")})

    # Send test button (added v41; changed v43: uses the alert text setting).
    def dc_test(self):
        self.collect(); threading.Thread(target=self.discord_send, args=(self.dc_text("test message - alerts work"), True), daemon=True).start()

    # Queues one alert from a short background thread; the same text is skipped for 60 s (added v41; changed v43: alert text setting).
    def notify(self, msg):
        now = time.time()
        if now - self.dc_seen.get(msg, 0) < 60: return
        self.dc_seen[msg] = now
        threading.Thread(target=self.discord_send, args=(self.dc_text(msg),), daemon=True).start()

    # Apply commands button: reads the command box (one 'name = reply' per line) into the config (added v43).
    def dc_cmds_apply(self):
        cmds, p = [], self.cfg["dc_prefix"] or "!"
        for no, raw in enumerate(self.dc_box.get("1.0", "end").splitlines(), 1):
            if not raw.strip(): continue
            name, _, reply = raw.partition("="); name, reply = name.strip().lstrip(p).lower(), reply.strip()
            if not re.fullmatch(r"[a-z0-9_]{1,32}", name) or not reply or len(reply) > 1500 or any(c[0] == name for c in cmds):
                return self.note("Discord commands", f"Line {no}: use  name = reply  (name: letters, digits, _; every name once; reply not empty).")
            cmds.append([name, reply])
        if len(cmds) > 25: return self.note("Discord commands", "At most 25 commands.")
        self.cfg["dc_cmds"] = cmds; self.log(f"Discord commands saved ({len(cmds)})", "ok")

    # Values for the {placeholders} of command replies (main thread only) (added v43).
    def dc_vals(self):
        run, frozen, disc, crashed = self.counts; alive, p = self.live(), self.cfg["dc_prefix"] or "!"
        return {"running": run, "total": len(self.cfg["accounts"]), "frozen": frozen, "disc": disc, "crashed": crashed, "time": time.strftime("%H:%M:%S"),
                "accounts": ", ".join(n for n, h in self.windows.items() if h in alive) or "none", "version": VERSION,
                "commands": ", ".join(p + n for n, _ in self.cfg["dc_cmds"])}

    # Every 6 s while 'Answer commands' is on and the bot is set up: starts one short thread that reads the channel (added v43).
    def dc_poll(self):
        try:
            if self.cfg["dc_cmd_on"] and self.cfg["dc_token"] and self.cfg["dc_chan"].strip().isdigit() and not self.dc_busy:
                self.dc_busy = True; threading.Thread(target=self.dc_fetch, daemon=True).start()
        finally: self.after(6000, self.dc_poll)

    # Thread: reads the channel's newest messages (Discord REST, only ones newer than the last seen; the first read only remembers the newest
    # one, so nothing old is answered) and hands the command words to the main thread. Needs 'Message Content Intent' on the bot (added v43).
    def dc_fetch(self):
        try:
            hdr, url = {"Authorization": f"Bot {dec(self.cfg['dc_token'])}"}, f"https://discord.com/api/v10/channels/{self.cfg['dc_chan'].strip()}/messages"
            first = self.dc_last is None
            r = requests.get(url, headers=hdr, params={"limit": 1} if first else {"after": self.dc_last, "limit": 20}, timeout=10); r.raise_for_status()
            msgs = sorted(r.json(), key=lambda m: int(m["id"]))
            if first: self.dc_last = msgs[-1]["id"] if msgs else "0"
            elif msgs:
                self.dc_last = msgs[-1]["id"]; p, words, empty = (self.cfg["dc_prefix"] or "!").lower(), [], False
                for m in msgs:
                    c = m["content"].strip()
                    if m["author"].get("bot"): continue
                    if not c: empty = True
                    elif c.lower().startswith(p) and c[len(p):].split(): words.append(c[len(p):].split()[0].lower())
                if empty and not words and not self.dc_warned: self.dc_warned = True; self.log("Discord: messages arrive empty - switch on 'Message Content Intent' for the bot", "warn")
                if words: self.after(0, lambda: self.dc_answer(words))
            self.dc_err = ""
        except Exception as ex:
            if str(ex)[:80] != self.dc_err: self.dc_err = str(ex)[:80]; self.log(f"Discord commands: {self.dc_err}", "warn")
        finally: self.after(0, lambda: setattr(self, "dc_busy", False))

    # Main thread: answers the command words with their replies (at most 5 per read), sent one after another from a thread (added v43).
    def dc_answer(self, words):
        cmds, vals = dict(self.cfg["dc_cmds"]), self.dc_vals()
        texts = [fill(cmds[w], vals) for w in words[:5] if w in cmds]
        if texts: threading.Thread(target=lambda: [self.discord_send(t) for t in texts], daemon=True).start()

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
        if self.macro_on or self.bg_job: self.macro_panic(); time.sleep(0.2)       # releases held keys / buttons before closing (added v42; changed v43)
        self.hotkeys(False); self.unembed_all(); self.destroy()

if __name__ == "__main__":
    App().mainloop()
