"""The per-download progress window and the 'start download' dialog."""
from theme import F
from ui import FlatProgress
from common import get_setting, format_bytes, expiry_text, open_path, apply_dark_theme, center_window, DARK_THEME
from pathlib import Path, PureWindowsPath
from common import (CATEGORIES, SETTINGS, _Toplevel, apply_dark_theme, category_dir, category_for, center_window, expiry_text, filedialog, format_bytes, get_setting, messagebox, norm_path, safe_grab, safe_int, save_settings, tk, ttk)


class ConnTable:
    """Small stand-in for the per-connection list: .set(row, column, text)."""
    def __init__(self, rows):
        self.rows = rows

    def set(self, iid, column, value):
        self.rows[int(iid)][column].configure(text=value)


class ActiveDownloadWindow(_Toplevel):
    def __init__(self, parent, task_info, app_ref=None, task_id=None):
        super().__init__(parent)
        self.task_info, self.app_ref, self.task_id, self.is_paused = task_info, app_ref, task_id, False
        self.title(f"0% {task_info['filename']}")
        self.transient(parent)
        apply_dark_theme(self)
        center_window(self, 640, 720)
        self.minsize(600, 660)
        t = DARK_THEME
        body = tk.Frame(self, bg=t["bg"], padx=28, pady=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=task_info["filename"], style="Heading.TLabel", wraplength=570, justify="left").pack(anchor="w")
        self.lbl_refs = {}
        status = tk.Label(body, text=str(task_info.get("status", "")), bg=t["surface2"], fg=t["accent"], font=F(9, True), padx=10, pady=3)
        status.pack(anchor="w", pady=(10, 0))
        self.lbl_refs["Status:"] = status
        self.pct_label = tk.Label(body, text="0%", bg=t["bg"], fg=t["text"], font=F(38, True))
        self.pct_label.pack(anchor="w", pady=(6, 0))
        self.prog_bar = FlatProgress(body, height=12, bg=t["bg"], track=t["surface2"], label=self.pct_label)
        self.prog_bar.pack(fill="x", pady=(2, 16))
        grid = tk.Frame(body, bg=t["bg"])
        grid.pack(fill="x")
        size = task_info.get("size") or 0
        tiles = (("Received:", "RECEIVED", "0 B"), ("Total size:", "TOTAL SIZE", format_bytes(size) if size else "Unknown"),
                 ("Speed:", "SPEED", "-"), ("Remaining:", "REMAINING", task_info.get("remaining_text") or "-"),
                 ("Can resume:", "CAN RESUME", "Checking..."), ("Link:", "LINK", expiry_text(task_info["url"]) or "no expiry"))
        for i, (key, title, value) in enumerate(tiles):
            card = tk.Frame(grid, bg=t["surface"], padx=14, pady=10)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else 8, 0), pady=(0, 8))
            grid.columnconfigure(i % 3, weight=1, uniform="tile")
            tk.Label(card, text=title, bg=t["surface"], fg=t["muted"], font=F(8, True)).pack(anchor="w")
            lbl = tk.Label(card, text=value, bg=t["surface"], fg=t["text"], font=F(11, True), anchor="w", wraplength=150, justify="left")
            lbl.pack(anchor="w", pady=(2, 0))
            self.lbl_refs[key] = lbl
        tk.Label(body, text="CONNECTIONS", bg=t["bg"], fg=t["muted"], font=F(8, True)).pack(anchor="w", pady=(12, 4))
        conn = tk.Frame(body, bg=t["surface"], padx=12, pady=8)
        conn.pack(fill="x")
        rows = []
        for i in range(max(1, int(get_setting("connections")))):
            r = tk.Frame(conn, bg=t["surface"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=f"#{i + 1}", bg=t["surface"], fg=t["muted"], font=F(9, True), width=3, anchor="w").pack(side="left")
            got = tk.Label(r, text="-", bg=t["surface"], fg=t["text"], font=F(9), width=11, anchor="w")
            got.pack(side="left")
            info = tk.Label(r, text="", bg=t["surface"], fg=t["muted"], font=F(9), anchor="w")
            info.pack(side="left", fill="x", expand=True)
            rows.append({"downloaded": got, "info": info})
        self.tree = ConnTable(rows)
        linkrow = tk.Frame(body, bg=t["bg"])
        linkrow.pack(fill="x", pady=(16, 0))
        self.url_entry = ttk.Entry(linkrow)
        self.url_entry.insert(0, task_info["url"])
        self.url_entry.configure(state="readonly")
        self.url_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(linkrow, text="Copy link", command=self.copy_link).pack(side="left", padx=(8, 0))
        limrow = tk.Frame(body, bg=t["bg"])
        limrow.pack(fill="x", pady=(10, 0))
        ttk.Label(limrow, text="Speed limit (KB/s, 0 = none)").pack(side="left")
        self.limit_entry = ttk.Entry(limrow, width=8)
        self.limit_entry.insert(0, str(int(task_info.get("speed_limit", 0) // 1024)))
        self.limit_entry.pack(side="left", padx=8)
        ttk.Button(limrow, text="Apply", command=self.on_apply_speed).pack(side="left")
        btns = tk.Frame(body, bg=t["bg"])
        btns.pack(fill="x", side="bottom", pady=(18, 0))
        self.pause_btn = ttk.Button(btns, text="Pause", style="Accent.TButton", command=self.on_pause_resume)
        self.pause_btn.pack(side="left")
        ttk.Button(btns, text="Open folder", command=lambda: open_path(Path(task_info["dest"]).parent)).pack(side="left", padx=8)
        ttk.Button(btns, text="Stop and close", style="Ghost.TButton", command=self.on_cancel).pack(side="right")
        if str(task_info.get("status", "")).startswith(("Paused", "Queued", "Error")):
            self.is_paused = True
            self.pause_btn.configure(text="Resume")

    def copy_link(self):
        self.clipboard_clear()
        self.clipboard_append(self.task_info["url"])

    def on_apply_speed(self):
        try:
            kb = max(0, int(self.limit_entry.get().strip() or 0))
        except ValueError:
            return
        self.task_info["speed_limit"] = kb * 1024

    def on_pause_resume(self):
        if not self.is_paused:
            self.app_ref.pause_task(self.task_id)
            self.lbl_refs["Status:"].configure(text="Paused")
            self.pause_btn.configure(text="Resume")
            self.is_paused = True
        elif self.app_ref.resume_task(self.task_id, window=self):
            self.lbl_refs["Status:"].configure(text="Resuming...")
            self.pause_btn.configure(text="Pause")
            self.is_paused = False

    def on_cancel(self):
        self.app_ref.pause_task(self.task_id)
        self.destroy()


class IDMDownloadDialog(_Toplevel):
    def __init__(self, parent, payload, info, err, name, hdrs, recent, callback):
        super().__init__(parent)
        self.title("New download - Renkit")
        self.transient(parent)
        apply_dark_theme(self)
        center_window(self, 640, 400)
        self.url, self.hdrs, self.callback = payload["url"], hdrs, callback
        self.filename = name
        self.filesize = info["total"] if info else safe_int(payload.get("size"))
        self.recent = list(recent)

        pad = {"padx": 14, "pady": 4}
        ttk.Label(self, text="Link:", font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad)
        url_entry = ttk.Entry(self)
        url_entry.insert(0, self.url)
        url_entry.configure(state="readonly")
        url_entry.pack(fill="x", **pad)
        size_text = format_bytes(self.filesize) if self.filesize else "size unknown"
        text = f"File: {name}\nSize: {size_text}"
        exp = expiry_text(self.url)
        if exp:
            text += f"\nLink: {exp}"
        if err:
            text += f"\nCould not read the link details: {err}"
        self.lbl_size = ttk.Label(self, text=text, justify="left", wraplength=600)
        self.lbl_size.pack(anchor="w", **pad)

        row = ttk.Frame(self)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Category:", width=10).pack(side="left")
        self.cat_combo = ttk.Combobox(row, values=list(CATEGORIES), state="readonly", width=16)
        self.cat_combo.set(category_for(name))
        self.cat_combo.pack(side="left")
        self.cat_combo.bind("<<ComboboxSelected>>", self._on_category)

        row2 = ttk.Frame(self)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="Save to:", width=10).pack(side="left")
        self.save_combo = ttk.Combobox(row2, values=self.recent)
        self.save_combo.set(norm_path(category_dir(self.cat_combo.get())))
        self.save_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="Browse...", command=self._browse).pack(side="left", padx=(6, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=14, pady=14)
        ttk.Button(bar, text="Start Download", command=self.on_start).pack(side="left")
        ttk.Button(bar, text="Download Later", command=self.on_later).pack(side="left", padx=8)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        safe_grab(self)

    def _on_category(self, _event=None):
        self.save_combo.set(norm_path(category_dir(self.cat_combo.get())))

    def _browse(self):
        folder = filedialog.askdirectory(parent=self, initialdir=self.save_combo.get() or None)
        if folder:
            self.save_combo.set(norm_path(folder))

    def _finish(self, start_immediately):
        cat = self.cat_combo.get()
        dest = Path(norm_path(self.save_combo.get().strip()) or str(category_dir(cat)))
        if get_setting("remember_last_dir"):
            dirs = dict(get_setting("category_dirs"))
            dirs[cat] = str(dest)
            SETTINGS["category_dirs"] = dirs
            save_settings()
        self.destroy()
        self.callback(self.url, dest, cat, "", start_immediately=start_immediately,
                      resolved_filename=self.filename, resolved_size=self.filesize,
                      hdrs=self.hdrs, queued=not start_immediately)

    def on_start(self):
        self._finish(True)

    def on_later(self):
        self._finish(False)
