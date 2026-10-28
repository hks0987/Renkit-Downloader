"""Small windows: download-complete box, choice box, 'paste a link' box, Properties, and the Options (settings) window."""
import copy
from theme import F, ACCENTS
from ui import FlatButton, Switch
from common import (get_setting, DUP_LABELS, CATEGORIES, norm_path, SETTINGS, DEFAULT_SETTINGS, save_settings, reset_opener,
                    CACHE_DIR, DEFAULT_FILE_TYPES, DEFAULT_EXCLUDE_SITES, DARK_THEME, apply_dark_theme, center_window,
                    tk, ttk, filedialog, messagebox)
import copy
from pathlib import Path, PureWindowsPath
from common import (CACHE_DIR, CATEGORIES, DARK_THEME, DEFAULT_EXCLUDE_SITES, DEFAULT_FILE_TYPES, DEFAULT_SETTINGS, DUP_LABELS, RepairError, SETTINGS, _Toplevel, apply_dark_theme, center_window, check_url, clipboard_url, expiry_text, filedialog, format_bytes, get_setting, messagebox, norm_path, open_path, reset_opener, safe_grab, save_settings, tk, ttk)


class DownloadCompleteDialog(_Toplevel):
    def __init__(self, parent, file_path, already=False):
        super().__init__(parent)
        self.title("Already Downloaded - Renkit" if already else "Download Complete - Renkit")
        self.transient(parent)
        apply_dark_theme(self)
        self.file_path = Path(file_path)
        headline = "This file is already downloaded." if already else "Download completed successfully!"
        ttk.Label(self, text=f"{headline}\n\n{self.file_path.name}\n{self.file_path.parent}",
                  font=("Segoe UI", 9, "bold"), wraplength=520, justify="left").pack(padx=16, pady=16, anchor="w")
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=4)
        ttk.Button(bar, text="Open File", command=self.on_open_file).pack(side="left", padx=2)
        ttk.Button(bar, text="Open Folder", command=self.on_open_folder).pack(side="left", padx=8)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right", padx=2)
        center_window(self, 580, 190)
        safe_grab(self)

    def on_open_file(self):
        open_path(self.file_path)
        self.destroy()

    def on_open_folder(self):
        open_path(self.file_path.parent)
        self.destroy()


def ask_choice(parent, title, message, buttons):
    """Modal dialog with one button per choice. Returns the clicked button's index (None if closed)."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.transient(parent)
    apply_dark_theme(dlg)
    ttk.Label(dlg, text=message, wraplength=460, justify="left").pack(padx=16, pady=(16, 8), anchor="w")
    result = [None]

    def pick(i):
        result[0] = i
        dlg.destroy()

    bar = ttk.Frame(dlg)
    bar.pack(padx=16, pady=(4, 14))
    for i, text in enumerate(buttons):
        ttk.Button(bar, text=text, command=lambda i=i: pick(i)).pack(side="left", padx=4)
    dlg.update_idletasks()
    center_window(dlg, max(dlg.winfo_reqwidth(), 360), dlg.winfo_reqheight())
    safe_grab(dlg)
    parent.wait_window(dlg)
    return result[0]


def prompt_link(parent, title, message, initial=""):
    """Ask for a link. Pre-fills from the clipboard when it holds a valid link; has a Paste button."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.transient(parent)
    apply_dark_theme(dlg)
    var = tk.StringVar(value=initial or clipboard_url(parent))
    ttk.Label(dlg, text=message, wraplength=520, justify="left").pack(padx=14, pady=(14, 6), anchor="w")
    row = ttk.Frame(dlg)
    row.pack(fill="x", padx=14)
    entry = ttk.Entry(row, textvariable=var, width=62)
    entry.pack(side="left", fill="x", expand=True)

    def paste():
        try:
            var.set(parent.clipboard_get().strip().split()[0])
        except Exception:
            pass

    ttk.Button(row, text="Paste", command=paste).pack(side="left", padx=(6, 0))
    result = [None]

    def ok():
        value = var.get().strip().strip("\"'")
        try:
            check_url(value)
        except RepairError as e:
            messagebox.showerror("Invalid link", str(e), parent=dlg)
            return
        result[0] = value
        dlg.destroy()

    bar = ttk.Frame(dlg)
    bar.pack(pady=12)
    ttk.Button(bar, text="OK", command=ok).pack(side="left", padx=4)
    ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="left", padx=4)
    entry.focus()
    entry.bind("<Return>", lambda _e: ok())
    dlg.update_idletasks()
    center_window(dlg, max(dlg.winfo_reqwidth(), 560), dlg.winfo_reqheight())
    safe_grab(dlg)
    parent.wait_window(dlg)
    return result[0]


class PropertiesWindow(_Toplevel):
    def __init__(self, parent, t):
        super().__init__(parent)
        self.title(f"Details - {t['filename']}")
        self.transient(parent)
        apply_dark_theme(self)
        center_window(self, 640, 400)
        self.url = t["url"]
        exp = expiry_text(t["url"])
        rows = [
            ("File name", t["filename"]), ("Saved to", t["dest"]),
            ("Size", format_bytes(t["size"]) if t["size"] else "Unknown"), ("Status", t["status"]),
            ("Link", exp or "no expiry detected"), ("Referer", (t.get("hdrs") or {}).get("referer", "-")),
            ("ETag", t.get("etag") or "-"), ("Last try", t.get("last_try") or "-"),
            ("Type", "Rescued from IDM pieces" if t.get("plan") else "Normal download"),
        ]
        grid = ttk.Frame(self, padding=12)
        grid.pack(fill="x")
        for i, (label, value) in enumerate(rows):
            ttk.Label(grid, text=label + ":", font=("Segoe UI", 9, "bold")).grid(row=i, column=0, sticky="nw", pady=2)
            ttk.Label(grid, text=value, wraplength=470, justify="left").grid(row=i, column=1, sticky="w", padx=12, pady=2)
        urow = ttk.Frame(self, padding=(12, 0))
        urow.pack(fill="x")
        entry = ttk.Entry(urow)
        entry.insert(0, t["url"])
        entry.configure(state="readonly")
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(urow, text="Copy link", command=self.copy_link).pack(side="left", padx=(6, 0))
        ttk.Button(self, text="Close", command=self.destroy).pack(pady=12)

    def copy_link(self):
        self.clipboard_clear()
        self.clipboard_append(self.url)


class SettingsWindow(_Toplevel):
    PAGES = ("General", "Folders", "Browser", "Network", "Appearance")

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Renkit settings")
        self.transient(parent)
        apply_dark_theme(self)
        center_window(self, 820, 620)
        self.minsize(740, 560)
        self.app, self.vars = parent, {}
        t = DARK_THEME
        nav = tk.Frame(self, bg=t["surface"], width=190)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Label(nav, text="Settings", bg=t["surface"], fg=t["text"], font=F(14, True)).pack(anchor="w", padx=22, pady=(24, 14))
        right = tk.Frame(self, bg=t["bg"])
        right.pack(side="left", fill="both", expand=True)
        footer = tk.Frame(right, bg=t["bg"], padx=28, pady=14)
        footer.pack(side="bottom", fill="x")
        FlatButton(footer, "Save", self.on_ok, kind="primary", padx=22).pack(side="right")
        FlatButton(footer, "Cancel", self.destroy, kind="soft").pack(side="right", padx=8)
        FlatButton(footer, "Reset to defaults", self.on_reset, kind="ghost").pack(side="left")
        self.stage = tk.Frame(right, bg=t["bg"], padx=30, pady=22)
        self.stage.pack(side="top", fill="both", expand=True)
        self.pages, self.nav_items = {}, {}
        for name in self.PAGES:
            lbl = tk.Label(nav, text=name, anchor="w", bg=t["surface"], fg=t["muted"], font=F(10), padx=16, pady=8, cursor="hand2")
            lbl.pack(fill="x", padx=10)
            lbl.bind("<Button-1>", lambda e, n=name: self.show(n))
            self.nav_items[name] = lbl
            page = tk.Frame(self.stage, bg=t["bg"])
            getattr(self, "_page_" + name.lower())(page)
            self.pages[name] = page
        self.show("General")

    def show(self, name):
        t = DARK_THEME
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        for n, lbl in self.nav_items.items():
            on = n == name
            lbl.configure(bg=t["surface2"] if on else t["surface"], fg=t["text"] if on else t["muted"], font=F(10, on))

    # ---- helpers
    def _var(self, key, kind):
        var = {"bool": tk.BooleanVar, "int": tk.IntVar, "str": tk.StringVar}[kind](value=get_setting(key))
        self.vars[key] = var
        return var

    def _heading(self, parent, text, hint=""):
        ttk.Label(parent, text=text, style="Heading.TLabel").pack(anchor="w")
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel", wraplength=540, justify="left").pack(anchor="w", pady=(2, 12))

    def _switch(self, parent, key, title, hint=""):
        t = DARK_THEME
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(fill="x", pady=7)
        text = tk.Frame(row, bg=t["bg"])
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=t["bg"], fg=t["text"], font=F(10), anchor="w").pack(anchor="w")
        if hint:
            tk.Label(text, text=hint, bg=t["bg"], fg=t["muted"], font=F(9), anchor="w", wraplength=470, justify="left").pack(anchor="w")
        Switch(row, self._var(key, "bool")).pack(side="right")

    def _label(self, parent, text, top=12):
        ttk.Label(parent, text=text).pack(anchor="w", pady=(top, 3))

    def _browse(self, var):
        folder = filedialog.askdirectory(parent=self, initialdir=var.get() or None)
        if folder:
            var.set(norm_path(folder))

    # ---- pages
    def _page_general(self, p):
        self._heading(p, "General", "How Renkit behaves when you add and finish downloads.")
        self._switch(p, "show_start_dialog", "Ask where to save each download", "Shows a small window before a download starts.")
        self._switch(p, "only_add_to_queue", "Add new links to the waiting list only", "Nothing starts until you run the waiting list.")
        self._switch(p, "show_complete_dialog", "Tell me when a download finishes")
        self._switch(p, "copy_link_to_clipboard", "Copy grabbed links to the clipboard", "A backup in case something goes wrong.")
        self._switch(p, "ignore_modification", "Resume even if the server's file changed", "Turn on only if a site keeps changing its file version.")
        self._switch(p, "verify_after_download", "Check ZIP files after downloading", "Names any damaged file inside the archive.")
        self._label(p, "When you add a link for a file you already have", 14)
        self.dup_var = tk.StringVar(value=DUP_LABELS.get(get_setting("duplicate_policy"), DUP_LABELS["ask"]))
        ttk.Combobox(p, textvariable=self.dup_var, values=list(DUP_LABELS.values()), state="readonly", width=66).pack(anchor="w")
        self._label(p, "Double-click on a download")
        self.dbl_labels = {"details": "Show download details", "open": "Open the file", "folder": "Open the folder"}
        self.dbl_var = tk.StringVar(value=self.dbl_labels.get(get_setting("double_click"), "Show download details"))
        ttk.Combobox(p, textvariable=self.dbl_var, values=list(self.dbl_labels.values()), state="readonly", width=30).pack(anchor="w")

    def _page_folders(self, p):
        self._heading(p, "Folders", "Where each kind of file is saved.")
        self.cat_vars = {}
        dirs = get_setting("category_dirs")
        for cat in CATEGORIES:
            row = tk.Frame(p, bg=DARK_THEME["bg"])
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=cat, width=12).pack(side="left")
            var = tk.StringVar(value=norm_path(dirs.get(cat, "")))
            self.cat_vars[cat] = var
            ttk.Entry(row, textvariable=var, width=52).pack(side="left", padx=6)
            ttk.Button(row, text="Browse", command=lambda v=var: self._browse(v)).pack(side="left")
        self._switch(p, "remember_last_dir", "Remember the folder I pick for each kind", "Uses it the next time that kind of file is downloaded.")
        self._label(p, "Work folder for unfinished parts", 10)
        var = self._var("temp_dir", "str")
        if norm_path(var.get()) == norm_path(CACHE_DIR):
            var.set("")
        row = tk.Frame(p, bg=DARK_THEME["bg"])
        row.pack(fill="x")
        ttk.Entry(row, textvariable=var, width=60).pack(side="left")
        ttk.Button(row, text="Browse", command=lambda: self._browse(var)).pack(side="left", padx=6)
        ttk.Label(p, text="Leave empty to keep unfinished parts in a hidden .renkit folder next to the file (recommended).",
                  style="Muted.TLabel", wraplength=540, justify="left").pack(anchor="w", pady=4)

    def _text_box(self, parent, value, height):
        t = DARK_THEME
        box = tk.Text(parent, height=height, width=70, wrap="word", bg=t["surface"], fg=t["text"], insertbackground=t["text"],
                      relief="flat", padx=8, pady=6, highlightthickness=1, highlightbackground=t["border"], highlightcolor=t["accent"])
        box.insert("1.0", value)
        box.pack(anchor="w", pady=4)
        return box

    def _page_browser(self, p):
        self._heading(p, "Browser", "Which downloads the browser extension hands over to Renkit.")
        self._label(p, "File types to catch (R0* style wildcards allowed)", 0)
        self.types_text = self._text_box(p, get_setting("file_types"), 6)
        ttk.Button(p, text="Default list", command=lambda: (self.types_text.delete("1.0", "end"), self.types_text.insert("1.0", DEFAULT_FILE_TYPES))).pack(anchor="e")
        self._switch(p, "catch_all", "Catch every download, whatever its type")
        self._label(p, "Never catch downloads from these sites (separate with spaces)")
        self.sites_text = self._text_box(p, get_setting("exclude_sites"), 4)
        ttk.Button(p, text="Default list", command=lambda: (self.sites_text.delete("1.0", "end"), self.sites_text.insert("1.0", DEFAULT_EXCLUDE_SITES))).pack(anchor="e")

    def _page_network(self, p):
        self._heading(p, "Network", "Speed, connections and proxy.")
        self._label(p, "Connections per download (1-16)", 0)
        ttk.Spinbox(p, from_=1, to=16, textvariable=self._var("connections", "int"), width=6).pack(anchor="w")
        self._label(p, "Default speed limit in KB/s (0 = unlimited)")
        ttk.Entry(p, textvariable=self._var("speed_limit_kb", "int"), width=10).pack(anchor="w")
        self._label(p, "Downloads running at once from the waiting list")
        ttk.Spinbox(p, from_=1, to=8, textvariable=self._var("max_parallel", "int"), width=6).pack(anchor="w")
        self._label(p, "Proxy", 16)
        mode = self._var("proxy_mode", "str")
        for value, text in (("system", "Use the system proxy settings"), ("none", "No proxy (direct connection)"), ("manual", "Use this proxy:")):
            ttk.Radiobutton(p, text=text, value=value, variable=mode).pack(anchor="w")
        ttk.Entry(p, textvariable=self._var("proxy_url", "str"), width=48).pack(anchor="w", padx=22, pady=(3, 0))
        ttk.Label(p, text="Example: 127.0.0.1:8080  or  user:password@host:3128", style="Muted.TLabel").pack(anchor="w", padx=22)
        self._label(p, "Browser identity (User-Agent) for links you add by hand", 16)
        ttk.Entry(p, textvariable=self._var("user_agent", "str"), width=76).pack(anchor="w")

    def _page_appearance(self, p):
        self._heading(p, "Appearance", "Make Renkit yours. Changes apply when you press Save.")
        self._label(p, "Theme", 4)
        mode = self._var("theme", "str")
        row = tk.Frame(p, bg=DARK_THEME["bg"])
        row.pack(anchor="w")
        for value, text in (("dark", "Dark"), ("light", "Light"), ("auto", "Match my system")):
            ttk.Radiobutton(row, text=text, value=value, variable=mode).pack(side="left", padx=(0, 20))
        self._label(p, "Accent colour", 22)
        acc = self._var("accent", "str")
        row2 = tk.Frame(p, bg=DARK_THEME["bg"])
        row2.pack(anchor="w")
        for value in ACCENTS:
            tk.Label(row2, text="  ", bg=ACCENTS[value][0]).pack(side="left", padx=(0, 6))
            ttk.Radiobutton(row2, text=value.title(), value=value, variable=acc).pack(side="left", padx=(0, 20))

    # ---- save / reset
    def on_reset(self):
        if not messagebox.askyesno("Reset", "Reset all settings to their defaults?", parent=self):
            return
        SETTINGS.clear()
        SETTINGS.update(copy.deepcopy(DEFAULT_SETTINGS))
        save_settings()
        reset_opener()
        self.app.apply_settings()
        self.destroy()
        self.app.apply_appearance()

    def on_ok(self):
        new = {}
        for key, var in self.vars.items():
            try:
                new[key] = var.get()
            except tk.TclError:
                messagebox.showerror("Invalid value", f"Please enter a valid number for '{key}'.", parent=self)
                return
        new["duplicate_policy"] = {v: k for k, v in DUP_LABELS.items()}.get(self.dup_var.get(), "ask")
        new["double_click"] = {v: k for k, v in self.dbl_labels.items()}.get(self.dbl_var.get(), "details")
        new["category_dirs"] = {c: norm_path(v.get()) for c, v in self.cat_vars.items() if v.get().strip()}
        new["file_types"] = " ".join(self.types_text.get("1.0", "end").split())
        new["exclude_sites"] = " ".join(self.sites_text.get("1.0", "end").split())
        new["connections"] = max(1, min(16, int(new["connections"])))
        new["max_parallel"] = max(1, min(8, int(new["max_parallel"])))
        new["speed_limit_kb"] = max(0, int(new["speed_limit_kb"]))
        new["temp_dir"] = norm_path(new["temp_dir"]) if str(new["temp_dir"]).strip() else ""
        before = (get_setting("theme"), get_setting("accent"))
        SETTINGS.update(new)
        save_settings()
        reset_opener()
        self.app.apply_settings()
        self.destroy()
        if before != (new["theme"], new["accent"]):
            self.app.apply_appearance()
