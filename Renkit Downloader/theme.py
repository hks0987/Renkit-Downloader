"""Renkit look and feel: dark and light palettes, accent colours, fonts and the ttk styling."""
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

ACCENTS = {"teal": ("#2dd4bf", "#0f9d8e"), "indigo": ("#9aa0ff", "#4f56e0"), "coral": ("#ff8f7a", "#e0553d")}
PALETTES = {
    "dark": {"bg": "#13151b", "surface": "#1b1e26", "surface2": "#252a36", "border": "#2e3340",
             "text": "#e9ecf3", "muted": "#8d95a8", "success": "#4ade80", "warn": "#fbbf24",
             "danger": "#f87171", "on_accent": "#06201c"},
    "light": {"bg": "#f2f3f8", "surface": "#ffffff", "surface2": "#eceef4", "border": "#d6d9e4",
              "text": "#1a1d26", "muted": "#667085", "success": "#15803d", "warn": "#b45309",
              "danger": "#dc2626", "on_accent": "#ffffff"},
}
THEME = {}  # the live palette, shared by every window (older code reads it as DARK_THEME)
STATE = {"mode": "dark", "family": None}


def mix(c1, c2, a):
    """Blend colour c1 towards c2 by the fraction a (0..1)."""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (round(r1 + (r2 - r1) * a), round(g1 + (g2 - g1) * a), round(b1 + (b2 - b1) * a))


def system_prefers_light():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 1
    except Exception:
        return False


def set_mode(mode="dark", accent="teal"):
    """Choose 'dark', 'light' or 'auto' (follow the system) and an accent colour. Returns the mode in use."""
    resolved = ("light" if system_prefers_light() else "dark") if mode == "auto" else (mode if mode in PALETTES else "dark")
    pal = dict(PALETTES[resolved])
    dark_acc, light_acc = ACCENTS.get(accent, ACCENTS["teal"])
    pal["accent"] = light_acc if resolved == "light" else dark_acc
    pal["accent_hover"] = mix(pal["accent"], "#ffffff" if resolved == "dark" else "#000000", 0.14)
    pal.update(fg=pal["text"], card_bg=pal["surface"], card_fg=pal["text"], select_bg=pal["accent"],
               select_fg=pal["on_accent"], disabled_bg=pal["surface2"], disabled_fg=pal["muted"], alt_row=pal["surface2"])
    THEME.clear()
    THEME.update(pal)
    STATE["mode"] = resolved
    return resolved


def ui_family(root=None):
    if STATE["family"]:
        return STATE["family"]
    try:
        have = set(tkfont.families(root))
    except Exception:
        have = set()
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans"):
        if name in have:
            STATE["family"] = name
            return name
    STATE["family"] = "Helvetica"
    return "Helvetica"


def F(size=10, bold=False):
    fam = STATE["family"] or "Helvetica"
    return (fam, size, "bold") if bold else (fam, size)


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def apply_theme(win):
    """Style all ttk widgets and the given window. Safe to call for every new window."""
    if not THEME:
        set_mode()
    t = THEME
    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    fam = ui_family(win)
    style.configure(".", background=t["bg"], foreground=t["text"], fieldbackground=t["surface"], bordercolor=t["border"],
                    lightcolor=t["border"], darkcolor=t["border"], troughcolor=t["surface2"], focuscolor=t["bg"],
                    font=(fam, 10))
    style.configure("TFrame", background=t["bg"])
    style.configure("Surface.TFrame", background=t["surface"])
    style.configure("TLabel", background=t["bg"], foreground=t["text"])
    style.configure("Muted.TLabel", foreground=t["muted"])
    style.configure("Heading.TLabel", font=(fam, 14, "bold"))
    style.configure("TButton", background=t["surface2"], foreground=t["text"], borderwidth=0, relief="flat",
                    padding=(14, 7), focusthickness=0)
    style.map("TButton", background=[("active", t["border"]), ("disabled", t["surface"])], foreground=[("disabled", t["muted"])])
    style.configure("Accent.TButton", background=t["accent"], foreground=t["on_accent"], font=(fam, 10, "bold"))
    style.map("Accent.TButton", background=[("active", t["accent_hover"])])
    style.configure("Ghost.TButton", background=t["bg"], foreground=t["muted"])
    style.map("Ghost.TButton", background=[("active", t["surface2"])], foreground=[("active", t["text"])])
    style.configure("TEntry", fieldbackground=t["surface"], foreground=t["text"], insertcolor=t["text"], padding=6, bordercolor=t["border"])
    style.map("TEntry", bordercolor=[("focus", t["accent"])])
    style.configure("TCombobox", fieldbackground=t["surface"], background=t["surface2"], foreground=t["text"],
                    arrowcolor=t["muted"], padding=5, bordercolor=t["border"])
    style.map("TCombobox", fieldbackground=[("readonly", t["surface"])], foreground=[("readonly", t["text"])],
              bordercolor=[("focus", t["accent"])])
    style.configure("TSpinbox", fieldbackground=t["surface"], foreground=t["text"], arrowcolor=t["muted"], padding=5, bordercolor=t["border"])
    for cls in ("TCheckbutton", "TRadiobutton"):
        style.configure(cls, background=t["bg"], foreground=t["text"])
        style.map(cls, background=[("active", t["bg"])], indicatorcolor=[("selected", t["accent"]), ("!selected", t["surface"])])
    style.configure("TSeparator", background=t["border"])
    style.configure("TLabelframe", background=t["bg"], bordercolor=t["border"])
    style.configure("TLabelframe.Label", background=t["bg"], foreground=t["muted"], font=(fam, 9, "bold"))
    style.configure("Vertical.TScrollbar", background=t["surface2"], troughcolor=t["bg"], bordercolor=t["bg"],
                    arrowcolor=t["muted"], gripcount=0, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", t["border"])])
    style.configure("TProgressbar", background=t["accent"], troughcolor=t["surface2"], bordercolor=t["surface2"],
                    lightcolor=t["accent"], darkcolor=t["accent"])
    style.configure("Treeview", background=t["surface"], fieldbackground=t["surface"], foreground=t["text"], rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background=t["surface2"], foreground=t["muted"], relief="flat")
    style.map("Treeview", background=[("selected", t["accent"])], foreground=[("selected", t["on_accent"])])
    for opt, val in (("*TCombobox*Listbox.background", t["surface"]), ("*TCombobox*Listbox.foreground", t["text"]),
                     ("*TCombobox*Listbox.selectBackground", t["accent"]), ("*TCombobox*Listbox.selectForeground", t["on_accent"]),
                     ("*Menu.background", t["surface"]), ("*Menu.foreground", t["text"]), ("*Menu.activeBackground", t["accent"]),
                     ("*Menu.activeForeground", t["on_accent"]), ("*Menu.relief", "flat")):
        win.option_add(opt, val)
    try:
        win.configure(bg=t["bg"])
    except tk.TclError:
        pass
