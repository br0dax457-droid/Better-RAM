"""
AltManager v13 - Windows only.
    pip install customtkinter requests psutil playwright
    python alt_manager_v13.py

Layout: small embedded tiles on the left, the focused instance docked as a real window over the right pane.
Tabs: Dashboard (accounts) | Viewer | Log (timestamped events) | Settings.
Uses the same accounts file (%APPDATA%\\AltManager.json) as every earlier version.
"""
import atexit, base64, ctypes, ctypes.wintypes as wt, json, os, random, re, shutil, socket, stat, subprocess, sys, tempfile, threading, time
import tkinter as tk
from tkinter import messagebox
from urllib.parse import quote

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)   # real pixels, not scaled (must run before any window exists)
except Exception: pass

VERSION = 13                       # bump this in the file you publish; running copies update when it is higher

# ======================= dependencies: install what's missing, re-check weekly =======================
DEPS = {"customtkinter": "customtkinter", "requests": "requests", "psutil": "psutil", "playwright": "playwright"}   # module -> pip name
CORE = ("customtkinter", "requests", "psutil")           # needed to start (playwright is only for "Add via browser")
DEPS_STAMP = os.path.join(os.getenv("APPDATA", "."), "AltManager.deps.json")

def ensure_dependencies():
    import importlib, importlib.util
    try: stamp = json.load(open(DEPS_STAMP))
    except Exception: stamp = {}
    names = sorted(DEPS.values())
    missing = [p for m, p in DEPS.items() if importlib.util.find_spec(m) is None]
    stale = stamp.get("deps") != names or time.time() - stamp.get("checked", 0) > 7 * 86400
    if not missing and not stale: return                 # fast path: straight to the app, no pip, no window
    out = {}
    def work():
        try:
            out["r"] = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "-q",
                                       "--timeout", "10", "--retries", "1", *(names if stale else missing)],
                                      capture_output=True, text=True, timeout=900, creationflags=0x08000000)
        except Exception as ex: out["err"] = str(ex)
    t = threading.Thread(target=work, daemon=True); t.start()
    root = tk.Tk(); root.title("AltManager"); root.configure(bg="#08080a"); root.geometry("380x90"); root.resizable(False, False)
    tk.Label(root, text="Installing required packages..." if missing else "Checking for package updates...",
             bg="#08080a", fg="#ececee", font=("Segoe UI", 11)).pack(expand=True)
    def wait():
        if t.is_alive(): root.after(200, wait)
        else: root.destroy()
    wait(); root.mainloop()
    importlib.invalidate_caches()
    r = out.get("r"); ok = bool(r and r.returncode == 0)
    gone = [m for m in CORE if importlib.util.find_spec(m) is None]
    if gone:
        messagebox.showerror("AltManager", "Could not install: " + ", ".join(gone) + "\n\n" + ((r.stderr if r else out.get("err", "")) or "")[-500:])
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
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, wt.BYTE, wt.DWORD]
user32.SetWindowRgn.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
gdi32 = ctypes.windll.gdi32
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6

# palette: black + deep gray
BG, CARD, FIELD, BTN, BTN_H = "#08080a", "#141518", "#1e2024", "#2a2c32", "#3a3d45"
TXT, MUTED, GREEN, ORANGE, RED = "#ececee", "#8a8d96", "#5fd38d", "#f0a030", "#ff6b6b"

DEFAULTS = {"accounts": [], "games": [], "place": "", "job": "", "delay": 6,
            "pane": 38, "micro": False, "windowWidth": 320, "windowHeight": 240, "badges": True,
            "gfx": True, "fps": 15, "quality": 1, "mute": True,
            "trim": True, "trim_sec": 90, "lowprio": True,
            "afk": False, "afk_min": 8, "afk_off": 8, "afk_gap": 1200,
            "watch": True, "watch_sec": 60, "auto_rejoin": False, "afk_skip": [], "idle_prio": [], "view_order": [],
            "update_url": "", "auto_update": True}
STR_KEYS = {"place", "job", "update_url"}

# ======================= cookies (Windows DPAPI) =======================
class BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

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

def auth_ticket(cookie):
    t = roblox_post("https://auth.roblox.com/v1/authentication-ticket", cookie).headers.get("rbx-authentication-ticket")
    if not t: raise RuntimeError("No ticket - cookie expired or invalid")
    return t

def presence_type(cookie, uid):
    """0 offline, 1 online, 2 in a game, 3 in Studio."""
    r = roblox_post("https://presence.roblox.com/v1/presence/users", cookie, {"userIds": [uid]})
    r.raise_for_status()
    return r.json()["userPresences"][0]["userPresenceType"]

def launch_uri(ticket, place, job=""):
    bt = random.randint(10**10, 10**11)
    req = f"RequestGameJob&gameId={job}" if job else "RequestGame"
    pl = (f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request={req}"
          f"&browserTrackerId={bt}&placeId={place}&isPlayTogetherGame=false")
    return (f"roblox-player:1+launchmode:play+gameinfo:{ticket}+launchtime:{int(time.time()*1000)}"
            f"+placelauncherurl:{quote(pl, safe='')}+browsertrackerid:{bt}"
            f"+robloxLocale:en_us+gameLocale:en_us+channel:+LaunchExp:InApp")

def parse_place(text):
    m = re.search(r"games/(\d+)", text) or re.search(r"(\d{5,})", text)
    return m.group(1) if m else ""

def put(r, key, text, color=None):
    """Update a dashboard label only if its text/colour actually changed (CTk redraws are expensive)."""
    if r.get(key + "_v") == (text, color): return
    r[key + "_v"] = (text, color)
    r[key].configure(text=text, **({"text_color": color} if color else {}))

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

def unlock_settings():
    if os.path.exists(SETTINGS): os.chmod(SETTINGS, stat.S_IREAD | stat.S_IWRITE)

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
WS_EX_LAYERED, LWA_ALPHA = 0x00080000, 2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 1, 2, 4, 0x10, 0x20, 0x40
HWND_TOP = 0
STRIP = WS_POPUP | WS_CHILD | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
STRIP_EX = WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME | WS_EX_APPWINDOW

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

def roblox_windows():
    found = []
    def cb(h, _):
        if user32.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, b, 64)
            if b.value == "WINDOWSCLIENT": found.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found

def pid_of(h):
    p = wt.DWORD(); user32.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value

def win_rect(h):
    r = wt.RECT(); user32.GetWindowRect(h, ctypes.byref(r)); return r

def win_area(h):
    r = win_rect(h); return (r.right - r.left) * (r.bottom - r.top)

def kill_pid(pid):
    try: subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=0x08000000)
    except Exception: pass

def installer_running():
    try: return any((p.info["name"] or "").lower() == "robloxplayerinstaller.exe" for p in psutil.process_iter(["name"]))
    except Exception: return False

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

def user_idle_seconds():
    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(li)
    user32.GetLastInputInfo(ctypes.byref(li))
    return ((kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0

# ---- embedding: tiles are child windows (no top-level minimum size); the focused one is a real docked window ----
ORIG_STYLE = {}                   # hwnd -> original (style, exstyle), restored on release
EMBEDDED, DOCKED = set(), set()   # every window we modified / the subset currently docked as a real window

def _restyle(hw, add, add_ex=0):
    st = user32.GetWindowLongPtrW(hw, GWL_STYLE); ex = user32.GetWindowLongPtrW(hw, GWL_EXSTYLE)
    ORIG_STYLE.setdefault(hw, (st, ex))
    user32.SetWindowLongPtrW(hw, GWL_STYLE, ((st & 0xFFFFFFFF) & ~STRIP) | add)
    user32.SetWindowLongPtrW(hw, GWL_EXSTYLE, (ex & ~STRIP_EX) | add_ex)

def embed_window(hw, parent):
    _restyle(hw, WS_CHILD | WS_VISIBLE)
    user32.SetParent(hw, parent)
    EMBEDDED.add(hw); DOCKED.discard(hw)

def dock_window(hw, owner, sx, sy, w, h, raise_=True):
    """Focused instance: a REAL top-level window (true OS focus/clicks), owned by the manager, parked over the pane."""
    if hw not in DOCKED:
        if hw in EMBEDDED: user32.SetParent(hw, 0)
        clear_region(hw)                                          # the focused window is not clipped
        _restyle(hw, WS_POPUP | WS_VISIBLE, WS_EX_TOOLWINDOW | WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes(hw, 0, 0, LWA_ALPHA)    # starts invisible; App.fade_in reveals it
        user32.SetWindowLongPtrW(hw, GWLP_HWNDPARENT, owner)      # owned: stays above the app, hides with it
        EMBEDDED.add(hw); DOCKED.add(hw)
    user32.SetWindowPos(hw, HWND_TOP, sx, sy, w, h,
                        SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE | (0 if raise_ else SWP_NOZORDER))

BORDER, RADIUS = 2, 10           # tile border thickness / corner radius (px)

RGN = {}                          # hwnd -> (w, h) of the clip region already applied to a game window

def round_region(hw, w, h, r):
    user32.SetWindowRgn(hw, gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2), True)

def clear_region(hw):
    RGN.pop(hw, None); user32.SetWindowRgn(hw, None, True)

def fit_child(hw, w, h):
    """Tile content sits inset inside its (rounded, gray) cell so the cell shows as a border."""
    iw, ih = w - 2 * BORDER, h - 2 * BORDER
    user32.SetWindowPos(hw, HWND_TOP, BORDER, BORDER, iw, ih, SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    if RGN.get(hw) != (iw, ih): RGN[hw] = (iw, ih); round_region(hw, iw, ih, RADIUS - BORDER)

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
    Click = focus that account, press-and-drag onto another tile = reorder."""
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

    def _down(self, e): self.press, self.moved = (e.x_root, e.y_root), False

    def _move(self, e):
        if self.press and (self.moved or abs(e.x_root - self.press[0]) + abs(e.y_root - self.press[1]) > 8):
            self.moved = True; self.cbs[1](e)

    def _up(self, e):
        if self.press: self.cbs[2](e) if self.moved else self.cbs[0]()
        self.press, self.moved = None, False

    def set_color(self, c):
        if self.dot.cget("fg") != c: self.dot.configure(fg=c)

    def raise_above(self, cell_hwnd):
        bh = self.winfo_id()
        if user32.GetWindow(cell_hwnd, 5) != bh:                   # GW_CHILD = current top child
            user32.SetWindowPos(bh, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

# ======================= App =======================
ctk.set_appearance_mode("dark")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        global BORDER, RADIUS
        sc = getattr(self, "_get_window_scaling", lambda: 1.0)()          # display scale (1.0 / 1.25 / 1.5 ...)
        BORDER, RADIUS = max(2, round(2 * sc)), round(10 * sc)             # tile border follows the scale
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()       # real pixels (DPI-aware process)
        w = int(min(0.9 * sw / sc, max(920, 0.6 * sw / sc))); h = int(min(0.9 * sh / sc, max(880, 0.8 * sh / sc)))
        self.title(f"AltManager v{VERSION}"); self.geometry(f"{w}x{h}"); self.minsize(min(820, w), min(700, h))
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_exit)
        self.mutex = kernel32.CreateMutexW(None, True, "ROBLOX_singletonMutex")   # lets several Roblox clients run
        saved = json.load(open(DATA)) if os.path.exists(DATA) else {}
        self.cfg = {**json.loads(json.dumps(DEFAULTS)), **{k: v for k, v in saved.items() if k in DEFAULTS}}
        self._saved = ""
        # per-account runtime state
        self.windows = {}                                   # account name -> hwnd
        self.crashed, self.hung, self.missing, self.procs = {}, {}, {}, {}
        self.cookie_ok, self.prev_state = {}, {}
        self.disconnected, self.offline, self.rejoin_hist = set(), {}, {}
        self.started, self.launch_info = {}, {}             # launch time / (place, job) per account
        # viewer state
        self.cells, self.badges, self.fixes, self.drag = {}, {}, {}, None
        self.active = self.maxed = None
        self.dock_local = self.last_dock = self._relayout = None
        self.press, self.was_down, self.app_fg_top, self._tab = None, False, False, ""
        # background work
        self.launch_jobs, self.launch_lock = 0, threading.Lock()
        self.afk_busy, self.afk_next = False, time.time() + 480
        self.afk_hw = self.afk_pt = None; self.afk_pressed = False
        self.sel, self.rows, self.v = {}, {}, {}
        self.status = tk.StringVar(value="Ready"); self.summary = tk.StringVar(value="")
        self.build(); self.refresh()
        for delay, fn in ((40, self.poll), (1000, self.sync), (2000, self.dash), (600, self.badge_loop),
                          (1500, self.heal_loop), (100, self.track_dock)):
            self.after(delay, fn)
        for fn in (self.maintenance, self.watch_loop):
            threading.Thread(target=fn, daemon=True).start()
        if self.cfg["auto_update"]: self.after(4000, lambda: threading.Thread(target=self.check_update, daemon=True).start())
        self.log("AltManager started")

    @property
    def busy(self):                                         # launching / anti-AFK moves windows: ignore clicks meanwhile
        return self.launch_jobs > 0 or self.afk_busy

    # ---------- UI helpers ----------
    def btn(self, parent, text, cmd, primary=False, w=120, h=38):
        return ctk.CTkButton(parent, text=text, command=cmd, width=w, height=h, corner_radius=12,
                             fg_color=TXT if primary else BTN, hover_color="#ffffff" if primary else BTN_H,
                             text_color=BG if primary else TXT, font=("Segoe UI Semibold", 13))

    def card(self, parent, title=None):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=18); c.pack(fill="x", padx=6, pady=8)
        if title: ctk.CTkLabel(c, text=title, font=("Segoe UI Semibold", 15), text_color=TXT).pack(anchor="w", padx=18, pady=(14, 4))
        return c

    def line(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=18, pady=7); return f

    def entry(self, f, label, key, w=70):
        ctk.CTkLabel(f, text=label, text_color=MUTED).pack(side="left")
        v = tk.StringVar(value=str(self.cfg[key])); self.v[key] = v
        ctk.CTkEntry(f, textvariable=v, width=w, height=34, corner_radius=10, fg_color=FIELD,
                     border_width=0).pack(side="left", padx=(8, 22))

    def check(self, f, label, key):
        v = tk.BooleanVar(value=self.cfg[key]); self.v[key] = v
        ctk.CTkCheckBox(f, text=label, variable=v, onvalue=True, offvalue=False, corner_radius=7,
                        fg_color=TXT, hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H,
                        text_color=TXT).pack(side="left", padx=(0, 24))

    def ask(self, title, prompt, secret=False):
        d = ctk.CTkToplevel(self); d.title(title); d.geometry("480x210"); d.configure(fg_color=CARD)
        d.transient(self); d.after(150, d.grab_set)
        out = {"v": None}
        ctk.CTkLabel(d, text=prompt, justify="left", text_color=TXT).pack(anchor="w", padx=22, pady=(22, 8))
        e = ctk.CTkEntry(d, width=436, height=38, corner_radius=10, fg_color=FIELD, border_width=0,
                         show="•" if secret else ""); e.pack(padx=22); e.focus()
        def ok(*_): out["v"] = e.get(); d.destroy()
        row = ctk.CTkFrame(d, fg_color="transparent"); row.pack(pady=20)
        self.btn(row, "Cancel", d.destroy, w=110).pack(side="left", padx=8)
        self.btn(row, "OK", ok, primary=True, w=110).pack(side="left", padx=8)
        d.bind("<Return>", ok); self.wait_window(d)
        return out["v"]

    # ---------- UI ----------
    def build(self):
        tv = self.tv = ctk.CTkTabview(self, fg_color=BG, corner_radius=18, segmented_button_fg_color=CARD,
                                      segmented_button_selected_color=BTN_H, segmented_button_selected_hover_color=BTN_H,
                                      segmented_button_unselected_color=CARD, segmented_button_unselected_hover_color=BTN)
        tv.pack(fill="both", expand=True, padx=14, pady=(14, 4))
        dash, view, logt, sett = tv.add("Dashboard"), tv.add("Viewer"), tv.add("Log"), tv.add("Settings")

        # --- viewer ---
        vb = ctk.CTkFrame(view, fg_color="transparent"); vb.pack(fill="x", padx=6, pady=(4, 8))
        self.btn(vb, "Maximize app", self.toggle_max, w=130).pack(side="left", padx=6)
        self.btn(vb, "Re-layout", self.unmax, w=110).pack(side="left", padx=6)
        self.active_label = ctk.CTkLabel(view, text="Focused: -", font=("Segoe UI Semibold", 14), text_color=TXT)
        self.active_label.pack(anchor="w", padx=14, pady=(0, 8))
        sb = ctk.CTkFrame(view, fg_color="transparent"); sb.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        ctk.CTkButton(sb, text="Anti-AFK now", command=lambda: self.start_afk(True), width=140, height=68, corner_radius=14,
                      fg_color=TXT, hover_color="#ffffff", text_color=BG,
                      font=("Segoe UI Semibold", 14)).pack(side="left", padx=(0, 12))
        tg = ctk.CTkFrame(sb, fg_color="transparent"); tg.pack(side="left", padx=(0, 6))
        for label, key in (("Anti-AFK", "afk"), ("Connection watch", "watch")):
            row = ctk.CTkFrame(tg, fg_color="transparent"); row.pack(anchor="w", pady=2); self.check(row, label, key)
        af = ctk.CTkFrame(sb, fg_color="transparent"); af.pack(side="left", fill="x", expand=True)
        top = ctk.CTkFrame(af, fg_color="transparent"); top.pack(fill="x")
        ctk.CTkLabel(top, text="AFK on:", text_color=MUTED).pack(side="left", padx=(0, 8))
        self.btn(top, "All", lambda: self.afk_all(True), w=50, h=26).pack(side="left", padx=(0, 6))
        self.btn(top, "None", lambda: self.afk_all(False), w=56, h=26).pack(side="left")
        self.afk_list = ctk.CTkScrollableFrame(af, orientation="horizontal", height=36, fg_color=FIELD, corner_radius=10)
        self.afk_list.pack(fill="x", pady=(4, 0))
        self.stage = tk.Frame(view, bg="#000000", highlightthickness=0)
        self.stage.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.stage.bind("<Configure>", self.on_stage)

        # --- log ---
        lb = ctk.CTkFrame(logt, fg_color="transparent"); lb.pack(fill="x", padx=6, pady=(4, 8))
        self.btn(lb, "Clear", self.clear_log, w=100).pack(side="left", padx=6)
        self.btn(lb, "Open log file", lambda: os.path.exists(LOG) and os.startfile(LOG), w=140).pack(side="left", padx=6)
        self.logbox = ctk.CTkTextbox(logt, fg_color=CARD, corner_radius=14, text_color=TXT,
                                     font=("Consolas", 13), wrap="word", state="disabled")
        self.logbox.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        for tag, col in (("ok", GREEN), ("warn", ORANGE), ("bad", RED), ("info", TXT)):
            self.logbox.tag_config(tag, foreground=col)

        # --- dashboard: game ---
        g = self.card(dash)
        f = self.line(g)
        self.v["place"] = tk.StringVar(value=self.cfg["place"]); self.v["job"] = tk.StringVar(value=self.cfg["job"])
        ctk.CTkEntry(f, textvariable=self.v["place"], width=330, height=38, corner_radius=10, fg_color=FIELD,
                     border_width=0, placeholder_text="Game ID or roblox.com/games/... link").pack(side="left", padx=(0, 10))
        ctk.CTkEntry(f, textvariable=self.v["job"], width=170, height=38, corner_radius=10, fg_color=FIELD,
                     border_width=0, placeholder_text="Job ID (optional)").pack(side="left", padx=(0, 10))
        self.btn(f, "Save game", self.save_game, w=100).pack(side="left", padx=(0, 8))
        f = self.line(g)
        self.combo = ctk.CTkComboBox(f, values=[""], width=330, height=38, corner_radius=10, fg_color=FIELD,
                                     border_width=0, button_color=BTN, button_hover_color=BTN_H,
                                     dropdown_fg_color=CARD, state="readonly", command=self.pick_game)
        self.combo.pack(side="left", padx=(0, 10))
        self.btn(f, "Delete saved", self.del_game, w=110).pack(side="left")
        self.refresh_games()

        # --- dashboard: summary, accounts, actions ---
        s = ctk.CTkFrame(dash, fg_color=CARD, corner_radius=14); s.pack(fill="x", padx=6, pady=(4, 6))
        ctk.CTkLabel(s, textvariable=self.summary, font=("Segoe UI Semibold", 14), text_color=TXT,
                     anchor="w").pack(fill="x", padx=18, pady=12)
        hd = ctk.CTkFrame(dash, fg_color="transparent"); hd.pack(fill="x", padx=6, pady=(2, 0))
        self.btn(hd, "Select all", self.sel_all, w=110, h=30).pack(side="left", padx=6)
        self.btn(hd, "Deselect all", self.sel_none, w=120, h=30).pack(side="left", padx=6)
        self.btn(hd, "Refresh status", self.refresh_status, w=130, h=30).pack(side="right", padx=6)
        self.list = ctk.CTkScrollableFrame(dash, fg_color=CARD, corner_radius=18, height=300)
        self.list.pack(fill="both", expand=True, padx=6, pady=6)
        bar = ctk.CTkFrame(dash, fg_color="transparent"); bar.pack(fill="x", padx=6, pady=(6, 4))
        ctk.CTkButton(bar, text="Launch selected", command=self.launch, width=190, height=130, corner_radius=14,
                      fg_color=TXT, hover_color="#ffffff", text_color=BG,
                      font=("Segoe UI Semibold", 17)).grid(row=0, column=0, rowspan=3, padx=6, pady=4, sticky="ns")
        cols = ([("Rejoin selected", self.rejoin_selected), ("Close selected", self.close_selected), ("Close all", self.close_all)],
                [("Add (paste cookie)", self.add), ("Add via browser", self.add_browser), ("Remove selected", self.remove)])
        for c, items in enumerate(cols, 1):
            for r, (text, cmd) in enumerate(items): self.btn(bar, text, cmd, w=150).grid(row=r, column=c, padx=6, pady=4)

        # --- settings ---
        sc = ctk.CTkScrollableFrame(sett, fg_color=BG); sc.pack(fill="both", expand=True)
        c = self.card(sc, "Layout")
        f = self.line(c); self.entry(f, "Launch delay (s)", "delay", 60); self.entry(f, "Tile area % of viewer width", "pane", 60)
        f = self.line(c); self.check(f, "Micro tiles (exact tile size)", "micro")
        self.entry(f, "Width px", "windowWidth", 60); self.entry(f, "Height px", "windowHeight", 60)
        f = self.line(c)
        ctk.CTkLabel(f, text="Presets", text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(f, values=["320x240", "240x180", "200x150", "160x120", "120x90"], width=120, height=34,
                          corner_radius=10, fg_color=BTN, button_color=BTN_H, button_hover_color=BTN_H,
                          dropdown_fg_color=CARD, command=self.pick_size).pack(side="left", padx=(8, 22))
        self.btn(f, "Apply size", self.retile, w=120).pack(side="left")
        f = self.line(c); self.check(f, "Username badges", "badges")
        c = self.card(sc, "Graphics lock")
        f = self.line(c); self.check(f, "Lock low graphics on launch", "gfx"); self.check(f, "Mute", "mute")
        f = self.line(c); self.entry(f, "FPS cap", "fps", 60); self.entry(f, "Quality (1-10)", "quality", 60)
        f = self.line(c)
        self.btn(f, "Apply now", self.apply_gfx, w=120).pack(side="left", padx=(0, 10))
        self.btn(f, "Unlock file", self.unlock, w=120).pack(side="left")
        c = self.card(sc, "RAM trimmer")
        f = self.line(c); self.check(f, "Auto trim", "trim"); self.check(f, "Lower priority", "lowprio")
        self.entry(f, "Every (s)", "trim_sec", 60)
        f = self.line(c); self.btn(f, "Trim now", self.do_trim, w=120).pack(side="left")
        c = self.card(sc, "Anti-AFK")
        f = self.line(c)
        self.entry(f, "Every (min)", "afk_min", 60); self.entry(f, "Corner offset (px)", "afk_off", 60)
        self.entry(f, "Click gap (ms)", "afk_gap", 70)
        c = self.card(sc, "Connection watch")
        f = self.line(c); self.check(f, "Auto-rejoin (max 3 per 30 min)", "auto_rejoin")
        f = self.line(c); self.entry(f, "Check every (s)", "watch_sec", 60)
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Asks Roblox whether each account is still in a game. A disconnect is flagged after 2 checks in a "
                          "row, so expect 1-2+ minutes. If an account uses 'appear offline', turn it off in the Viewer tab.").pack(anchor="w", padx=18, pady=(0, 14))
        c = self.card(sc, f"Updates  (installed: v{VERSION})")
        f = self.line(c); self.entry(f, "Update link (https)", "update_url", 430)
        f = self.line(c); self.check(f, "Check at launch", "auto_update"); self.btn(f, "Check now", self.check_update_now, w=120).pack(side="left")
        ctk.CTkLabel(c, wraplength=700, justify="left", text_color=MUTED,
                     text="Link to your newest AltManager .py file (for example its GitHub 'Raw' link). It is only installed when its "
                          "VERSION number is higher than this one. Only use a link that you alone can edit.").pack(anchor="w", padx=18, pady=(0, 14))

        ctk.CTkLabel(self, textvariable=self.status, text_color=GREEN, anchor="w").pack(fill="x", padx=24, pady=(2, 12))

    # ---------- logging ----------
    def log(self, msg, kind="info", status=True):
        """Timestamped event -> Log tab + file (+ status bar). Safe to call from any thread."""
        stamp = time.strftime("%H:%M:%S")
        try:
            with open(LOG, "a", encoding="utf-8") as fh: fh.write(f"{time.strftime('%Y-%m-%d')} {stamp}  {msg}\n")
        except Exception: pass
        def ui():
            if status: self.status.set(msg)
            self.logbox.configure(state="normal")
            self.logbox.insert("end", f"{stamp}  {msg}\n", kind)
            if int(self.logbox.index("end-1c").split(".")[0]) > 1500: self.logbox.delete("1.0", "300.0")
            self.logbox.configure(state="disabled"); self.logbox.see("end")
        self.after(0, ui)

    def say(self, text): self.after(0, lambda: self.status.set(text))

    def clear_log(self):
        self.logbox.configure(state="normal"); self.logbox.delete("1.0", "end"); self.logbox.configure(state="disabled")

    # ---------- config ----------
    def collect(self):
        for k, var in self.v.items():
            try: val = var.get()
            except tk.TclError: continue
            if k in STR_KEYS: self.cfg[k] = str(val).strip()
            elif isinstance(var, tk.BooleanVar): self.cfg[k] = bool(val)
            else:
                try: self.cfg[k] = int(val)
                except ValueError: pass

    def save(self):
        self.collect()
        try:
            blob = json.dumps(self.cfg, sort_keys=True)
            if blob != self._saved:
                with open(DATA, "w") as fh: fh.write(blob)
                self._saved = blob
        except Exception: pass

    def sync(self):                                         # every setting change is persisted within a second
        self.save(); self.after(1000, self.sync)

    # ---------- games ----------
    def glabels(self): return [f'{g["name"]}  ({g["place"]})' for g in self.cfg["games"]]

    def refresh_games(self):
        self.combo.configure(values=self.glabels() or [""]); self.combo.set("")

    def pick_game(self, choice):
        L = self.glabels()
        if choice in L: self.v["place"].set(self.cfg["games"][L.index(choice)]["place"])

    def save_game(self):
        self.collect(); pid = parse_place(self.cfg["place"])
        if not pid: return messagebox.showwarning("Game", "Paste a game ID or link first.")
        name = self.ask("Save game", "Name for this game:")
        if not name: return
        self.cfg["games"] = [g for g in self.cfg["games"] if g["place"] != pid] + [{"name": name, "place": pid}]
        self.refresh_games()

    def del_game(self):
        L = self.glabels(); cur = self.combo.get()
        if cur in L: del self.cfg["games"][L.index(cur)]; self.refresh_games()

    # ---------- accounts ----------
    def account(self, name): return next((a for a in self.cfg["accounts"] if a["name"] == name), None)
    def checked(self): return [n for n, v in self.sel.items() if v.get()]
    def sel_all(self): [v.set(True) for v in self.sel.values()]
    def sel_none(self): [v.set(False) for v in self.sel.values()]

    def refresh(self):
        for w in self.list.winfo_children(): w.destroy()
        self.rows = {}
        names = [a["name"] for a in self.cfg["accounts"]]
        self.sel = {n: self.sel.get(n, tk.BooleanVar(value=False)) for n in names}
        for i, n in enumerate(names):
            if i: ctk.CTkFrame(self.list, height=2, corner_radius=0, fg_color=BTN_H).pack(fill="x", padx=18, pady=2)
            f = ctk.CTkFrame(self.list, fg_color=FIELD, corner_radius=14); f.pack(fill="x", pady=3, padx=4)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkCheckBox(f, text=n, variable=self.sel[n], onvalue=True, offvalue=False, corner_radius=7,
                            fg_color=TXT, hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H,
                            text_color=TXT, width=200).grid(row=0, column=0, padx=14, pady=12, sticky="w")
            bad = self.cookie_ok.get(n) is False
            st = ctk.CTkLabel(f, text="Cookie expired - re-login" if bad else "Idle",
                              text_color=RED if bad else MUTED, anchor="w", width=190)
            cpu = ctk.CTkLabel(f, text="", text_color=MUTED, width=56)
            ram = ctk.CTkLabel(f, text="", text_color=MUTED, width=84)
            st.grid(row=0, column=1, padx=6, sticky="w"); cpu.grid(row=0, column=2, padx=4); ram.grid(row=0, column=3, padx=4)
            lp = tk.BooleanVar(value=n in self.cfg["idle_prio"])
            ctk.CTkCheckBox(f, text="Lowest prio", variable=lp, command=lambda n=n, v=lp: self.set_idle_prio(n, v.get()),
                            width=90, checkbox_width=18, checkbox_height=18, corner_radius=5, fg_color=TXT,
                            hover_color="#ffffff", checkmark_color=BG, border_color=BTN_H, text_color=MUTED,
                            font=("Segoe UI", 12)).grid(row=0, column=4, padx=(8, 4))
            self.btn(f, "Show", lambda n=n: self.show(n), w=60).grid(row=0, column=5, padx=(8, 4))
            self.btn(f, "Max", lambda n=n: self.max_instance(n), w=56).grid(row=0, column=6, padx=(0, 12))
            self.rows[n] = {"st": st, "cpu": cpu, "ram": ram}
        self.build_afk_list(names); self.after(50, self.update_rows)

    def set_status(self, name, text, color=MUTED):
        def go():
            r = self.rows.get(name)
            if r: put(r, "st", text, color)
        self.after(0, go)

    def build_afk_list(self, names):
        for w in self.afk_list.winfo_children(): w.destroy()
        skip = set(self.cfg["afk_skip"])
        self.afk_sel = {n: tk.BooleanVar(value=n not in skip) for n in names}
        for n in names:
            ctk.CTkCheckBox(self.afk_list, text=n, variable=self.afk_sel[n], command=self.afk_toggle, width=20,
                            checkbox_width=18, checkbox_height=18, corner_radius=5, fg_color=TXT, hover_color="#ffffff",
                            checkmark_color=BG, border_color=BTN_H, text_color=TXT,
                            font=("Segoe UI", 12)).pack(side="left", padx=(6, 4))

    def afk_all(self, on):
        for v in self.afk_sel.values(): v.set(on)
        self.afk_toggle()

    def afk_toggle(self):
        self.cfg["afk_skip"] = [n for n, v in self.afk_sel.items() if not v.get()]

    def store_account(self, name, cookie, uid):
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a["name"] != name] + \
                               [{"name": name, "cookie": enc(cookie), "id": uid}]
        self.cookie_ok.pop(name, None); self.refresh(); self.log(f"Added account {name}", "ok")

    def add(self):
        c = self.ask("Add account", "Paste the .ROBLOSECURITY cookie\n(treat it like a password):", secret=True)
        if not c: return
        try: uid, name = whoami(c.strip())
        except Exception as ex: return messagebox.showerror("Invalid cookie", str(ex))
        self.store_account(name, c.strip(), uid)

    def add_browser(self):
        self.log("Opening browser - log in there (2FA/captcha work normally). It closes by itself.")
        threading.Thread(target=self._browser_login, daemon=True).start()

    def _browser_login(self):
        try: from playwright.sync_api import sync_playwright
        except ImportError:
            return self.after(0, lambda: messagebox.showerror("Missing package", "Run:  pip install playwright"))
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

    def remove(self):
        gone = set(self.checked())
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a["name"] not in gone]
        self.refresh()

    # ---------- graphics lock ----------
    def apply_gfx(self):
        self.collect()
        try:
            apply_graphics(self.cfg["fps"], self.cfg["quality"], self.cfg["mute"])
            self.log(f"Graphics lock written (FPS {self.cfg['fps']}, quality {self.cfg['quality']}), file is read-only")
        except Exception as ex: messagebox.showerror("Settings", str(ex))

    def unlock(self):
        try: unlock_settings(); self.log("Graphics settings file unlocked")
        except Exception as ex: messagebox.showerror("Settings", str(ex))

    # ---------- launching / closing / rejoining ----------
    def launch(self):
        self.save(); place = parse_place(self.cfg["place"])
        if not place: return messagebox.showwarning("Game", "Enter a game ID or roblox.com/games link.")
        if self.cfg["gfx"]: self.apply_gfx()
        todo = [a for a in self.cfg["accounts"] if a["name"] in self.checked()]
        if todo: self.log(f"Launching {len(todo)} account(s) into place {place}")
        self.start_launch(todo, place, self.cfg["job"])

    def start_launch(self, accounts, place, job):
        if accounts: threading.Thread(target=self._launch_worker, args=(accounts, place, job), daemon=True).start()

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
        finally:
            self.launch_jobs -= 1

    def launch_one(self, a, place, job):
        n = a["name"]; self.crashed.pop(n, None)
        if self.cookie_ok.get(n) is False:
            self.set_status(n, "Cookie expired - skipped", RED); return self.log(f"{n}: skipped (cookie expired)", "warn")
        for i in range(120):                                 # never stack launches on a running installer/updater
            if not installer_running(): break
            if i == 0: self.log(f"{n}: waiting for the Roblox updater to finish", "warn", status=False)
            self.set_status(n, "Waiting for Roblox updater..."); time.sleep(1)
        self.set_status(n, "Getting ticket...")
        ticket = auth_ticket(dec(a["cookie"]))
        before = set(roblox_windows())
        os.startfile(launch_uri(ticket, place, job))
        self.set_status(n, "Starting...")
        for _ in range(90):
            time.sleep(1)
            if set(roblox_windows()) - before: break
        else:
            self.set_status(n, "Timed out", RED); return self.log(f"{n}: Roblox window never appeared (timed out)", "bad")
        time.sleep(4)                                        # splash -> game window: take the biggest new window
        cands = list(set(roblox_windows()) - before)
        if not cands:
            self.set_status(n, "Window vanished", RED); return self.log(f"{n}: window vanished right after starting", "bad")
        self.windows[n] = max(cands, key=win_area)
        self.hung[n] = self.missing[n] = self.offline[n] = 0
        self.started[n] = time.time(); self.launch_info[n] = (place, job)
        if n in self.cfg["idle_prio"]: self.set_priority(n, 0x40)
        self.log(f"{n}: launched", "ok", status=False)
        self.after(0, self.retile)
        time.sleep(self.cfg["delay"])

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
            r["st"].configure(text=status, text_color=MUTED); r["cpu"].configure(text=""); r["ram"].configure(text="")

    def close_selected(self):
        names = [n for n in self.checked() if n in self.windows]
        if not names: return self.say("Tick the running accounts you want to close first")
        for n in names: self.kill_instance(n)
        self.retile(); self.log(f"Closed {len(names)} instance(s): {', '.join(names)}")

    def close_all(self):
        names = list(self.windows)
        for n in names: self.kill_instance(n)
        self.crashed.clear(); self.active = None; self.refresh()
        if names: self.log(f"Closed all instances ({len(names)})")

    def rejoin_selected(self):
        names = self.checked()
        if not names: return self.say("Tick the accounts you want to rejoin first")
        self.rejoin(names)

    def rejoin(self, names):
        """Close the instance (if any) and start it again in the same game."""
        default = (parse_place(self.cfg["place"]), self.cfg["job"])
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

    def watch_loop(self):
        nxt = time.time() + 60
        while True:
            time.sleep(3)
            try:
                if not self.cfg["watch"] or time.time() < nxt: continue
                nxt = time.time() + max(30, self.cfg["watch_sec"])
                self.check_presence(list(self.windows))
            except Exception as ex:
                self.log(f"Connection watch error: {str(ex)[:70]}", "warn", status=False)

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

    def auto_rejoin(self, n):
        now = time.time(); hist = [t for t in self.rejoin_hist.get(n, []) if now - t < 1800]
        if len(hist) >= 3: return self.log(f"{n}: auto-rejoin paused (3 attempts in 30 min)", "warn")
        self.rejoin_hist[n] = hist + [now]
        self.log(f"{n}: auto-rejoin attempt {len(hist) + 1}", "warn")
        self.rejoin([n])

    # ---------- viewer layout ----------
    def stage_size(self):
        return max(self.stage.winfo_width(), 200), max(self.stage.winfo_height(), 200)

    def live(self):
        wins = [h for h in self.windows.values() if user32.IsWindow(h)]
        if self.active not in wins: self.active = None
        if self.maxed not in wins: self.maxed = None
        return wins

    def plan(self, n):
        """-> (tile slots, focus-pane rect, tiles fit?) in stage coordinates."""
        W, H = self.stage_size()
        multi = n > 1
        tw = int(W * max(20, min(70, self.cfg["pane"])) / 100) if multi else W
        fits = True
        if self.cfg["micro"]:
            w, h = max(40, self.cfg["windowWidth"]), max(40, self.cfg["windowHeight"])
            cols = max(1, tw // w); cw, ch = w, h
            fits = w <= tw and -(-n // cols) * h <= H
        if not self.cfg["micro"] or not fits: cols, cw, ch, w, h = grid_plan(n, tw, H)   # exact size doesn't fit -> auto
        slots = [((i % cols) * cw, (i // cols) * ch, w, h) for i in range(n)]
        if multi:
            fw = W - tw; w2 = min(fw, int(H * 16 / 9)); h2 = int(w2 * 9 / 16)
            fr = (tw + (fw - w2) // 2, (H - h2) // 2, w2, h2)
        else:
            fr = (0, 0, W, H)
        return slots, fr, fits

    def retile(self):
        order = self.cfg["view_order"]
        self.windows = dict(sorted(self.windows.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)))
        self.collect(); wins = self.live()
        if not wins: return
        if self.tv.get() != "Viewer": self.tv.set("Viewer")
        self.update_idletasks(); self.fixes.clear()
        if self.maxed in wins:                               # one instance fills the viewer, the rest are hidden
            W, H = self.stage_size()
            for hw in wins:
                if hw == self.maxed: self.place(hw, (0, 0, W, H))
                else: self.cell_for(hw).place_forget()
            self.stage.update_idletasks()
            self.say("Maximized - 'Re-layout' in the Viewer tab brings the tiles back")
            self.after(30, self.update_badges); self.after(60, lambda h=self.maxed: self.give_focus(h))
            return
        if self.active is None: self.active = wins[0]
        slots, fr, fits = self.plan(len(wins))
        for i, hw in enumerate(wins):
            self.place(hw, fr if hw == self.active else slots[i])
        self.stage.update_idletasks()
        big = sum(1 for i, hw in enumerate(wins) if hw != self.active
                  and (win_rect(hw).right - win_rect(hw).left > slots[i][2] + 3 or win_rect(hw).bottom - win_rect(hw).top > slots[i][3] + 3))
        msg = f"Layout: {len(wins)} windows, tiles {slots[0][2]}x{slots[0][3]}"
        if big: msg += f" - {big} resisted resizing and are cropped to their tile"
        if not fits: msg += " - micro tiles don't fit this screen, using automatic sizes"
        self.say(msg); self.after(30, self.update_badges); self.set_active_label()

    def place(self, hw, rect):
        x, y, w, h = rect
        cell = self.cell_for(hw)
        cell.place(x=x, y=y, width=w, height=h)
        if cell.rgn != (w, h): cell.rgn = (w, h); round_region(cell.winfo_id(), w, h, RADIUS)
        if hw == self.active:                                # focused instance = real window docked over the pane
            self.dock_local = rect; self.dock(hw)
        else:
            if hw in DOCKED: self.undock(hw, cell)           # just lost focus -> back into its tile
            fit_child(hw, w, h)

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

    # ---------- drag a tile's name tag onto another tile to reorder ----------
    def tile_at(self, x, y, exclude):
        for hw, c in self.cells.items():
            if hw == exclude or hw in DOCKED or not c.winfo_ismapped(): continue
            if c.winfo_rootx() <= x < c.winfo_rootx() + c.winfo_width() and c.winfo_rooty() <= y < c.winfo_rooty() + c.winfo_height():
                return hw

    def drag_tile(self, n, e):
        if self.drag is None:
            ghost = tk.Label(self.stage, text=n, bg=TXT, fg=BG, font=("Segoe UI Semibold", 11), padx=10, pady=4)
            self.drag = {"hw": self.windows.get(n), "ghost": ghost, "target": None}
        d = self.drag
        d["ghost"].place(x=e.x_root - self.stage.winfo_rootx() + 10, y=e.y_root - self.stage.winfo_rooty() + 10)
        d["ghost"].tkraise()
        t = self.tile_at(e.x_root, e.y_root, d["hw"])
        if t != d["target"]:
            if d["target"] in self.cells: self.cells[d["target"]].configure(bg=BTN_H)
            if t: self.cells[t].configure(bg=TXT)                # highlighted border = drop target
            d["target"] = t

    def drop_tile(self, n, e):
        d, self.drag = self.drag, None
        if not d: return
        d["ghost"].destroy()
        if d["target"] in self.cells: self.cells[d["target"]].configure(bg=BTN_H)
        dst = next((k for k, h in self.windows.items() if h == d["target"]), None)
        if dst is None or dst == n: return
        names = list(self.windows); names.insert(names.index(dst), names.pop(names.index(n)))
        self.cfg["view_order"] = names + [x for x in self.cfg["view_order"] if x not in names]
        self.retile()

    def drop_cell(self, hw):
        EMBEDDED.discard(hw); DOCKED.discard(hw); ORIG_STYLE.pop(hw, None); RGN.pop(hw, None)
        c = self.cells.pop(hw, None)
        if c: c.destroy()

    def unembed_all(self):
        for hw in list(EMBEDDED): unembed_window(hw)
        for hw in list(self.cells): self.cells.pop(hw).destroy()

    def top_hwnd(self): return user32.GetAncestor(self.winfo_id(), 2)

    def dock(self, hw):
        x, y, w, h = self.dock_local
        sx, sy = self.stage.winfo_rootx() + x, self.stage.winfo_rooty() + y
        fresh = hw not in DOCKED
        dock_window(hw, self.top_hwnd(), sx, sy, w, h, raise_=fresh)
        self.last_dock = (sx, sy, w, h)
        if fresh: self.after(60, lambda: self.give_focus(hw)); self.fade_in(hw)
        self.set_active_label()

    def undock(self, hw, cell):
        user32.SetWindowLongPtrW(hw, GWLP_HWNDPARENT, 0); DOCKED.discard(hw)
        embed_window(hw, cell.winfo_id())

    def give_focus(self, hw):
        """Only a real top-level window can hold true OS focus, so this applies to the docked instance."""
        try:
            if user32.IsWindow(hw) and hw in DOCKED: user32.SetForegroundWindow(hw)
        except Exception: pass

    def fade_in(self, hw, a=0):
        """Short alpha ramp for a newly focused window; the layered flag is removed again at the end (no runtime cost)."""
        if hw not in DOCKED or not user32.IsWindow(hw): return
        a += 32
        if a < 255:
            user32.SetLayeredWindowAttributes(hw, 0, a, LWA_ALPHA); self.after(20, lambda: self.fade_in(hw, a))
        else:
            user32.SetWindowLongPtrW(hw, GWL_EXSTYLE, user32.GetWindowLongPtrW(hw, GWL_EXSTYLE) & ~WS_EX_LAYERED)

    def set_active_label(self):
        name = next((n for n, h in self.windows.items() if h == self.active), None)
        self.active_label.configure(text=f"Focused: {name}" if name else "Focused: -")

    def switch_to(self, hw):
        if hw == self.active: return
        old, self.active = self.active, hw
        wins = self.live()
        if hw not in wins: return
        slots, fr, _ = self.plan(len(wins))
        if old in wins: self.place(old, slots[wins.index(old)])
        self.place(hw, fr)
        self.stage.update_idletasks()
        self.after(10, self.update_badges); self.after(50, lambda: self.give_focus(hw)); self.after(150, self.verify_layout)

    def show(self, n):
        hw = self.windows.get(n)
        if not hw or hw not in self.live(): return
        if self.maxed: self.maxed = None; self.retile()
        self.tv.set("Viewer"); self.switch_to(hw)

    def max_instance(self, n):
        hw = self.windows.get(n)
        if not hw or not user32.IsWindow(hw): return self.say(f"{n} is not running")
        self.maxed = self.active = hw; self.retile()

    def unmax(self): self.maxed = None; self.retile()
    def toggle_max(self): self.state("normal" if self.state() == "zoomed" else "zoomed")
    def pick_size(self, choice):
        w, h = choice.split("x"); self.v["windowWidth"].set(w); self.v["windowHeight"].set(h); self.retile()

    def on_stage(self, _=None):
        if self._relayout: self.after_cancel(self._relayout)
        self._relayout = self.after(200, self._do_relayout)

    def _do_relayout(self):
        self._relayout = None
        if self.cells and self.tv.get() == "Viewer" and self.stage.winfo_width() > 200: self.retile()

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
        self.after(40 if self._tab == "Viewer" and self.cells else 200, self.poll)

    def track_dock(self):
        """Keep the docked window glued to the focus pane when the app moves/resizes; hide it off the Viewer tab."""
        try:
            hw = self.active
            if hw and hw in DOCKED and user32.IsWindow(hw) and self.dock_local:
                if self.tv.get() != "Viewer" or self.state() == "iconic":
                    if user32.IsWindowVisible(hw): user32.ShowWindow(hw, 0)
                else:
                    x, y, w, h = self.dock_local
                    want = (self.stage.winfo_rootx() + x, self.stage.winfo_rooty() + y, w, h)
                    if want != self.last_dock or not user32.IsWindowVisible(hw):
                        user32.SetWindowPos(hw, 0, *want, SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
                        self.last_dock = want
        finally:
            self.after(80, self.track_dock)

    def verify_layout(self):
        """Self-heal: a tile that re-parented itself, regained its frame, or drifted gets put back."""
        if not (self.cells and self.tv.get() == "Viewer"): return
        for hw, cell in list(self.cells.items()):
            if hw in DOCKED or not user32.IsWindow(hw) or not cell.winfo_ismapped(): continue
            ch = cell.winfo_id(); w, h = cell.winfo_width(), cell.winfo_height()
            st = user32.GetWindowLongPtrW(hw, GWL_STYLE) & 0xFFFFFFFF
            if user32.GetParent(hw) != ch or not (st & WS_CHILD) or (st & (WS_CAPTION | WS_THICKFRAME)):
                embed_window(hw, ch); fit_child(hw, w, h); continue
            r = win_rect(hw)
            if (abs(r.right - r.left - w + 2 * BORDER) > 2 or abs(r.bottom - r.top - h + 2 * BORDER) > 2) and self.fixes.get(hw, 0) < 3:
                self.fixes[hw] = self.fixes.get(hw, 0) + 1   # stop nagging a window that truly can't resize
                fit_child(hw, w, h)

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

    def update_rows(self):
        run = frozen = disc = crashed = 0; ram = cpu_t = 0.0
        for n, hw in list(self.windows.items()):            # gone for 2 checks in a row = crashed / closed
            self.missing[n] = 0 if user32.IsWindow(hw) else self.missing.get(n, 0) + 1
            if self.missing[n] >= 2:
                self.crashed[n] = time.strftime("%H:%M")
                self.windows.pop(n); self.procs.pop(n, None); self.prev_state.pop(n, None); self.disconnected.discard(n)
                self.drop_cell(hw)
                self.log(f"{n}: window disappeared - crashed or closed", "bad")
        for a in self.cfg["accounts"]:
            n = a["name"]; r = self.rows.get(n)
            if not r: continue
            if n in self.windows:
                hw = self.windows[n]
                self.hung[n] = self.hung.get(n, 0) + 1 if user32.IsHungAppWindow(hw) else 0
                cpu, mb = self.usage(n, pid_of(hw))
                if self.hung[n] >= 2: state, text, col = "frozen", "Frozen (not responding)", ORANGE; frozen += 1
                elif n in self.disconnected: state, text, col = "disc", "Disconnected - not in a game", RED; disc += 1
                else: state, text, col = "run", "Running", GREEN; run += 1
                if state != self.prev_state.get(n):
                    if state == "frozen": self.log(f"{n}: not responding", "warn", status=False)
                    elif self.prev_state.get(n) == "frozen": self.log(f"{n}: responding again", "ok", status=False)
                    self.prev_state[n] = state
                if cpu is not None: cpu_t += cpu; ram += mb
                put(r, "st", text, col)
                put(r, "cpu", "n/a" if cpu is None else f"{cpu:.0f}%"); put(r, "ram", "n/a" if mb is None else f"{mb:.0f} MB")
            elif n in self.crashed:
                crashed += 1
                put(r, "st", f"Crashed / closed ({self.crashed[n]})", RED); put(r, "cpu", "-"); put(r, "ram", "-")
        txt = (f"Running {run}   Frozen {frozen}   Disconnected {disc}   Crashed {crashed}      "
                         f"RAM {ram/1024:.1f} GB   CPU {cpu_t:.0f}%")
        if txt != self.summary.get(): self.summary.set(txt)

    def refresh_status(self):
        """Re-check every account now: clear stale crash notes, redraw usage, ask Roblox who is really in a game."""
        for n in [n for n in self.crashed if n not in self.windows]: del self.crashed[n]
        self.missing.clear()
        for a in self.cfg["accounts"]:
            r = self.rows.get(a["name"])
            if r and a["name"] not in self.windows:
                bad = self.cookie_ok.get(a["name"]) is False
                put(r, "st", "Cookie expired - re-login" if bad else "Idle", RED if bad else MUTED); put(r, "cpu", ""); put(r, "ram", "")
        self.update_rows(); self.say("Refreshing status...")
        threading.Thread(target=self._refresh_presence, daemon=True).start()

    def _refresh_presence(self):
        try: self.check_presence(list(self.windows))
        except Exception as ex: self.log(f"Status refresh error: {str(ex)[:70]}", "warn", status=False)
        self.after(1500, self.update_rows); self.after(1500, lambda: self.say("Status refreshed"))

    def dash(self):
        try: self.update_rows()
        finally: self.after(2000, self.dash)

    # ---------- RAM trim ----------
    def prio_class(self, n):
        return 0x40 if n in self.cfg["idle_prio"] else 0x4000 if self.cfg["lowprio"] else 0x20   # IDLE / BELOW_NORMAL / NORMAL

    def set_priority(self, n, cls):
        hw = self.windows.get(n)
        hp = hw and user32.IsWindow(hw) and kernel32.OpenProcess(0x0200 | 0x0400, False, pid_of(hw))
        if hp: kernel32.SetPriorityClass(hp, cls); kernel32.CloseHandle(hp)

    def set_idle_prio(self, n, on):
        s = set(self.cfg["idle_prio"]); (s.add if on else s.discard)(n)
        self.cfg["idle_prio"] = sorted(s); self.set_priority(n, self.prio_class(n))
        self.log(f"{n}: lowest priority {'on' if on else 'off'}", status=False)

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

    # ---------- anti-AFK: visit each instance and click for real (a tile can't hold OS focus) ----------
    def run_seq(self, steps):
        if not steps: return
        d, fn = steps[0]
        def go():
            try: fn()
            finally: self.run_seq(steps[1:])
        self.after(d, go)

    def start_afk(self, force=False):
        if self.afk_busy: return
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
        self.log(f"Anti-AFK round started ({len(wins)} instances)", status=False)
        self.run_seq(steps)

    def afk_aim(self, hw):
        self.afk_hw = hw
        rc = wt.RECT(); user32.GetClientRect(hw, ctypes.byref(rc)); off = max(1, self.cfg["afk_off"])
        pt = wt.POINT(max(1, rc.right - off), max(1, rc.bottom - off)); user32.ClientToScreen(hw, ctypes.byref(pt))
        user32.SetCursorPos(pt.x, pt.y); self.afk_pt = pt

    def afk_down(self):
        pt = self.afk_pt
        self.afk_pressed = bool(pt and self.afk_hw and user32.IsWindow(self.afk_hw)
                                and self.owner_of(user32.WindowFromPoint(pt)) == self.afk_hw)   # never click anything else
        if self.afk_pressed: user32.mouse_event(2, 0, 0, 0, 0)

    def afk_up(self):
        if self.afk_pressed: user32.mouse_event(4, 0, 0, 0, 0); self.afk_pressed = False

    def afk_finish(self):
        prev_tab, prev_active = self.afk_prev
        if prev_active in self.live() and prev_active != self.active: self.switch_to(prev_active)
        if prev_tab != "Viewer": self.after(800, lambda: self.tv.set(prev_tab))
        user32.SetCursorPos(*self.afk_cursor)
        self.afk_busy = False
        self.log("Anti-AFK round done", "ok")

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
                self.log(f"Maintenance error: {str(ex)[:60]}", "warn", status=False)

    # ---------- self-update ----------
    def check_update_now(self):
        self.collect(); threading.Thread(target=self.check_update, args=(True,), daemon=True).start()

    def check_update(self, manual=False):
        """Download the file behind the update link; install it only if it is valid and has a higher VERSION."""
        url = self.cfg["update_url"].strip()
        if not url.lower().startswith("https://"):
            if manual: self.after(0, lambda: messagebox.showinfo("Updates", "Enter an https:// update link in Settings first."))
            return
        try:
            r = requests.get(url, timeout=10); r.raise_for_status()
            text = r.content.decode("utf-8")
            m = re.search(r"^VERSION\s*=\s*(\d+)", text, re.M)
            if not m or "class App" not in text or not 5000 < len(text) < 2_000_000: raise ValueError("link is not an AltManager file")
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
            self.log(f"Update check failed: {str(ex)[:80]}", "warn", status=manual)

    def offer_restart(self, new):
        n = len(self.live())
        msg = f"AltManager v{new} was downloaded and installed.\n\nRestart now to use it?"
        if n: msg += f"\n\n{n} Roblox window(s) will be released to the desktop (not closed)."
        if messagebox.askyesno("Update installed", msg): self.restart()

    def restart(self):
        self.save()
        subprocess.Popen([sys.executable, os.path.abspath(__file__)], creationflags=0x00000008)   # DETACHED_PROCESS
        self.log("Restarting for update", status=False); self.unembed_all(); self.destroy()

    # ---------- exit ----------
    def on_exit(self):
        if self.windows:
            ans = messagebox.askyesnocancel("Close AltManager",
                "Close the Roblox instances too?\n\nYes = close them\nNo = release them to the desktop\nCancel = stay open")
            if ans is None: return
            if ans:
                for hw in list(self.windows.values()): kill_pid(pid_of(hw))
        self.save(); self.log("AltManager closed", status=False)
        self.unembed_all(); self.destroy()

if __name__ == "__main__":
    App().mainloop()
