import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import random, os, sys, time

try:
    import ctypes
    import ctypes.wintypes as wt
    _WIN32 = True
    user32 = ctypes.windll.user32
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        DWMWA_CLOAKED = 14
        _DWM = True
    except Exception:
        _DWM = False
except Exception:
    _WIN32 = False
    _DWM   = False

def get_battery_status():
    """Returns (percent, is_charging) or (None, None) if unavailable."""
    if not _WIN32:
        return None, None
    try:
        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus",        ctypes.c_byte),
                ("BatteryFlag",         ctypes.c_byte),
                ("BatteryLifePercent",  ctypes.c_byte),
                ("SystemStatusFlag",    ctypes.c_byte),
                ("BatteryLifeTime",     ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]
        sps = SYSTEM_POWER_STATUS()
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps))
        percent     = sps.BatteryLifePercent if sps.BatteryLifePercent != 255 else None
        is_charging = sps.ACLineStatus == 1
        return percent, is_charging
    except Exception:
        return None, None

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SPRITE_PATH = os.path.join(SCRIPT_DIR, "cat_sprite.png")

CELL        = 64
SCALE       = 2
CAT_PX      = CELL * SCALE          # 128 px

FPS         = 10
WALK_SPEED  = 3
GRAVITY     = 2.5
MAX_FALL    = 20
FOOT_OFFSET = 16 * SCALE            # 32 px
TRANS       = "#010101"

ANIM_MAP = {
    "walk_right": (5,  6),
    "walk_left":  (4,  6),
    "idle_sit":   (12, 4),
    "tail_wag":   (19, 4),
    "stand_wag":  (25, 4),
    "lie":        (27, 3),
    "sleep":      (48, 1),
    "scratch":    (17, 3),
    "meow":       (14, 3),
    "yawn":       (43, 3),
}

STATE_OPTS = {
    "idle":       ["idle_sit", "tail_wag", "scratch"],
    "sit":        ["lie", "sleep", "lie"],
    "pet":        ["stand_wag", "meow", "tail_wag"],
    "walk_right": ["walk_right"],
    "walk_left":  ["walk_left"],
    "drag":       ["hind_legs"],
    "talking":    ["idle_sit", "tail_wag"],   # animations used while speaking
}

STATE_DUR = {
    "idle":       (4, 10),
    "sit":        (60, 90),  # long enough that sleep anim plays for ~1 min
    "pet":        (2,  2),
    "walk_right": (1,  1),
    "walk_left":  (1,  1),
    "talking":    (99, 99),  # held externally by bubble duration
}

def load_frames(path: str) -> dict:
    sheet = Image.open(path).convert("RGBA")
    data  = sheet.load()
    W, H  = sheet.size
    for y in range(H):
        for x in range(W):
            r, g, b, a = data[x, y]
            if r + g + b < 30:
                data[x, y] = (0, 0, 0, 0)
    out = {}
    for name, (row, n) in ANIM_MAP.items():
        frames = []
        for col in range(n):
            cell = sheet.crop((col*CELL, row*CELL, (col+1)*CELL, (row+1)*CELL))
            cell = cell.resize((CAT_PX, CAT_PX), Image.NEAREST)
            frames.append(ImageTk.PhotoImage(cell))
        out[name] = frames

    hind_path = os.path.join(SCRIPT_DIR, "on_hind_legs.png")
    if os.path.exists(hind_path):
        hind = Image.open(hind_path).convert("RGBA")
        hd   = hind.load()
        hw, hh = hind.size
        for y in range(hh):
            for x in range(hw):
                r, g, b, a = hd[x, y]
                if r + g + b < 30:
                    hd[x, y] = (0, 0, 0, 0)
        hind = hind.resize((CAT_PX, CAT_PX), Image.NEAREST)
        out["hind_legs"] = [ImageTk.PhotoImage(hind)]
    else:
        out["hind_legs"] = [out["idle_sit"][0]]

    return out

def _is_real_window(hwnd, my_hwnd):
    if hwnd == my_hwnd:                  return False
    if not user32.IsWindowVisible(hwnd): return False
    if _DWM:
        try:
            c = wt.DWORD(0)
            dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                          ctypes.byref(c), ctypes.sizeof(c))
            if c.value: return False
        except Exception:
            pass
    WS_CAPTION = 0x00C00000
    WS_EX_TOOL = 0x00000080
    if not (user32.GetWindowLongW(hwnd, -16) & WS_CAPTION): return False
    if   user32.GetWindowLongW(hwnd, -20) & WS_EX_TOOL:     return False
    return True


def get_floor_y(cat_x, cat_y, my_hwnd, screen_h):
    cat_cx     = cat_x + CAT_PX // 2
    cat_bottom = cat_y + CAT_PX - FOOT_OFFSET
    best = float(screen_h - CAT_PX + FOOT_OFFSET - 48)
    if not _WIN32:
        return best
    candidates = []
    tb = user32.FindWindowW("Shell_TrayWnd", None)
    if tb:
        r = wt.RECT()
        user32.GetWindowRect(tb, ctypes.byref(r))
        if r.left <= cat_cx <= r.right:
            surface_top = r.top
            land_y      = surface_top - CAT_PX + FOOT_OFFSET
            if surface_top >= cat_bottom - 5:
                candidates.append(land_y)
    wins = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_int)
    def _cb(hwnd, _):
        if not _is_real_window(hwnd, my_hwnd): return True
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left < 200 or r.bottom - r.top < 80: return True
        wins.append((r.left, r.top, r.right, r.bottom))
        return True
    user32.EnumWindows(EnumProc(_cb), 0)
    for wl, wt_, wr, wb in wins:
        if wl <= cat_cx <= wr:
            surface_top = wt_
            land_y      = surface_top - CAT_PX + FOOT_OFFSET
            if surface_top >= cat_bottom - 5:
                candidates.append(land_y)
    if candidates:
        best = min(candidates, key=lambda y: abs(y - cat_y))
    return best


def get_random_sit_spot(my_hwnd, screen_w, screen_h):
    spots = []
    if not _WIN32:
        return None
    tb = user32.FindWindowW("Shell_TrayWnd", None)
    if tb:
        r = wt.RECT()
        user32.GetWindowRect(tb, ctypes.byref(r))
        tb_w  = r.right - r.left
        sit_y = r.top - CAT_PX + FOOT_OFFSET
        for _ in range(6):
            rx = r.left + random.randint(CAT_PX, max(CAT_PX+1, tb_w - CAT_PX))
            spots.append((rx, sit_y))
    wins = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_int)
    def _cb(hwnd, _):
        if not _is_real_window(hwnd, my_hwnd): return True
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w = r.right - r.left
        h = r.bottom - r.top
        if w < 300 or h < 80: return True
        wins.append((r.left, r.top, r.right, r.bottom))
        return True
    user32.EnumWindows(EnumProc(_cb), 0)
    for wl, wt_, wr, wb in wins:
        win_w = wr - wl
        if win_w < CAT_PX * 2: continue
        sit_y = wt_ - CAT_PX + FOOT_OFFSET
        if sit_y < 0 or sit_y > screen_h - CAT_PX: continue
        rx = wl + random.randint(CAT_PX, win_w - CAT_PX)
        spots.append((rx, sit_y))
    return random.choice(spots) if spots else None


class SpeechBubble(tk.Toplevel):
    """Rounded speech bubble that sits above the cat."""

    def __init__(self, master, text: str, cat_x: int, cat_y: int,
                 duration_ms: int = 8000, color: str = "#FFFDE7",
                 on_close=None):
        super().__init__(master)
        self.on_close = on_close
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", TRANS)
        self.config(bg=TRANS)

        pad  = 14
        font = ("Segoe UI", 10, "bold")
        tmp  = tk.Label(self, text=text, font=font, wraplength=220)
        tmp.update_idletasks()
        tw   = min(tmp.winfo_reqwidth() + pad*2, 260)
        th   = tmp.winfo_reqheight() + pad*2
        tmp.destroy()

        bw = tw + 20
        bh = th + 20

        self.canvas = tk.Canvas(self, width=bw, height=bh,
                                bg=TRANS, highlightthickness=0)
        self.canvas.pack()

        r = 12
        x1, y1, x2, y2 = 4, 4, bw - 4, th + 4
        self._round_rect(x1, y1, x2, y2, r, fill=color, outline="#555", width=1)
        tx = x1 + 30
        self.canvas.create_polygon(
            tx, y2, tx + 14, y2, tx + 6, y2 + 14,
            fill=color, outline="#555", width=1)
        self.canvas.create_text(
            (x1 + x2) // 2, (y1 + y2) // 2,
            text=text, font=font, fill="#333",
            width=tw - 4, justify="center")

        # Position bubble just above the cat's head (not too high)
        # cat_y is the window top; cat head is roughly top 40% of sprite
        head_top = cat_y + int(CAT_PX * 0.10)   # ~13px down from sprite top
        bx = cat_x - 10
        by = head_top - bh                        # tail points down to head
        sw = master.winfo_screenwidth()
        bx = max(0, min(bx, sw - bw))
        by = max(0, by)
        self.geometry(f"{bw}x{bh}+{bx}+{by}")
        self.after(duration_ms, self._close)

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [
            x1+r, y1,   x2-r, y1,
            x2,   y1,   x2,   y1+r,
            x2,   y2-r, x2,   y2,
            x2-r, y2,   x1+r, y2,
            x1,   y2,   x1,   y2-r,
            x1,   y1+r, x1,   y1,
            x1+r, y1,
        ]
        self.canvas.create_polygon(pts, smooth=True, **kw)

    def move_to(self, cat_x: int, cat_y: int):
        """Reposition the bubble to follow the cat."""
        try:
            bw = self.winfo_width()
            bh = self.winfo_height()
            head_top = cat_y + int(CAT_PX * 0.10)
            bx = cat_x - 10
            by = head_top - bh
            sw = self.winfo_screenwidth()
            bx = max(0, min(bx, sw - bw))
            by = max(0, by)
            self.geometry(f"+{bx}+{by}")
        except Exception:
            pass

    def _close(self):
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_close:
            self.on_close()

class TimerDialog(tk.Toplevel):
    """Small dialog to set a custom countdown timer."""

    def __init__(self, master, on_set):
        super().__init__(master)
        self.on_set = on_set
        self.title("Set a Timer 🐾")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set()

        # center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        pad = 20
        tk.Label(self, text="Set a reminder timer", font=("Segoe UI", 11, "bold"),
                 pady=10).pack()
        tk.Label(self, text="The cat will remind you when time is up! 😺",
                 font=("Segoe UI", 9), fg="#555").pack()

        tk.Frame(self, height=8).pack()

        # Quick presets
        preset_frame = tk.Frame(self)
        preset_frame.pack(pady=(0, 8))
        tk.Label(preset_frame, text="Quick:", font=("Segoe UI", 9)).grid(row=0, column=0, padx=(0,6))
        for i, (label, mins) in enumerate([("15 min", 15), ("30 min", 30),
                                            ("1 hr", 60), ("2 hr", 120)]):
            tk.Button(preset_frame, text=label, width=6,
                      font=("Segoe UI", 9),
                      command=lambda m=mins: self._set(m)
                      ).grid(row=0, column=i+1, padx=2)

        # Custom input
        custom_frame = tk.Frame(self)
        custom_frame.pack(pady=4)
        tk.Label(custom_frame, text="Custom:", font=("Segoe UI", 9)).grid(row=0, column=0, padx=(0,6))
        self._var = tk.StringVar(value="25")
        tk.Entry(custom_frame, textvariable=self._var, width=5,
                 font=("Segoe UI", 10), justify="center").grid(row=0, column=1)
        tk.Label(custom_frame, text="minutes", font=("Segoe UI", 9)).grid(row=0, column=2, padx=(4,0))
        tk.Button(custom_frame, text="Set ✓", font=("Segoe UI", 9),
                  command=self._set_custom).grid(row=0, column=3, padx=(8,0))

        tk.Frame(self, height=6).pack()
        tk.Button(self, text="Cancel", font=("Segoe UI", 9), fg="#888",
                  command=self.destroy).pack(pady=(0, 10))

        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _set(self, minutes):
        self.destroy()
        self.on_set(minutes)

    def _set_custom(self):
        try:
            mins = int(self._var.get())
            if mins < 1:
                raise ValueError
        except ValueError:
            self._var.set("?")
            return
        self._set(mins)

class DesktopCat:
    def __init__(self, root: tk.Tk, frames: dict):
        self.root   = root
        self.frames = frames

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", TRANS)
        root.config(bg=TRANS)

        self.canvas = tk.Canvas(root, width=CAT_PX, height=CAT_PX,
                                bg=TRANS, highlightthickness=0)
        self.canvas.pack()
        self._img = self.canvas.create_image(0, 0, anchor="nw")

        self.SW = root.winfo_screenwidth()
        self.SH = root.winfo_screenheight()

        self._my_hwnd = None
        if _WIN32:
            try:
                self._my_hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
            except Exception:
                pass

        # position
        self.x    = float(self.SW // 2)
        self.y    = float(self.SH - CAT_PX + FOOT_OFFSET - 48)
        self.vy   = 0.0
        self.grounded = True

        # animation state
        self.state       = "idle"
        self.anim_name   = "idle_sit"
        self.frame_idx   = 0
        self.cycles_left = random.randint(*STATE_DUR["idle"])

        # walk
        self.vel_x           = 0.0
        self.target_x        = self.x
        self._sit_y          = self.y
        self._walking_to_sit = False

        # pet
        self.petting    = False
        self.pet_cycles = 0

        # drag
        self._dragging = False
        self._drag_ox  = 0.0
        self._drag_oy  = 0.0
        self._press_t  = 0.0

        self._bubble      = None   # active SpeechBubble or None
        self._talking     = False  # True while bubble is visible → play idle anim

        self._last_charging          = None
        self._battery_check_interval = 3000

        self._timers = []
        self._timer_check_interval = 5000   # ms

        self.canvas.bind("<ButtonPress-1>",  self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>",        self._on_rclick)

        self._ms = max(1, 1000 // FPS)
        self._schedule()
        self._schedule_battery_check()
        self._schedule_timer_check()

    def _show_bubble(self, text: str, duration_ms: int = 8000,
                     color: str = "#FFFDE7"):
        """Show a speech bubble AND switch cat to idle/talking animation."""
        # Dismiss any existing bubble
        if self._bubble is not None:
            try:
                self._bubble.destroy()
            except Exception:
                pass
            self._bubble = None

        # Enter talking state: freeze walking, play idle anim
        self._talking   = True
        self.vel_x      = 0.0
        self.state      = "talking"
        self.anim_name  = random.choice(STATE_OPTS["talking"])
        self.frame_idx  = 0

        self._bubble = SpeechBubble(
            self.root, text,
            int(self.x), int(self.y),
            duration_ms=duration_ms,
            color=color,
            on_close=self._on_bubble_close)

    def _on_bubble_close(self):
        """Called when the bubble timer expires — resume normal AI."""
        self._talking = False
        self._bubble  = None
        self._enter("idle")

    def _schedule_battery_check(self):
        self.root.after(self._battery_check_interval, self._check_battery)

    def _check_battery(self):
        percent, is_charging = get_battery_status()
        if is_charging is not None:
            if self._last_charging is False and is_charging is True:
                pct_str = f" ({percent}%)" if percent is not None else ""
                msgs = [
                    f"Ooh, charging time{pct_str}!",
                    f"Power incoming{pct_str}!",
                    f"Charging{pct_str}~",
                ]
                self._show_bubble(random.choice(msgs), duration_ms=9000, color="#FFF9C4")
            elif self._last_charging is True and is_charging is False:
                pct_str = f" ({percent}% left)" if percent is not None else ""
                msgs = [
                    f"Unplugged{pct_str}!",
                    f"Charger gone{pct_str}… better save your work!",
                ]
                self._show_bubble(random.choice(msgs), duration_ms=7000, color="#FFE0B2")
            self._last_charging = is_charging
        self._schedule_battery_check()

    def _schedule_timer_check(self):
        self.root.after(self._timer_check_interval, self._check_timers)

    def _check_timers(self):
        now     = time.time()
        expired = [t for t in self._timers if now >= t["end"]]
        for t in expired:
            self._timers.remove(t)
            self._show_bubble(t["msg"], duration_ms=12000, color="#F3E5F5")
        self._schedule_timer_check()

    def _add_timer(self, minutes: int):
        """Schedule a reminder after `minutes` minutes."""
        end = time.time() + minutes * 60
        if minutes < 60:
            label = f"{minutes} min"
        else:
            h, m = divmod(minutes, 60)
            label = f"{h}h" + (f" {m}m" if m else "")

        msgs = [
            f"Meow! Your {label} timer is done!",
            f"{label} is up!",
            f"Hey! {label} has passed.",
        ]
        self._timers.append({"end": end, "msg": random.choice(msgs)})
        # Confirm to user
        self._show_bubble(f"Timer set for {label}! I'll remind you.",
                          duration_ms=5000, color="#E3F2FD")

    def _open_timer_dialog(self):
        TimerDialog(self.root, on_set=self._add_timer)

    def _schedule(self):
        self.root.after(self._ms, self._tick)

    def _tick(self):
        if self._dragging:
            self.anim_name = "hind_legs"
            self._draw()
            self._schedule()
            return
        self._physics()
        if self.grounded:
            # If talking, just loop the idle anim — don't run AI or walk
            if not self._talking:
                self._ai()
                self._walk()
        self._draw()
        self._schedule()

    def _physics(self):
        floor_y = get_floor_y(self.x, self.y, self._my_hwnd, self.SH)
        if self.y < floor_y - 1:
            self.vy       = min(self.vy + GRAVITY, MAX_FALL)
            self.y       += self.vy
            self.grounded = False
            self.anim_name = "hind_legs"
        else:
            self.y        = floor_y
            self.vy       = 0.0
            self.grounded = True
            if self.state not in ("walk_right", "walk_left",
                                  "idle", "sit", "pet", "talking"):
                self._enter("idle")
        self.x = max(0.0, min(float(self.SW - CAT_PX), self.x))
        self.root.geometry(f"{CAT_PX}x{CAT_PX}+{int(self.x)}+{int(self.y)}")

    def _ai(self):
        if self.petting:
            self.pet_cycles -= 1
            if self.pet_cycles <= 0:
                self.petting = False
                self._enter("idle")
            return
        n = len(self.frames[self.anim_name])
        if self.frame_idx % n == n - 1:
            self.cycles_left -= 1
            if self.cycles_left <= 0:
                self._next_state()

    def _next_state(self):
        if self.state in ("walk_right", "walk_left"):
            if abs(self.x - self.target_x) < WALK_SPEED + 4:
                self.x     = self.target_x
                self.vel_x = 0.0
                if self._walking_to_sit:
                    self.y = self._sit_y
                    self._walking_to_sit = False
                self._enter(random.choice(["idle", "idle", "sit"]))
            return
        roll = random.random()
        if roll < 0.30:
            self._go_sit()
        elif roll < 0.60:
            self._start_walk()
        else:
            self._enter("idle")

    def _enter(self, state: str):
        self.state       = state
        self.anim_name   = random.choice(STATE_OPTS[state])
        self.frame_idx   = 0
        lo, hi           = STATE_DUR.get(state, (3, 8))
        self.cycles_left = random.randint(lo, hi)

    def _start_walk(self):
        margin = CAT_PX + 20
        self.target_x        = float(random.randint(margin, self.SW - margin))
        self._sit_y          = self.y
        self._walking_to_sit = True
        self._begin_walk()

    def _go_sit(self):
        spot = get_random_sit_spot(self._my_hwnd, self.SW, self.SH)
        if not spot:
            self._start_walk()
            return
        tx, ty = spot
        tx = max(0, min(self.SW - CAT_PX, tx))
        ty = max(0, min(self.SH - CAT_PX, ty))
        self.target_x        = float(tx)
        self._sit_y          = float(ty)
        self._walking_to_sit = True
        self._begin_walk()

    def _begin_walk(self):
        dx = self.target_x - self.x
        if abs(dx) < WALK_SPEED + 4:
            self.vel_x = 0.0
            self._enter("idle")
            return
        if dx > 0:
            self.vel_x = WALK_SPEED
            self._enter("walk_right")
        else:
            self.vel_x = -WALK_SPEED
            self._enter("walk_left")

    def _walk(self):
        if self.state not in ("walk_right", "walk_left"):
            return
        self.x += self.vel_x
        self.x  = max(0.0, min(float(self.SW - CAT_PX), self.x))
        if abs(self.x - self.target_x) < WALK_SPEED + 4:
            self.x     = self.target_x
            self.vel_x = 0.0
            if self._walking_to_sit:
                self.y = self._sit_y
                self._walking_to_sit = False
            self._enter(random.choice(["idle", "sit"]))

    def _draw(self):
        imgs = self.frames[self.anim_name]
        self.canvas.itemconfig(self._img, image=imgs[self.frame_idx % len(imgs)])
        self.frame_idx += 1

    def _on_press(self, e):
        self._drag_ox  = e.x_root - self.x
        self._drag_oy  = e.y_root - self.y
        self._dragging = False
        self._press_t  = time.time()
        # Wake the cat if it's sleeping or lying
        if self.anim_name in ("sleep", "lie") and not self._talking:
            self._enter("idle")

    def _on_drag(self, e):
        self._dragging = True
        self.vel_x     = 0.0
        self.vy        = 0.0
        self.x = float(e.x_root - self._drag_ox)
        self.y = float(e.y_root - self._drag_oy)
        self.root.geometry(f"{CAT_PX}x{CAT_PX}+{int(self.x)}+{int(self.y)}")
        # Keep bubble attached to cat while dragging
        if self._bubble is not None:
            try:
                self._bubble.move_to(int(self.x), int(self.y))
            except Exception:
                pass

    def _on_release(self, e):
        was_dragging   = self._dragging
        self._dragging = False
        self.grounded  = False
        self.vy        = 0.0
        if not was_dragging and time.time() - self._press_t < 0.4:
            self._pet()
        else:
            self._enter("idle")

    def _pet(self):
        self.petting    = True
        self.state      = "pet"
        self.anim_name  = random.choice(STATE_OPTS["pet"])
        self.frame_idx  = 0
        self.pet_cycles = FPS * 3
        self.vel_x      = 0.0

    def _on_rclick(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="🐾  Pet the cat",   command=self._pet_yawn)
        m.add_command(label="⏱  Set a Timer",    command=self._open_timer_dialog)

        # Show active timers (read-only info)
        if self._timers:
            m.add_separator()
            now = time.time()
            for t in self._timers:
                remaining = int(t["end"] - now)
                if remaining > 0:
                    h, rem = divmod(remaining, 3600)
                    mins, secs = divmod(rem, 60)
                    if h:
                        countdown = f"{h}h {mins}m left"
                    else:
                        countdown = f"{mins}m {secs}s left"
                    m.add_command(label=f"  🕐 {countdown}", state="disabled")

        m.add_separator()
        top = self.root.attributes("-topmost")
        m.add_command(label=("✓ " if top else "    ") + "Always on Top",
                      command=lambda: self.root.attributes("-topmost", not top))
        m.add_separator()
        m.add_command(label="Quit", command=self.root.quit)
        m.tk_popup(e.x_root, e.y_root)

    def _pet_yawn(self):
        self.petting    = True
        self.state      = "pet"
        self.anim_name  = "yawn"
        self.frame_idx  = 0
        self.pet_cycles = FPS * 2
        self.vel_x      = 0.0


def main():
    if not os.path.exists(SPRITE_PATH):
        print("=" * 60)
        print("ERROR: cat_sprite.png not found!")
        print(f"Expected: {SPRITE_PATH}")
        print("=" * 60)
        sys.exit(1)

    root = tk.Tk()
    root.title("Desktop Cat")
    root.resizable(False, False)

    print("Loading sprites…")
    frames = load_frames(SPRITE_PATH)
    print(f"Loaded {sum(len(v) for v in frames.values())} frames.")
    print("Left-click tap = pet  |  Click+drag = pick up  |  Right-click = menu")

    DesktopCat(root, frames)
    root.mainloop()

if __name__ == "__main__":
    main()