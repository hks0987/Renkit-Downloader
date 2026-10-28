"""The main window: list, toolbar, right-click menu, queue, duplicate handling, download engine."""
from theme import STATE, F, set_mode
from ui import CardList, FlatButton
from common import clipboard_url, explain_exception, remove_cache_dir
import os
import time
import json
import queue
import shutil
import datetime
import subprocess
import threading
from pathlib import Path, PureWindowsPath
from common import (CACHE_DIR, CONFIG_FILE, DARK_THEME, LinkRejected, RateLimiter, RepairError, SETTINGS, _Tk, apply_dark_theme, cache_path, category_dir, category_for, center_window, check_free_space, check_url, expiry_text, extract_filename_from_url, fetch_range, filedialog, format_bytes, format_time, get_setting, hdrs_from_payload, link_expiry, load_settings, log_error, merge_file_parts, messagebox, new_task, norm_path, normalize_status, open_path, plan_units, probe_url, safe_int, sanitize_filename, save_settings, stream_whole, task_id_for, tk, ttk, unique_destination, verify_file)
from dialogs import DownloadCompleteDialog, PropertiesWindow, SettingsWindow, ask_choice, prompt_link
from windows import ActiveDownloadWindow, IDMDownloadDialog
from server import start_local_server


def status_tag(status):
    """Colour group for a status (errors red, finished green, paused grey, busy blue)."""
    if status == "Error":
        return "st_error"
    if status == "Complete":
        return "st_done"
    if status in ("Paused", "Queued"):
        return "st_idle"
    return "st_busy"


class MainDownloadManagerApp(_Tk):
    _side_keys = {"Archives": "Compressed", "Documents": "Documents", "Music": "Music", "Apps": "Programs", "Video": "Video"}
    SORT_LABELS = {"added": "Date added", "name": "Name", "size": "Size", "status": "Status", "progress": "Progress", "last_try": "Last activity"}

    def __init__(self):
        super().__init__()
        load_settings()
        set_mode(get_setting("theme"), get_setting("accent"))
        self.title("Renkit downloader")
        self.geometry("1180x680")
        self.minsize(1060, 560)
        center_window(self, 1180, 680)
        apply_dark_theme(self)

        self.events = queue.Queue()
        self.tasks = {}
        self.recent_destinations = []
        self.queue_running = False
        self._toast_text, self._toast_until = "", 0.0
        self._grid_lines, self._grid_pending = [], False
        self.apply_settings()

        self._load_logo()
        self._build_ui()
        self.load_persistent_tasks()
        self.after(100, self._poll_events)
        self.after(1000, self._tick)
        self.start_local_server()

    # ------------------------------------------------------------ settings / status bar
    def apply_settings(self):
        seen = []
        dirs = [norm_path(d) for d in (get_setting("category_dirs") or {}).values()]
        for d in list(self.recent_destinations) + dirs:
            if d and d not in seen:
                seen.append(d)
        self.recent_destinations = seen[:10]

    def _remember_dest(self, folder):
        folder = norm_path(folder)
        if folder:
            self.recent_destinations = [folder] + [d for d in self.recent_destinations if d != folder][:9]

    def toast(self, text, seconds=6):
        self._toast_text, self._toast_until = text, time.time() + seconds
        self._update_statusbar()

    def _update_statusbar(self):
        running = [t for t in self.tasks.values() if t.get("running")]
        speed = sum(t.get("speed", 0) for t in running)
        queued = sum(1 for t in self.tasks.values() if t.get("queued") and t.get("status") != "Complete")
        text = f"{len(running)} active   |   {format_bytes(speed)}/sec   |   {queued} waiting"
        if self.queue_running:
            text += "   (waiting list running)"
        if self._toast_text and time.time() < self._toast_until:
            text = f"{self._toast_text}      ||      {text}"
        self.status_var.set(text)

    def on_open_settings(self):
        SettingsWindow(self)

    # ------------------------------------------------------------ layout
    def _load_logo(self):
        self._logo = self._logo_big = self._icon = None
        try:
            assets = Path(__file__).resolve().parent / "assets"
            self._logo_big = tk.PhotoImage(file=str(assets / "renkit_64.png"))
            self._logo = self._logo_big.subsample(2, 2)
            self._icon = tk.PhotoImage(file=str(assets / "renkit_256.png"))
            self.iconphoto(True, self._icon)
            if os.name == "nt":
                try:
                    self.iconbitmap(str(assets / "renkit.ico"))
                except tk.TclError:
                    pass
        except Exception:
            pass

    def _build_ui(self):
        t = DARK_THEME
        self.configure(bg=t["bg"])
        self.nav_choice = getattr(self, "nav_choice", "Everything")
        side = tk.Frame(self, bg=t["surface"], width=224)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=t["surface"])
        brand.pack(fill="x", padx=20, pady=(22, 18))
        if self._logo is not None:
            tk.Label(brand, image=self._logo, bg=t["surface"]).pack(side="left")
        tk.Label(brand, text="Renkit", bg=t["surface"], fg=t["text"], font=F(17, True)).pack(side="left", padx=(10, 0))
        self._nav_items = {}

        def section(title):
            tk.Label(side, text=title, bg=t["surface"], fg=t["muted"], font=F(8, True), anchor="w").pack(fill="x", padx=22, pady=(14, 4))

        def nav(name, text, indent=0):
            lbl = tk.Label(side, text=text, anchor="w", bg=t["surface"], fg=t["muted"], font=F(10), padx=14 + indent, pady=7, cursor="hand2")
            lbl.pack(fill="x", padx=10)
            lbl.bind("<Button-1>", lambda e, n=name: self.set_nav(n))
            self._nav_items[name] = (lbl, text)

        section("LIBRARY")
        nav("Everything", "Everything")
        for name in self._side_keys:
            nav(name, name, 14)
        section("STATUS")
        for name in ("Active", "Waiting", "Needs attention", "Finished"):
            nav(name, name)
        tk.Label(side, text="open source", bg=t["surface"], fg=t["muted"], font=F(8)).pack(side="bottom", pady=14)

        main = tk.Frame(self, bg=t["bg"])
        main.pack(side="left", fill="both", expand=True)
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(main, textvariable=self.status_var, anchor="w", bg=t["bg"], fg=t["muted"], font=F(9)).pack(side="bottom", fill="x", padx=22, pady=(0, 10))
        top = tk.Frame(main, bg=t["bg"])
        top.pack(side="top", fill="x", padx=22, pady=(20, 12))
        for text, cmd in (("About", self.on_about), ("Settings", self.on_open_settings), ("\u25d0", self.toggle_theme)):
            FlatButton(top, text, cmd, kind="ghost").pack(side="right")
        FlatButton(top, "Waiting list \u25be", self._show_queue_menu, kind="ghost", pass_event=True).pack(side="right")
        for text, cmd in (("Remove", self.on_delete_task), ("Pause", self.on_stop_task), ("Resume", self.on_resume_task)):
            FlatButton(top, text, cmd, kind="soft").pack(side="right", padx=(0, 6))
        FlatButton(top, "+  Add link", self.on_add_url_prompt, kind="primary", padx=18, pady=9).pack(side="left")
        tk.Label(top, text="Search", bg=t["bg"], fg=t["muted"], font=F(9)).pack(side="left", padx=(18, 6))
        self.search_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.search_var, width=8).pack(side="left", fill="x", expand=True, padx=(0, 14))
        self.search_var.trace_add("write", lambda *a: self.apply_category_filter())
        head = tk.Frame(main, bg=t["bg"])
        head.pack(side="top", fill="x", padx=(24, 14), pady=(0, 8))
        self.view_title = tk.Label(head, text=self.nav_choice, bg=t["bg"], fg=t["text"], font=F(13, True))
        self.view_title.pack(side="left")
        self.view_count = tk.Label(head, text="", bg=t["bg"], fg=t["muted"], font=F(9))
        self.view_count.pack(side="left", padx=(10, 0), pady=(3, 0))
        self.sort_dir_btn = FlatButton(head, "\u2191", self.toggle_sort_dir, kind="ghost", padx=9, pady=4)
        self.sort_dir_btn.pack(side="right")
        self.sort_btn = FlatButton(head, "Sort", self._show_sort_menu, kind="ghost", pass_event=True, padx=10, pady=4)
        self.sort_btn.pack(side="right")
        self._update_sort_button()
        self.tree = CardList(main, on_action=self._on_card_action, on_context=self._on_card_context, on_double=self._on_card_double)
        self.tree.pack(side="top", fill="both", expand=True, padx=(22, 10), pady=(0, 8))
        self.bind("<Control-m>", lambda e: self._ctx_rename(self._first_selected()))
        self.bind("<Delete>", lambda e: None if isinstance(e.widget, (tk.Entry, ttk.Entry)) else self.on_delete_task())
        self.bind("<Control-v>", self._paste_link)
        self._paint_nav()

    def _update_sort_button(self):
        self.sort_btn.configure(text=f"Sort: {self.SORT_LABELS.get(get_setting('sort_key'), 'Date added')}  \u25be")
        self.sort_dir_btn.configure(text="\u2193" if get_setting("sort_desc") else "\u2191")

    def _sort_menu(self):
        t = DARK_THEME
        m = tk.Menu(self, tearoff=0, bg=t["surface"], fg=t["text"], activebackground=t["accent"], activeforeground=t["on_accent"], bd=0)
        m._choice = tk.StringVar(value=get_setting("sort_key"))
        for key, label in self.SORT_LABELS.items():
            m.add_radiobutton(label=label, value=key, variable=m._choice, command=lambda k=key: self.set_sort(k))
        m.add_separator()
        m.add_command(label="Reverse order", command=self.toggle_sort_dir)
        return m

    def _show_sort_menu(self, event):
        menu = self._sort_menu()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def set_sort(self, key, desc=None):
        SETTINGS["sort_key"] = key
        if desc is not None:
            SETTINGS["sort_desc"] = bool(desc)
        save_settings()
        self._update_sort_button()
        self._apply_sort()

    def toggle_sort_dir(self):
        self.set_sort(get_setting("sort_key"), not get_setting("sort_desc"))

    def _sort_value(self, tid, key):
        t = self.tasks[tid]
        if key == "name":
            return t["filename"].lower()
        if key == "size":
            return t.get("size") or 0
        if key == "added":
            return t.get("added", 0.0)
        if key == "progress":
            return self.tree.set(tid, "progress") if self.tree.exists(tid) else 0
        if key == "status":
            return 0 if t.get("running") else {"Queued": 1, "Paused": 2, "Error": 3, "Complete": 4}.get(t.get("status", ""), 2)
        if key == "last_try":
            try:
                return time.mktime(time.strptime(t.get("last_try", ""), "%b %d %Y"))
            except Exception:
                return 0
        return 0

    def _apply_sort(self):
        key, desc = get_setting("sort_key"), bool(get_setting("sort_desc"))
        index = {tid: i for i, tid in enumerate(self.tasks)}
        ordered = sorted(self.tasks, key=lambda tid: (self._sort_value(tid, key), index[tid]), reverse=desc)
        self.tree.reorder(ordered)
        self.restripe()

    def _paint_nav(self):
        t = DARK_THEME
        for name, (lbl, _text) in self._nav_items.items():
            on = name == self.nav_choice
            lbl.configure(bg=t["surface2"] if on else t["surface"], fg=t["text"] if on else t["muted"], font=F(10, on))

    def set_nav(self, name):
        self.nav_choice = name
        self._paint_nav()
        self.apply_category_filter()

    def _update_nav_counts(self):
        for name, (lbl, text) in getattr(self, "_nav_items", {}).items():
            n = sum(1 for t in self.tasks.values() if self._matches(name, t))
            lbl.configure(text=f"{text}   {n}" if n else text)

    def _show_queue_menu(self, event):
        t = DARK_THEME
        m = tk.Menu(self, tearoff=0, bg=t["surface"], fg=t["text"], activebackground=t["accent"], activeforeground=t["on_accent"], bd=0)
        m.add_command(label="Run waiting list", command=self.on_start_queue)
        m.add_command(label="Pause waiting list", command=self.on_stop_queue)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _paste_link(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
            return
        url = clipboard_url(self)
        if url:
            self.handle_incoming_url({"url": url})

    def toggle_theme(self):
        SETTINGS["theme"] = "light" if STATE["mode"] == "dark" else "dark"
        save_settings()
        self.apply_appearance()

    def apply_appearance(self):
        """Switch theme/accent: rebuild the main window; open progress windows are closed."""
        set_mode(get_setting("theme"), get_setting("accent"))
        apply_dark_theme(self)
        for t in self.tasks.values():
            win = self._win(t)
            if win is not None:
                win.destroy()
            t["active_win"] = None
        for child in list(self.winfo_children()):
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        self._build_ui()
        for tid, t in self.tasks.items():
            self._insert_row(tid, t)
        self.apply_category_filter()

    def _on_card_action(self, iid, name, event):
        t = self.tasks.get(iid)
        if t is None:
            return
        if name == "toggle":
            if t.get("running"):
                self.pause_task(iid)
            elif t.get("status") == "Complete":
                open_path(t["dest"])
            else:
                self.resume_task(iid)
        elif name == "folder":
            self._open_folder(t)
        elif name == "more":
            self._on_card_context(iid, event.x_root, event.y_root)

    def _on_card_context(self, iid, x, y):
        if iid not in self.tasks:
            return
        menu = self._ctx_menu(iid)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_card_double(self, iid):
        self.on_double_click_task(None)

    # ------------------------------------------------------------ local server for the browser extension
    def start_local_server(self):
        start_local_server(self)

    # ------------------------------------------------------------ adding links
    def on_add_url_prompt(self):
        url = prompt_link(self, "Add link", "Enter the download link (a link on your clipboard is filled in for you):")
        if url:
            self.handle_incoming_url({"url": url})

    def handle_incoming_url(self, payload):
        if isinstance(payload, str):
            payload = {"url": payload}
        try:
            check_url(payload.get("url"))
        except RepairError as e:
            messagebox.showerror("Invalid link", str(e))
            return
        threading.Thread(target=self._resolve_incoming, args=(payload,), daemon=True).start()

    @staticmethod
    def _pick_name(payload, info):
        candidates = []
        if info and info.get("name") and info["name"] != "downloaded_file":
            candidates.append(info["name"])
        if payload.get("filename"):
            candidates.append(sanitize_filename(payload["filename"]))
        candidates.append(extract_filename_from_url(payload["url"]))
        for c in candidates:
            if "." in c:
                return c
        return candidates[0]

    def _resolve_incoming(self, payload):
        """Runs off the UI thread: reads the link's details and looks for an unfinished IDM download."""
        info = err = matched = None
        try:
            info = probe_url(payload["url"], extra=hdrs_from_payload(payload))
        except RepairError as e:
            err = str(e)
        except Exception as e:
            log_error("_resolve_incoming probe")
            err = str(e)
        name = self._pick_name(payload, info)
        self.events.put(("incoming_ready", (payload, info, err, name, matched)))

    def _copy_clip(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
        except Exception:
            pass

    def _find_task(self, name, total):
        for tid, t in self.tasks.items():
            if t["filename"].lower() == name.lower() and (not total or not t["size"] or t["size"] == total):
                return tid
        return None

    def _unique_name(self, folder, name):
        stem, suffix = Path(name).stem, Path(name).suffix
        candidate, i = name, 1
        while (Path(folder) / candidate).exists() or task_id_for(Path(folder) / candidate) in self.tasks:
            candidate = f"{stem} ({i}){suffix}"
            i += 1
        return candidate

    def _incoming_ready(self, payload, info, err, name, matched):
        url = payload["url"]
        if get_setting("copy_link_to_clipboard"):
            self._copy_clip(url)
        total = info["total"] if info else safe_int(payload.get("size"))
        hdrs = hdrs_from_payload(payload)
        folder = category_dir(category_for(name))
        existing_id = self._find_task(name, total)
        existing = self.tasks.get(existing_id) if existing_id else None
        final = folder / name
        done_task = existing if (existing and existing["status"] == "Complete") else None
        on_disk = final.exists() and (not total or final.stat().st_size == total)
        policy = get_setting("duplicate_policy")

        # 1) the file is already there
        if done_task or on_disk:
            shown = Path(done_task["dest"]) if done_task else final
            if policy == "resume_or_complete":
                DownloadCompleteDialog(self, shown, already=True)
                return
            choice = {"numbered": 1, "overwrite": 2}.get(policy)
            if policy == "ask":
                choice = ask_choice(self, "Already downloaded", f"{name} is already in your downloads.",
                                    ["Show file", "Download again (new name)", "Download again (overwrite)", "Cancel"])
            if choice is None or choice == 3:
                return
            if choice == 0:
                DownloadCompleteDialog(self, shown, already=True)
                return
            self._start_new(payload, info, err, name, total, hdrs, numbered=(choice == 1), overwrite=(choice == 2),
                            replace_id=existing_id if (done_task and choice == 2) else None)
            return

        # 2) same file, not finished yet: resume it with this (new) link, or start over
        if existing:
            if existing.get("running"):
                existing["url"] = url
                self.toast(f"{name} is already downloading.")
                return
            if policy == "resume_or_complete":
                choice = 0
            elif policy == "ask":
                choice = ask_choice(self, "Unfinished download found",
                                    f"{name} was started before but not finished.\nIts old link may have expired.",
                                    ["Resume it with this new link", "Download again (remove the previous one)", "Cancel"])
            elif policy == "numbered":
                choice = 3
            else:
                choice = 1
            if choice == 0:
                if total and existing["size"] and existing["size"] != total:
                    messagebox.showerror("Different file", f"This link is {format_bytes(total)} but the unfinished "
                                         f"download is {format_bytes(existing['size'])}. Choose 'Download again'.")
                    return
                existing["url"] = url
                if hdrs:
                    existing["hdrs"] = hdrs
                self.save_task_state()
                self.start_task(existing_id)
            elif choice == 1:
                self.remove_task(existing_id)
                self._start_new(payload, info, err, name, total, hdrs, overwrite=True)
            elif choice == 3:
                self._start_new(payload, info, err, name, total, hdrs, numbered=True)
            return

        # 3) brand new download
        self._start_new(payload, info, err, name, total, hdrs)

    def _start_new(self, payload, info, err, name, total, hdrs, numbered=False, overwrite=False, replace_id=None):
        if replace_id:
            self.remove_task(replace_id)
        cat = category_for(name)
        folder = category_dir(cat)
        if numbered:
            name = self._unique_name(folder, name)

        def go(u, dest, c, desc, **kw):
            return self.register_task(u, dest, c, desc, overwrite=overwrite, **kw)

        if get_setting("show_start_dialog"):
            IDMDownloadDialog(self, payload, info, err, name, hdrs, self.recent_destinations, go)
        else:
            only_queue = bool(get_setting("only_add_to_queue"))
            go(payload["url"], folder, cat, "", start_immediately=not only_queue, resolved_filename=name,
               resolved_size=total, hdrs=hdrs, queued=only_queue)

    # ------------------------------------------------------------ list helpers
    @staticmethod
    def _win(t):
        win = t.get("active_win")
        try:
            if win is not None and win.winfo_exists():
                return win
        except Exception:
            pass
        return None

    def _first_selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def set_status(self, task_id, text):
        t = self.tasks.get(task_id)
        if t is not None:
            t["status"] = text
        if self.tree.exists(task_id):
            self.tree.set(task_id, "status", text)
            self._retag(task_id)

    def _retag(self, task_id):
        try:
            stripe = "evenrow" if self.tree.index(task_id) % 2 == 0 else "oddrow"
            self.tree.item(task_id, tags=(stripe, status_tag(self.tasks.get(task_id, {}).get("status", ""))))
        except Exception:
            pass

    def restripe(self):
        for i, iid in enumerate(self.tree.get_children("")):
            self.tree.item(iid, tags=("evenrow" if i % 2 == 0 else "oddrow",
                                      status_tag(self.tasks.get(iid, {}).get("status", ""))))

    def _matches(self, name, t):
        status = t.get("status", "")
        if name == "Everything":
            return True
        if name == "Active":
            return bool(t.get("running"))
        if name == "Waiting":
            return (bool(t.get("queued")) or status == "Queued") and not t.get("running") and status != "Complete"
        if name == "Needs attention":
            return status == "Error"
        if name == "Finished":
            return status == "Complete"
        return t.get("category") == self._side_keys.get(name, name)

    def apply_category_filter(self):
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        for tid, t in self.tasks.items():
            if not self.tree.exists(tid):
                continue
            show = self._matches(self.nav_choice, t) and (not query or query in t["filename"].lower())
            if show:
                self.tree.reattach(tid, "", "end")
            else:
                self.tree.detach(tid)
        self.tree.empty_text = ("Nothing here yet.\nClick  + Add link  or press Ctrl+V with a link copied."
                                if not self.tasks else "No downloads match this view.")
        self.tree.refresh_empty()
        self._apply_sort()
        self._update_nav_counts()
        if hasattr(self, "view_title"):
            n = len(self.tree.get_children())
            self.view_title.configure(text=self.nav_choice)
            self.view_count.configure(text=f"{n} download" + ("" if n == 1 else "s"))

    def on_about(self):
        messagebox.showinfo("About Renkit",
                            "Renkit\n\nAn independent download manager that can also rescue unfinished "
                            "downloads left behind by other programs.\n\nNot affiliated with, endorsed by, or "
                            "connected to Internet Download Manager or Tonec Inc. All product names belong to their owners.",
                            parent=self)

    def _insert_row(self, task_id, t):
        name = t["filename"]
        ftype = name.split(".")[-1].upper() + " File" if "." in name else "File"
        self.tree.insert("", "end", iid=task_id, values=(
            name, "\u25cf" if t.get("queued") else "", format_bytes(t["size"]) if t["size"] else "Unknown", t["status"],
            t.get("remaining_text", ""), "", ftype, t.get("description", ""), t.get("last_try") or "-"))
        self.tree.set(task_id, "progress", 100 if t["status"] == "Complete" else (min(100, t.get("downloaded", 0) * 100 // t["size"]) if t.get("size") else 0))

    # ------------------------------------------------------------ task registry
    def register_task(self, url, dest_folder, category="General", description="", start_immediately=True,
                      resolved_filename=None, resolved_size=0, hdrs=None, overwrite=False, queued=False, plan=None):
        try:
            check_url(url)
        except RepairError as e:
            messagebox.showerror("Invalid link", str(e))
            return None
        filename = sanitize_filename(resolved_filename) if resolved_filename else extract_filename_from_url(url)
        out_path = Path(norm_path(dest_folder)) / filename
        task_id = task_id_for(out_path)
        self._remember_dest(out_path.parent)

        existing = self.tasks.get(task_id)
        if existing is not None:
            if existing.get("status") == "Complete":
                if not (overwrite or plan):
                    messagebox.showinfo("Already downloaded", f"{filename} is already complete in your list.")
                    return task_id
                self.remove_task(task_id)
            else:  # same file again (e.g. with a fresh link): update the link instead of ignoring it
                existing["url"] = url
                if hdrs:
                    existing["hdrs"] = hdrs
                if plan:
                    existing["plan"] = plan
                    existing["size"] = plan["total"]
                if overwrite:
                    existing["overwrite"] = True
                self.save_task_state()
                if existing.get("running"):
                    messagebox.showinfo("Link updated", "This file is already downloading. The new link will be used the next time it resumes.")
                elif start_immediately:
                    self.start_task(task_id)
                return task_id

        t = new_task(filename, safe_int(resolved_size), url, out_path, category, description, "Queued")
        t["hdrs"], t["plan"], t["overwrite"], t["queued"] = hdrs or {}, plan, bool(overwrite), bool(queued)
        t["added"] = time.time()
        work = norm_path(get_setting("temp_dir") or "")
        t["cache_root"] = work if work and work != norm_path(CACHE_DIR) else str(out_path.parent / ".renkit")
        self.tasks[task_id] = t
        self._insert_row(task_id, t)
        self.restripe()
        self.apply_category_filter()
        self.save_task_state()
        if start_immediately:
            self.start_task(task_id)
        return task_id

    def save_task_state(self):
        try:
            data = {}
            for tid, t in self.tasks.items():
                data[tid] = {
                    "filename": t["filename"], "size": t["size"], "url": t["url"], "dest": str(t["dest"]),
                    "category": t["category"], "description": t["description"],
                    "status": normalize_status(t.get("status")), "etag": t.get("etag", ""),
                    "last_try": t.get("last_try", ""), "cache_key": t.get("cache_key"),
                    "hdrs": {k: v for k, v in (t.get("hdrs") or {}).items() if k != "cookie"},  # cookies stay in memory only
                    "plan": t.get("plan"), "queued": bool(t.get("queued")), "overwrite": bool(t.get("overwrite")),
                    "ranges": t.get("ranges"), "ranges_total": t.get("ranges_total", 0),
                    "cache_root": t.get("cache_root", ""), "md5": t.get("md5", ""),
                    "downloaded": t.get("downloaded", 0), "remaining_text": t.get("remaining_text", ""), "added": t.get("added", 0.0),
                }
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)  # atomic: a crash can never leave half a file
        except Exception:
            log_error("save_task_state")

    def load_persistent_tasks(self):
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            log_error("load_persistent_tasks: config unreadable")
            try:
                shutil.copy(CONFIG_FILE, CONFIG_FILE.with_suffix(".corrupt"))
            except Exception:
                pass
            return
        for tid, d in data.items():
            try:
                if tid in self.tasks:
                    continue
                t = new_task(d["filename"], safe_int(d.get("size")), d.get("url", ""), d["dest"],
                             d.get("category", "General"), d.get("description", ""),
                             normalize_status(d.get("status")), d.get("etag", ""), d.get("last_try", ""), d.get("cache_key"))
                t["hdrs"], t["plan"] = d.get("hdrs") or {}, d.get("plan")
                t["queued"], t["overwrite"] = bool(d.get("queued")), bool(d.get("overwrite"))
                t["ranges"], t["ranges_total"] = d.get("ranges"), safe_int(d.get("ranges_total"))
                t["cache_root"], t["md5"] = d.get("cache_root", ""), d.get("md5", "")
                t["downloaded"], t["remaining_text"] = safe_int(d.get("downloaded")), d.get("remaining_text", "")
                t["added"] = float(d.get("added") or 0)
                if t["status"] == "Paused" and t["size"] and t["downloaded"] and not t["remaining_text"]:
                    t["remaining_text"] = f"{max(0, 100 - t['downloaded'] * 100 // t['size'])}% left"
                self.tasks[tid] = t
                self._insert_row(tid, t)
            except Exception:
                log_error("load_persistent_tasks: bad entry")
        self.restripe()

    def remove_task(self, task_id, delete_file=False):
        t = self.tasks.pop(task_id, None)
        if t is None:
            return
        t["cancel"].set()
        win = self._win(t)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        if delete_file and t.get("status") == "Complete":
            try:
                Path(t["dest"]).unlink()
            except OSError:
                pass
        timer = threading.Timer(3.0, remove_cache_dir, args=(cache_path(t),))
        timer.daemon = True  # give running threads a moment to stop writing first
        timer.start()
        if self.tree.exists(task_id):
            self.tree.delete(task_id)
        self.restripe()
        self.save_task_state()

    # ------------------------------------------------------------ start / pause / resume
    def prompt_new_link(self, task_id, reason=""):
        t = self.tasks.get(task_id)
        if t is None:
            return False
        text = (reason + "\n\n" if reason else "") + f"Paste a fresh link for the SAME file:\n{t['filename']}"
        new = prompt_link(self, "Replace expired link", text)
        if not new:
            return False
        t["url"] = new
        self.save_task_state()
        if t.get("status") != "Complete":
            return self.start_task(task_id)
        return True

    def start_task(self, task_id, window=None, interactive=True):
        t = self.tasks.get(task_id)
        if t is None:
            return False
        if t.get("status") == "Complete":
            messagebox.showinfo("Already complete", f"{t['filename']} is already downloaded.")
            return False
        if t.get("running"):
            return False
        if not t.get("url"):
            messagebox.showerror("Error", "No download URL available for this item.")
            return False
        exp = link_expiry(t["url"])
        if interactive and exp is not None and exp < datetime.datetime.now(datetime.timezone.utc):
            return self.prompt_new_link(task_id, "The saved link has expired.")
        t["cancel"] = threading.Event()  # a fresh flag per run, so an old run can never be revived by a new one
        t["running"] = True
        t["last_try"] = time.strftime("%b %d %Y")
        self.set_status(task_id, "Connecting...")
        self.apply_category_filter()
        if self.tree.exists(task_id):
            self.tree.set(task_id, "last_try", t["last_try"])
        win = window if window is not None else self._win(t)
        if win is None and interactive:
            win = ActiveDownloadWindow(self, t, app_ref=self, task_id=task_id)
        elif win is not None:
            try:
                win.is_paused = False
                win.pause_btn.configure(text="Pause")
            except Exception:
                pass
        t["active_win"] = win
        self.save_task_state()
        threading.Thread(target=self._worker_download_task, args=(task_id, t["cancel"]), daemon=True).start()
        return True

    def pause_task(self, task_id):
        t = self.tasks.get(task_id)
        if t is None or t.get("status") == "Complete":
            return
        t["cancel"].set()
        self.set_status(task_id, "Paused")
        if self.tree.exists(task_id):
            self.tree.set(task_id, "transfer_rate", "")
        self.save_task_state()

    def resume_task(self, task_id, window=None):
        t = self.tasks.get(task_id)
        if t is None:
            return False
        if t.get("running"):
            if t["cancel"].is_set():
                messagebox.showinfo("Please wait", "The previous run is still stopping. Try again in a moment.")
            return False
        return self.start_task(task_id, window)

    def _worker_download_task(self, task_id, cancel):
        put = self.events.put
        t = self.tasks.get(task_id)
        if t is None:
            return
        errors = []
        try:
            url, extra, plan = t["url"], t.get("hdrs") or {}, t.get("plan")
            check_url(url)
            put(("run_info", (task_id, "Checking...")))
            info = probe_url(url, extra=extra)
            expected = plan["total"] if plan else t["size"]
            if expected and info["total"] and info["total"] != expected:
                raise RepairError(f"This link is for a different file: it is {format_bytes(info['total'])} but this "
                                  f"download expects {format_bytes(expected)}.")
            if (not get_setting("ignore_modification") and t.get("etag") and info["etag"]
                    and info["etag"] != t["etag"]):
                raise RepairError("The file on the server has changed since this download started (different ETag). "
                                  "Remove this item and add the link again to start over, or tick 'Ignore file "
                                  "modification time changes' in Options.")
            t["etag"] = info["etag"] or t.get("etag", "")
            t["md5"] = info.get("md5", "")
            total = expected or info["total"]
            t["size"] = total
            ranged = info["supports_range"] and total > 0
            if plan and not ranged:
                raise RepairError("This link does not allow downloading just the missing parts, so the repair can't use it.")
            put(("run_info", (task_id, "Yes" if ranged else "No (single connection)")))

            cache = cache_path(t)
            cache.mkdir(parents=True, exist_ok=True)
            real_name = info["name"]
            if (not plan and real_name and real_name != "downloaded_file" and real_name != t["filename"]
                    and t["filename"] in (extract_filename_from_url(url), "downloaded_file")
                    and not any(cache.glob("part_*"))):
                t["filename"] = real_name
                t["dest"] = str(Path(t["dest"]).parent / real_name)
                put(("rename_task", (task_id, real_name)))
            out_path = Path(t["dest"])

            plan_segments = []
            if plan:
                for off, p, skip, length in plan["segments"]:
                    if not Path(p).exists():
                        raise RepairError(f"IDM's piece file is missing: {Path(p).name}. It was moved or deleted, "
                                          "so this repair can no longer be completed.")
                    plan_segments.append((int(off), Path(p), int(skip), int(length)))

            if ranged:
                if not plan and t.get("ranges") and t.get("ranges_total") == total:
                    units = [tuple(r) for r in t["ranges"]]
                else:
                    units = plan_units(total, max(1, int(get_setting("connections"))), plan)
                    if not plan:
                        t["ranges"], t["ranges_total"] = [list(u) for u in units], total
            else:
                units = [(0, total - 1 if total > 0 else None)]
            part_paths = [cache / f"part_{s}" for s, _ in units]
            if not ranged:  # without Range support a partial file can't be continued
                for p in part_paths:
                    try:
                        p.unlink()
                    except OSError:
                        pass

            counters = []
            for i, (s, e) in enumerate(units):
                have = part_paths[i].stat().st_size if part_paths[i].exists() else 0
                counters.append(min(have, e - s + 1) if e is not None else have)
            n_workers = min(max(1, int(get_setting("connections"))), len(units)) if ranged else 1
            for w in range(n_workers):
                t["thread_progress"][w] = (0, "Waiting...")
            if total:
                check_free_space(cache, max(sum((e - s + 1) for s, e in units if e is not None) - sum(counters), 0))
            limiter = RateLimiter(lambda: t.get("speed_limit") or int(get_setting("speed_limit_kb")) * 1024)
            work = queue.Queue()
            for i in range(len(units)):
                work.put(i)
            wbytes = [0] * n_workers
            base = plan["have"] if plan else 0

            def worker(w):
                while not cancel.is_set():
                    try:
                        i = work.get_nowait()
                    except queue.Empty:
                        break
                    s, e = units[i]

                    def cb(n, i=i):
                        counters[i] += n
                        wbytes[w] += n

                    try:
                        if ranged:
                            ok = fetch_range(url, s, e, part_paths[i], cancel, expected_total=total,
                                             limiter=limiter, on_progress=cb, extra=extra)
                        else:
                            ok = stream_whole(url, part_paths[i], cancel, total, limiter, cb, extra=extra)
                        if not ok:
                            break
                    except LinkRejected as ex:
                        errors.append(("link", str(ex)))
                        cancel.set()
                        break
                    except RepairError as ex:
                        errors.append(("err", str(ex)))
                        cancel.set()
                        break
                    except Exception as ex:
                        log_error("download worker")
                        errors.append(("err", f"Unexpected error: {ex}"))
                        cancel.set()
                        break
                t["thread_progress"][w] = (wbytes[w], "Finished" if not cancel.is_set() else "Stopped")

            threads = [threading.Thread(target=worker, args=(w,), daemon=True) for w in range(n_workers)]
            for th in threads:
                th.start()

            last_time, last_bytes, speed = time.time(), base + sum(counters), 0.0
            while any(th.is_alive() for th in threads):
                time.sleep(0.25)
                done = base + sum(counters)
                if total:
                    done = min(done, total)
                now = time.time()
                dt = now - last_time
                inst = (done - last_bytes) / dt if dt > 0 else 0
                speed = inst if speed <= 0 else speed * 0.5 + inst * 0.5
                last_time, last_bytes = now, done
                t["downloaded"], t["speed"] = done, speed
                for w, th in enumerate(threads):
                    if th.is_alive():
                        t["thread_progress"][w] = (wbytes[w], "Receiving data...")
                pct = min(int(done * 100 / total), 99) if total else 0
                eta = (total - done) / speed if (total and speed > 0) else 0
                put(("update_task", (task_id, f"{pct}%", format_bytes(speed) + "/sec", format_time(eta), done, total, speed)))
                put(("thread_tick", task_id))
            for th in threads:
                th.join()
            t["speed"] = 0.0

            if errors:
                raise (LinkRejected if errors[0][0] == "link" else RepairError)(errors[0][1])
            if cancel.is_set():
                put(("task_paused", task_id))
                return

            shown = total or (base + sum(counters))
            put(("update_task", (task_id, "100%", "0 B/s", "00:00", shown, shown, 0.0)))
            put(("task_stitching", task_id))
            if ranged:
                segments = plan_segments + [(s, part_paths[i], 0, e - s + 1) for i, (s, e) in enumerate(units)]
                expected_total = total
            else:
                segments = [(0, part_paths[0], 0, part_paths[0].stat().st_size)]
                expected_total = total or None
            final_path = out_path
            if final_path.exists() and not t.get("overwrite"):  # never silently overwrite an existing file
                final_path = unique_destination(final_path.parent, final_path.name)
                t["dest"], t["filename"] = str(final_path), final_path.name
                put(("rename_task", (task_id, final_path.name)))
            last_pct = [-1]

            def stitch_cb(written, tot):
                pct = int(written * 100 / tot)
                if pct != last_pct[0]:
                    last_pct[0] = pct
                    put(("update_stitch_progress", (task_id, pct)))

            merge_file_parts(segments, final_path, progress_cb=stitch_cb, cancel_event=cancel, expected_total=expected_total)
            remove_cache_dir(cache)
            if get_setting("verify_after_download"):
                put(("task_verifying", task_id))
                ok, msg = verify_file(final_path, t.get("md5") or None)
                put(("task_verified", (task_id, ok, msg)))
            put(("task_done", task_id))
        except LinkRejected as e:
            put(("task_error", (task_id, str(e), "link")))
        except RepairError as e:
            if errors or not cancel.is_set():
                put(("task_error", (task_id, str(e), "")))
            else:
                put(("task_paused", task_id))
        except Exception as e:
            log_error("_worker_download_task")
            put(("task_error", (task_id, explain_exception(e), "")))
        finally:
            put(("run_finished", task_id))

    # ------------------------------------------------------------ queue
    def on_start_queue(self):
        self.queue_running = True
        self.toast("Waiting list started.")

    def on_stop_queue(self):
        self.queue_running = False
        self.toast("Waiting list paused (running downloads keep going).")

    def _set_queued(self, task_id, flag):
        t = self.tasks.get(task_id)
        if t is None or t.get("status") == "Complete":
            return
        t["queued"] = flag
        if self.tree.exists(task_id):
            self.tree.set(task_id, "q", "\u25cf" if flag else "")
        self.save_task_state()
        if flag and not self.queue_running:
            self.toast("Added to the waiting list - click 'Run Waiting List' to start it.")

    def _tick(self):
        try:
            if self.queue_running:
                running = sum(1 for t in self.tasks.values() if t.get("running"))
                limit = max(1, int(get_setting("max_parallel")))
                pending = [tid for tid, t in self.tasks.items()
                           if t.get("queued") and not t.get("running") and t.get("status") in ("Queued", "Paused")]
                for tid in pending:
                    if running >= limit:
                        break
                    if self.start_task(tid, interactive=False):
                        running += 1
                if not pending and not running:
                    self.queue_running = False
                    self.toast("Waiting list finished.")
            self._update_statusbar()
            self._update_nav_counts()
        except Exception:
            log_error("_tick")
        finally:
            try:
                self.after(1000, self._tick)
            except Exception:
                pass

    # ------------------------------------------------------------ toolbar actions
    def on_stop_task(self):
        for item in self.tree.selection():
            self.pause_task(item)

    def on_resume_task(self):
        for item in self.tree.selection():
            self.resume_task(item)

    def on_delete_task(self):
        items = [i for i in self.tree.selection() if i in self.tasks]
        if not items:
            return
        if not messagebox.askyesno("Delete", f"Remove {len(items)} item(s) from the list and delete their partial data?\n"
                                             "(Finished files already saved on disk are NOT deleted.)"):
            return
        for item in items:
            self.remove_task(item)

    def on_double_click_task(self, event):
        item = self._first_selected()
        if item is None or item not in self.tasks:
            return
        t = self.tasks[item]
        action = get_setting("double_click")
        if action == "open" and t.get("status") == "Complete":
            open_path(t["dest"])
            return
        if action == "folder":
            open_path(Path(t["dest"]).parent)
            return
        win = self._win(t)
        if win is not None:
            win.lift()
            return
        t["active_win"] = ActiveDownloadWindow(self, t, app_ref=self, task_id=item)

    # ------------------------------------------------------------ right-click menu (like IDM)
    def _ctx_menu(self, iid):
        t = self.tasks[iid]
        done = t.get("status") == "Complete"
        running = bool(t.get("running"))
        exists = Path(t["dest"]).exists()
        theme = DARK_THEME
        style = dict(bg=theme["card_bg"], fg=theme["fg"], activebackground=theme["accent"],
                     activeforeground="#ffffff", disabledforeground="#777777")
        m = tk.Menu(self, tearoff=0, **style)

        def st(flag):
            return "normal" if flag else "disabled"

        if not done:
            m.add_command(label="Show progress details", command=lambda: self._show_details(iid))
            m.add_separator()
        m.add_command(label="Open file", state=st(done and exists), command=lambda: open_path(t["dest"]))
        m.add_command(label="Open with another app...", state=st(done and exists and os.name == "nt"), command=lambda: self._open_with(t))
        m.add_command(label="Show in folder", command=lambda: self._open_folder(t))
        m.add_separator()
        m.add_command(label="Rename or move... (Ctrl+M)", command=lambda: self._ctx_rename(iid))
        m.add_separator()
        m.add_command(label="Download again", state=st(not running), command=lambda: self._ctx_redownload(iid))
        m.add_separator()
        m.add_command(label="Continue download", state=st(not done and not running), command=lambda: self.resume_task(iid))
        m.add_command(label="Pause download", state=st(running), command=lambda: self.pause_task(iid))
        m.add_separator()
        m.add_command(label="Replace expired link...", state=st(not done), command=lambda: self.prompt_new_link(iid))
        m.add_separator()
        m.add_command(label="Remove from list...", command=lambda: self._ctx_remove(iid))
        m.add_separator()
        qm = tk.Menu(m, tearoff=0, **style)
        qm.add_command(label="Waiting list", command=lambda: self._set_queued(iid, True))
        m.add_cascade(label="Add to waiting list", menu=qm, state=st(not done))
        m.add_command(label="Take off waiting list", state=st(t.get("queued")), command=lambda: self._set_queued(iid, False))
        m.add_separator()
        dm_ = tk.Menu(m, tearoff=0, **style)
        m._dbl_var = tk.StringVar(value=get_setting("double_click"))
        for key, label in (("open", "Opens the file"), ("folder", "Shows the folder"), ("details", "Shows progress details")):
            dm_.add_radiobutton(label=label, value=key, variable=m._dbl_var, command=lambda k=key: self._set_double_click(k))
        m.add_cascade(label="Double-click does", menu=dm_)
        m.add_separator()
        m.add_command(label="Details", command=lambda: PropertiesWindow(self, t))
        return m

    def _show_details(self, iid):
        t = self.tasks.get(iid)
        if t is None:
            return
        win = self._win(t)
        if win is not None:
            win.lift()
            return
        t["active_win"] = ActiveDownloadWindow(self, t, app_ref=self, task_id=iid)

    def _set_double_click(self, key):
        SETTINGS["double_click"] = key
        save_settings()

    def _open_with(self, t):
        try:
            subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(t["dest"])])
        except Exception:
            pass

    def _open_folder(self, t):
        path = Path(t["dest"])
        try:
            if os.name == "nt" and path.exists():
                subprocess.Popen(["explorer", f"/select,{path}"])
                return
        except Exception:
            pass
        open_path(path.parent)

    def _ctx_rename(self, iid):
        t = self.tasks.get(iid) if iid else None
        if t is None:
            return
        if t.get("running"):
            messagebox.showinfo("Move/Rename", "Stop the download first.")
            return
        new = filedialog.asksaveasfilename(parent=self, title="Move/Rename", initialdir=str(Path(t["dest"]).parent),
                                           initialfile=t["filename"])
        if not new:
            return
        new = Path(norm_path(new))
        if t.get("status") == "Complete":
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(t["dest"]), str(new))
            except Exception as e:
                messagebox.showerror("Move/Rename", f"Could not move the file:\n{e}")
                return
        t["dest"], t["filename"] = str(new), new.name
        if self.tree.exists(iid):
            self.tree.set(iid, "file_name", new.name)
        self.save_task_state()

    def _ctx_redownload(self, iid):
        t = self.tasks.get(iid)
        if t is None or t.get("running"):
            return
        if not messagebox.askyesno("Download again", f"Download {t['filename']} again from the beginning?"):
            return
        shutil.rmtree(cache_path(t), ignore_errors=True)
        t.update(status="Queued", downloaded=0, ranges=None, ranges_total=0, etag="", overwrite=True, plan=None)
        self.set_status(iid, "Queued")
        self.start_task(iid)

    def _ctx_remove(self, iid):
        t = self.tasks.get(iid)
        if t is None:
            return
        if t.get("status") == "Complete":
            answer = messagebox.askyesnocancel("Remove", f"Remove {t['filename']} from the list?\n\n"
                                                         "Yes = also delete the file from disk\nNo = remove from the list only")
            if answer is None:
                return
            self.remove_task(iid, delete_file=bool(answer))
        else:
            if messagebox.askyesno("Remove", f"Remove {t['filename']} and its partial data?"):
                self.remove_task(iid)

    # ------------------------------------------------------------ events from worker threads
    def _poll_events(self):
        try:
            for _ in range(200):  # bounded batch keeps the window responsive
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_event(kind, payload)
                    if kind in ("task_paused", "task_error", "run_finished"):
                        self.apply_category_filter()
                except Exception:
                    log_error(f"event {kind}")
        finally:
            try:
                self.after(100, self._poll_events)
            except Exception:
                pass

    def _handle_event(self, kind, payload):
        if kind == "server_ok":
            self.toast("Listening for browser links on 127.0.0.1:18123", 10)
        elif kind == "ext_link":
            self.toast("Link received from the browser: " + payload["url"][:80], 10)
            self.handle_incoming_url(payload)
            self.lift()
            self.focus_force()
        elif kind == "incoming_ready":
            self._incoming_ready(*payload)
        elif kind == "server_error":
            messagebox.showwarning("Browser capture unavailable",
                                   f"Could not start the local link receiver on 127.0.0.1:18123 ({payload}).\n"
                                   "Another copy of Renkit may already be running. Links sent from your "
                                   "browser will not reach this window.")
        elif kind == "run_info":
            task_id, text = payload
            t = self.tasks.get(task_id)
            win = self._win(t) if t else None
            if win is not None:
                try:
                    win.lbl_refs["Can resume:"].configure(text=text)
                except Exception:
                    pass
        elif kind == "rename_task":
            task_id, real_name = payload
            t = self.tasks.get(task_id)
            if t is None:
                return
            if self.tree.exists(task_id):
                self.tree.set(task_id, "file_name", real_name)
                self.tree.set(task_id, "type", real_name.split(".")[-1].upper() + " File" if "." in real_name else "File")
            win = self._win(t)
            if win is not None:
                win.title(f"0% {real_name}")
        elif kind == "thread_tick":
            t = self.tasks.get(payload)
            win = self._win(t) if t else None
            if win is not None:
                for idx, (sz, st) in list(t.get("thread_progress", {}).items()):
                    try:
                        win.tree.set(str(idx), "downloaded", format_bytes(sz))
                        win.tree.set(str(idx), "info", st)
                    except Exception:
                        pass
        elif kind == "update_task":
            task_id, pct, speed_str, eta_str, total_dl, total_size, _speed = payload
            t = self.tasks.get(task_id)
            if t is None or t["cancel"].is_set() or not t.get("running"):
                return  # stale update from a run that was paused/stopped
            self.set_status(task_id, f"Downloading {pct}")
            if self.tree.exists(task_id):
                self.tree.set(task_id, "transfer_rate", speed_str)
                left_pct = max(0, 100 - safe_int(str(pct).rstrip("%")))
                t["remaining_text"] = f"{eta_str}  ({left_pct}% left)"
                self.tree.set(task_id, "time_left", t["remaining_text"])
                if total_size:
                    self.tree.set(task_id, "size", format_bytes(total_size))
            win = self._win(t)
            if win is not None:
                try:
                    win.title(f"{pct} {t['filename']}")
                    win.lbl_refs["Status:"].configure(text="Receiving data...")
                    win.lbl_refs["Total size:"].configure(text=format_bytes(total_size) if total_size else "Unknown")
                    win.lbl_refs["Received:"].configure(text=f"{format_bytes(total_dl)} / {format_bytes(total_size)} ( {pct} )")
                    win.lbl_refs["Speed:"].configure(text=speed_str)
                    win.lbl_refs["Remaining:"].configure(text=eta_str)
                    win.lbl_refs["Link:"].configure(text=expiry_text(t["url"]) or "no expiry detected")
                    win.prog_bar["value"] = int(total_dl * 100 / total_size) if total_size else 0
                except Exception:
                    pass
        elif kind in ("task_stitching", "task_verifying"):
            t = self.tasks.get(payload)
            if t is None:
                return
            text = "Stitching parts..." if kind == "task_stitching" else "Checking file..."
            self.set_status(payload, text)
            win = self._win(t)
            if win is not None:
                try:
                    win.lbl_refs["Status:"].configure(text=text)
                    win.prog_bar["value"] = 0
                except Exception:
                    pass
        elif kind == "update_stitch_progress":
            task_id, stitch_pct = payload
            t = self.tasks.get(task_id)
            win = self._win(t) if t else None
            if win is not None:
                try:
                    win.title(f"Stitching {stitch_pct}% {t['filename']}")
                    win.lbl_refs["Status:"].configure(text=f"Stitching parts ({stitch_pct}%)...")
                    win.prog_bar["value"] = stitch_pct
                except Exception:
                    pass
        elif kind == "task_verified":
            task_id, ok, msg = payload
            t = self.tasks.get(task_id)
            if t is not None:
                t["verify"] = (ok, msg)
        elif kind == "task_paused":
            t = self.tasks.get(payload)
            if t is None:
                return
            self.set_status(payload, "Paused")
            win = self._win(t)
            if win is not None:
                try:
                    win.lbl_refs["Status:"].configure(text="Paused")
                except Exception:
                    pass
            self.save_task_state()
        elif kind == "task_done":
            t = self.tasks.get(payload)
            if t is None:
                return
            self.set_status(payload, "Complete")
            t["queued"] = False
            t["remaining_text"] = ""
            if self.tree.exists(payload):
                self.tree.set(payload, "time_left", "")
                self.tree.set(payload, "transfer_rate", "")
                self.tree.set(payload, "q", "")
            win = self._win(t)
            if win is not None:
                try:
                    win.destroy()
                except Exception:
                    pass
            verify = t.pop("verify", None)
            if verify and not verify[0]:
                t["description"] = "File check failed"
                if self.tree.exists(payload):
                    self.tree.set(payload, "description", t["description"])
                messagebox.showwarning("File check", f"{t['filename']} finished downloading, but:\n\n{verify[1]}")
            self.save_task_state()
            self.apply_category_filter()
            self.toast(f"Finished: {t['filename']}")
            self.bell()
            opts = t.get("options", {})
            others_running = any(o.get("running") for tid, o in self.tasks.items() if tid != payload)
            if opts.get("exit_app") and not others_running:
                self.destroy()
                return
            if opts.get("show_dialog", True) and get_setting("show_complete_dialog"):
                DownloadCompleteDialog(self, t["dest"])
            if opts.get("shutdown") and not others_running:
                try:
                    if os.name == "nt":
                        subprocess.Popen(["shutdown", "/s", "/t", "60", "/c",
                                          "Renkit finished downloading. Run 'shutdown /a' to cancel."])
                    else:
                        subprocess.Popen(["shutdown", "-h", "+1", "Renkit finished downloading. Run 'shutdown -c' to cancel."])
                except Exception:
                    log_error("shutdown")
        elif kind == "task_error":
            task_id, err, flavor = payload
            t = self.tasks.get(task_id)
            if t is None:
                return
            self.set_status(task_id, "Error")
            win = self._win(t)
            if win is not None:
                try:
                    win.lbl_refs["Status:"].configure(text="Error - see message")
                except Exception:
                    pass
            self.save_task_state()
            if flavor == "link":  # expired link: offer to continue with a fresh one, like IDM's "refresh address"
                self.after(50, lambda: self.prompt_new_link(task_id, err))
            else:
                messagebox.showerror("Download problem", f"{t['filename']}\n\n{err}")
        elif kind == "run_finished":
            t = self.tasks.get(payload)
            if t is not None:
                t["running"] = False
