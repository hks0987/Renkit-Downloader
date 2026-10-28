"""Custom widgets: flat buttons, a switch, a thin progress bar and the card list that shows downloads."""
import re
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from theme import THEME, STATE, F, round_rect, mix


class FlatButton(tk.Label):
    """A flat clickable label. kinds: primary (accent), soft, ghost (quiet)."""
    def __init__(self, master, text, command=None, kind="ghost", bg=None, padx=14, pady=7, pass_event=False, font=None):
        t = THEME
        self.kind, self.command, self.pass_event, self.enabled = kind, command, pass_event, True
        base = bg or t["bg"]
        self._pal = {"primary": (t["accent"], t["on_accent"], t["accent_hover"], t["on_accent"]),
                     "soft": (t["surface2"], t["text"], t["border"], t["text"]),
                     "ghost": (base, t["muted"], t["surface2"], t["text"])}[kind]
        super().__init__(master, text=text, padx=padx, pady=pady, cursor="hand2", bg=self._pal[0], fg=self._pal[1],
                         font=font or F(10, kind == "primary"))
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<Button-1>", self._click)

    def _hover(self, on):
        if self.enabled:
            self.configure(bg=self._pal[2] if on else self._pal[0], fg=self._pal[3] if on else self._pal[1])

    def _click(self, event):
        if self.enabled and self.command:
            self.command(event) if self.pass_event else self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.configure(fg=self._pal[1] if enabled else THEME["muted"], cursor="hand2" if enabled else "arrow")


class Switch(tk.Canvas):
    """An on/off switch bound to a BooleanVar."""
    def __init__(self, master, variable, bg=None):
        super().__init__(master, width=42, height=24, bg=bg or THEME["bg"], highlightthickness=0, cursor="hand2")
        self.var = variable
        self.bind("<Button-1>", lambda e: self.var.set(not self.var.get()))
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        round_rect(self, 1, 2, 41, 22, 10, fill=THEME["accent"] if on else THEME["border"], outline="")
        x = 23 if on else 4
        self.create_oval(x, 5, x + 15, 20, fill="#ffffff", outline="")


class FlatProgress(tk.Canvas):
    """A thin rounded progress bar. Assign bar["value"] = 0..100."""
    def __init__(self, master, height=8, bg=None, track=None, color=None, label=None):
        super().__init__(master, height=height, bg=bg or THEME["bg"], highlightthickness=0, bd=0)
        self.track, self.color, self.label = track or THEME["surface2"], color or THEME["accent"], label
        self._value, self._h = 0.0, height
        self.bind("<Configure>", lambda e: self._draw())

    def __setitem__(self, key, value):
        if key == "value":
            self.set(value)

    def __getitem__(self, key):
        return self._value if key == "value" else super().__getitem__(key)

    def set(self, value, color=None, bg=None):
        self._value = max(0.0, min(100.0, float(value)))
        if color:
            self.color = color
        if bg:
            self.configure(bg=bg)
        if self.label is not None:
            self.label.configure(text=f"{int(self._value)}%")
        self._draw()

    def _draw(self):
        w, h = self.winfo_width(), self._h
        self.delete("all")
        if w < 6:
            return
        round_rect(self, 1, 0, w - 1, h, h / 2, fill=self.track, outline="")
        if self._value > 0:
            round_rect(self, 1, 0, 1 + max(h, (w - 2) * self._value / 100), h, h / 2, fill=self.color, outline="")


KIND_COLORS = {"video": "#7c83ff", "archive": "#f5a524", "audio": "#f472b6", "app": "#2dd4bf", "doc": "#38bdf8", "other": "#94a3b8"}
EXT_KIND = {}
for _kind, _exts in (("video", "mkv mp4 avi mov wmv m4v 3gp webm flv mpg mpeg ogv qt"), ("archive", "zip rar 7z gz tar bz2 z iso img"),
                     ("audio", "mp3 flac wav aac m4a ogg wma"), ("app", "exe msi apk bin msu dmg deb rpm"),
                     ("doc", "pdf doc docx xls xlsx ppt pptx txt epub")):
    for _e in _exts.split():
        EXT_KIND[_e] = _kind
RUNNING = ("Downloading", "Connecting", "Stitching", "Checking")
COLUMNS = ("file_name", "q", "size", "status", "time_left", "transfer_rate", "type", "description", "last_try")


def kind_of(name):
    ext = Path(str(name)).suffix.lower().lstrip(".")
    return EXT_KIND.get(ext, "other"), ext


class Card:
    def __init__(self, owner, iid, values):
        self.owner, self.iid, self.selected, self.hover, self.tags = owner, iid, False, False, ()
        self.values = dict(zip(COLUMNS, list(values) + [""] * (len(COLUMNS) - len(values))))
        self.values["progress"] = 0
        self.derive_progress()
        t = THEME
        self.frame = tk.Frame(owner.inner, bg=t["surface"], highlightthickness=1, highlightbackground=t["border"], highlightcolor=t["border"])
        self.frame.columnconfigure(1, weight=1)
        self.badge = tk.Canvas(self.frame, width=48, height=48, bg=t["surface"], highlightthickness=0)
        self.badge.grid(row=0, column=0, rowspan=3, padx=(14, 14), pady=14)
        self.title = tk.Label(self.frame, anchor="w", bg=t["surface"], fg=t["text"], font=F(11, True))
        self.title.grid(row=0, column=1, sticky="ew", pady=(14, 0))
        self.subrow = tk.Frame(self.frame, bg=t["surface"])
        self.subrow.grid(row=1, column=1, sticky="ew", pady=(2, 0))
        self.chip = tk.Label(self.subrow, anchor="w", bg=t["surface"], font=F(9, True))
        self.chip.pack(side="left")
        self.sub = tk.Label(self.subrow, anchor="w", bg=t["surface"], fg=t["muted"], font=F(9))
        self.sub.pack(side="left", padx=(10, 0))
        self.bar = FlatProgress(self.frame, height=6, bg=t["surface"], track=t["border"])
        self.bar.grid(row=2, column=1, sticky="ew", pady=(8, 14), padx=(0, 16))
        self.actions = tk.Frame(self.frame, bg=t["surface"])
        self.actions.grid(row=0, column=2, rowspan=3, padx=(0, 14))
        self.btn_main = FlatButton(self.actions, "Pause", lambda e: owner._action(iid, "toggle", e), kind="soft", bg=t["surface"], pass_event=True, padx=12, pady=5)
        self.btn_folder = FlatButton(self.actions, "Folder", lambda e: owner._action(iid, "folder", e), kind="ghost", bg=t["surface"], pass_event=True, padx=10, pady=5)
        self.btn_more = FlatButton(self.actions, "\u22ef", lambda e: owner._action(iid, "more", e), kind="ghost", bg=t["surface"], pass_event=True, padx=10, pady=5)
        for b in (self.btn_main, self.btn_folder, self.btn_more):
            b.pack(side="left", padx=2)
        self._paintables = [self.frame, self.subrow, self.chip, self.sub, self.title, self.actions]
        self._bind(self.frame)
        self.refresh()

    def _bind(self, widget):
        widget.bind("<MouseWheel>", self.owner._wheel, add="+")
        widget.bind("<Button-4>", self.owner._wheel, add="+")
        widget.bind("<Button-5>", self.owner._wheel, add="+")
        if not isinstance(widget, FlatButton):
            widget.bind("<Button-1>", lambda e: self.owner._click(self.iid, e), add="+")
            widget.bind("<Double-1>", lambda e: self.owner._double(self.iid), add="+")
            widget.bind("<Button-3>", lambda e: self.owner._context(self.iid, e), add="+")
            widget.bind("<Enter>", lambda e: self._set_hover(True), add="+")
            widget.bind("<Leave>", lambda e: self.frame.after(40, self._check_hover), add="+")
        for child in widget.winfo_children():
            self._bind(child)

    def _check_hover(self):
        try:
            w = self.frame.winfo_containing(*self.frame.winfo_pointerxy())
            while w is not None and w is not self.frame:
                w = w.master
            self._set_hover(w is self.frame)
        except Exception:
            pass

    def _set_hover(self, on):
        if on != self.hover:
            self.hover = on
            self.paint()

    def paint(self):
        t = THEME
        bg = t["surface2"] if (self.selected or self.hover) else t["surface"]
        for w in self._paintables:
            w.configure(bg=bg)
        self.badge.configure(bg=bg)
        for b in (self.btn_main, self.btn_folder, self.btn_more):
            b._pal = (bg,) + b._pal[1:] if b.kind == "ghost" else b._pal
            if b.kind == "ghost":
                b.configure(bg=bg)
        self.frame.configure(highlightbackground=t["accent"] if self.selected else t["border"],
                             highlightcolor=t["accent"] if self.selected else t["border"])
        self.bar.configure(bg=bg)

    def derive_progress(self):
        status = self.values["status"]
        m = re.search(r"(\d+)%", status)
        if status == "Complete":
            self.values["progress"] = 100
        elif m and status.startswith(RUNNING):
            self.values["progress"] = int(m.group(1))

    def refresh(self):
        v, t = self.values, THEME
        name = v["file_name"]
        kind, ext = kind_of(name)
        color = KIND_COLORS[kind]
        self.title.configure(text=name)
        self.badge.delete("all")
        round_rect(self.badge, 1, 1, 47, 47, 12, fill=mix(t["surface"], color, 0.22), outline="")
        txt = color if STATE["mode"] == "dark" else mix(color, "#000000", 0.35)
        self.badge.create_text(24, 24, text=(ext or "file").upper()[:4], fill=txt, font=F(9 if len(ext) > 3 else 10, True))
        status = v["status"]
        running = status.startswith(RUNNING)
        if status == "Complete":
            label, col, btn, bar_col = "Finished", t["success"], "Open", t["success"]
        elif running:
            label, col, btn, bar_col = status, t["accent"], "Pause", t["accent"]
        elif status == "Error":
            label, col, btn, bar_col = "Needs attention", t["danger"], "Retry", t["danger"]
        elif status == "Paused":
            label, col, btn, bar_col = "Paused", t["warn"], "Resume", t["warn"]
        else:
            label, col, btn, bar_col = ("Waiting" if status == "Queued" else status), t["muted"], "Resume", t["muted"]
        if v["q"]:
            label = "\u25cf " + label
        self.chip.configure(text=label, fg=col)
        parts = [p for p in (v["size"], v["transfer_rate"] if running else "", v["time_left"] if status != "Complete" else "", v["description"]) if p]
        self.sub.configure(text="   \u00b7   ".join(parts))
        self.btn_main.configure(text=btn)
        if status == "Complete":
            self.bar.grid_remove()
        else:
            self.bar.grid()
            self.bar.set(v["progress"], color=bar_col)
        self.paint()


class CardList(tk.Frame):
    """Scrolling list of download cards. It offers the small Treeview-style API the app already uses."""
    def __init__(self, master, on_action=None, on_context=None, on_double=None, on_select=None):
        t = THEME
        super().__init__(master, bg=t["bg"])
        self.on_action, self.on_context, self.on_double, self.on_select = on_action, on_context, on_double, on_select
        self.canvas = tk.Canvas(self, bg=t["bg"], highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=t["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for w in (self.canvas, self.inner):
            w.bind("<Button-1>", self._blank_click)
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Button-4>", self._wheel)
            w.bind("<Button-5>", self._wheel)
        self.cards, self.order, self.attached = {}, [], {}
        self._selected, self._anchor, self._dirty, self._flush_job = [], None, set(), None
        self.empty_text = "Nothing here yet.\nClick  + Add link  or press Ctrl+V with a link copied."
        self.empty = tk.Label(self.inner, bg=t["bg"], fg=t["muted"], font=F(11), justify="center")

    # ---- Treeview-style API used by the app
    def insert(self, parent, index, iid=None, values=()):
        self.cards[iid] = Card(self, iid, values)
        self.order.append(iid)
        self.attached[iid] = True
        self._relayout()
        return iid

    def exists(self, iid):
        return iid in self.cards

    def set(self, iid, column, value=None):
        card = self.cards[iid]
        if value is None:
            return card.values.get(column, "")
        card.values[column] = value
        if column == "status":
            card.derive_progress()
        self._dirty.add(iid)
        if self._flush_job is None:
            self._flush_job = self.after(30, self._flush)

    def _flush(self):
        self._flush_job = None
        for iid in list(self._dirty):
            if iid in self.cards:
                try:
                    self.cards[iid].refresh()
                except tk.TclError:
                    pass
        self._dirty.clear()

    def item(self, iid, option=None, **kw):
        card = self.cards[iid]
        if "tags" in kw:
            card.tags = kw["tags"]
        return card.tags if option == "tags" else {"tags": card.tags}

    def index(self, iid):
        return list(self.get_children()).index(iid)

    def delete(self, iid):
        card = self.cards.pop(iid, None)
        if card is not None:
            card.frame.destroy()
        if iid in self.order:
            self.order.remove(iid)
        self.attached.pop(iid, None)
        if iid in self._selected:
            self._selected.remove(iid)
        self._relayout()

    def detach(self, iid):
        if self.attached.get(iid):
            self.attached[iid] = False
            self._relayout()

    def reattach(self, iid, parent="", index="end"):
        if iid in self.attached and not self.attached[iid]:
            self.attached[iid] = True
            self._relayout()

    def get_children(self, parent=""):
        return tuple(i for i in self.order if self.attached.get(i))

    def selection(self):
        return tuple(i for i in self.order if i in self._selected and self.attached.get(i))

    def selection_set(self, *items):
        if len(items) == 1 and isinstance(items[0], (tuple, list)):
            items = items[0]
        self._set_selection(list(items))

    # ---- layout / selection / events
    def reorder(self, ids):
        wanted = set(ids)
        new = [i for i in ids if i in self.cards] + [i for i in self.order if i not in wanted]
        if new != self.order:
            self.order = new
            self._relayout()

    def refresh_empty(self):
        if not self.get_children():
            self.empty.configure(text=self.empty_text)

    def _relayout(self):
        for c in self.cards.values():
            c.frame.pack_forget()
        self.empty.pack_forget()
        shown = self.get_children()
        for iid in shown:
            self.cards[iid].frame.pack(fill="x", padx=(0, 8), pady=(0, 10))
        if not shown:
            self.empty.configure(text=self.empty_text)
            self.empty.pack(pady=70)

    def _set_selection(self, sel):
        old = set(self._selected)
        self._selected = [i for i in sel if i in self.cards]
        for iid in old ^ set(self._selected):
            if iid in self.cards:
                card = self.cards[iid]
                card.selected = iid in self._selected
                card.paint()

    def _click(self, iid, event):
        shown, ctrl, shift = list(self.get_children()), bool(event.state & 0x4), bool(event.state & 0x1)
        if shift and self._anchor in shown:
            a, b = shown.index(self._anchor), shown.index(iid)
            sel = shown[min(a, b):max(a, b) + 1]
        elif ctrl:
            cur = list(self.selection())
            sel = [x for x in cur if x != iid] if iid in cur else cur + [iid]
            self._anchor = iid
        else:
            sel, self._anchor = [iid], iid
        self._set_selection(sel)
        if self.on_select:
            self.on_select()

    def _blank_click(self, event):
        self._set_selection([])
        if self.on_select:
            self.on_select()

    def _double(self, iid):
        self._set_selection([iid])
        if self.on_double:
            self.on_double(iid)

    def _context(self, iid, event):
        if iid not in self.selection():
            self._set_selection([iid])
        if self.on_context:
            self.on_context(iid, event.x_root, event.y_root)

    def _action(self, iid, name, event):
        if self.on_action:
            self.on_action(iid, name, event)

    def _wheel(self, event):
        if self.inner.winfo_height() <= self.canvas.winfo_height():
            return
        units = -2 if event.num == 4 else 2 if event.num == 5 else -int(event.delta / 60)
        self.canvas.yview_scroll(units, "units")
