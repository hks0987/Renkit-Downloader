"""Shared building blocks: folders, settings (remembered), network helpers (proxy/referer/cookies),
link expiry, IDM log reading, merging, file checks, window theme."""
try:
    from theme import THEME as DARK_THEME, apply_theme as apply_dark_theme, set_mode
except ImportError:  # tkinter is missing: the friendly message in renkit.py explains it
    DARK_THEME = {}

    def apply_dark_theme(win):
        pass

    def set_mode(*args, **kwargs):
        return "dark"
import os
import re
import sys
import time
import json
import queue
import shutil
import copy
import ctypes
import base64
import zipfile
import datetime
import hashlib
import getpass
import traceback
import tempfile
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path, PureWindowsPath

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False

_Toplevel = tk.Toplevel if _TKINTER_AVAILABLE else object
_Tk = tk.Tk if _TKINTER_AVAILABLE else object


BUFFER_SIZE = 256 * 1024  # 256 KB buffer
PARALLEL_THREADS = 4      # Concurrent connections per download
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ResumeFetch/8.2"

if os.name == "nt":
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ResumeFetch"   # kept so existing settings carry over
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "renkit"
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = CONFIG_DIR / "Cache"
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    CACHE_DIR = Path(tempfile.gettempdir()) / "ResumeFetch_Cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def center_window(win, width, height):
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = (sw - width) // 2
    y = (sh - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


class RepairError(Exception):
    pass


def downloads_folder():
    userprofile = os.environ.get("USERPROFILE")
    if userprofile and (Path(userprofile) / "Downloads").exists():
        return Path(userprofile) / "Downloads"
    return Path.home() / "Downloads"


MERGE_BLOCK = 4 * 1024 * 1024
FATAL_HTTP = (400, 401, 403, 404, 410, 416)
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def log_error(context=""):
    """Append the current exception to ResumeFetch/error.log (in your AppData folder). Never raises."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = CONFIG_DIR / "error.log"
        if log_file.exists() and log_file.stat().st_size > 1_000_000:
            os.replace(log_file, CONFIG_DIR / "error.old.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {context}\n{traceback.format_exc()}")
    except Exception:
        pass


def lower_headers(headers):
    """HTTP header names are case-insensitive (Cloudflare/HTTP2 send lowercase) - normalise them."""
    try:
        return {str(k).lower(): v for k, v in dict(headers).items()}
    except Exception:
        return {}


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def check_url(url):
    """Only plain http(s) links are allowed (blocks file:// and ftp://)."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise RepairError("That is not a valid http(s) download link.")
    return url


def safe_grab(win):
    """grab_set() right after creating a window can fail ('window not viewable'); retry shortly."""
    def _grab():
        try:
            win.grab_set()
        except Exception:
            pass
    try:
        win.after(60, _grab)
    except Exception:
        pass


def http_error_message(code):
    if code in (401, 403, 410):
        return (f"The website rejected the link (error {code}). It has most likely expired - "
                "generate a brand new link and use that.")
    if code == 404:
        return "The link points to a file that no longer exists (error 404)."
    if code == 416:
        return "The server says that part of the file does not exist - the link is probably for a different or smaller file."
    return f"The server answered with error {code}."


def check_free_space(folder, needed):
    try:
        probe = Path(folder)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
    except Exception:
        return
    if needed > 0 and free < needed:
        raise RepairError(f"Not enough free disk space for {folder}: need about {format_bytes(needed)}, "
                          f"only {format_bytes(free)} free.")


class RateLimiter:
    """One shared speed limit for all connections of a download."""
    def __init__(self, get_limit):
        self.get_limit = get_limit
        self.lock = threading.Lock()
        self.next_time = time.time()

    def wait(self, nbytes):
        limit = self.get_limit()
        if not limit or limit <= 0:
            return
        with self.lock:
            now = time.time()
            start = max(now, self.next_time)
            self.next_time = start + nbytes / limit
            delay = start - now
        if delay > 0:
            time.sleep(delay)


def task_id_for(dest):
    return hashlib.sha1(str(dest).lower().encode("utf-8", "ignore")).hexdigest()[:10]


def normalize_status(status):
    status = str(status or "Paused")
    return status if status in ("Complete", "Queued") else "Paused"


def new_task(filename, size, url, dest, category="General", description="", status="Queued",
             etag="", last_try="", cache_key=None):
    return {
        "filename": filename, "size": size, "downloaded": 0, "status": status,
        "url": url, "dest": str(dest), "category": category, "description": description,
        "cancel": threading.Event(), "thread_progress": {}, "speed_limit": 0,
        "options": {"show_dialog": True, "exit_app": False, "shutdown": False},
        "etag": etag, "last_try": last_try, "running": False,
        "cache_key": cache_key or task_id_for(dest),
        "hdrs": {}, "plan": None, "overwrite": False, "queued": False, "speed": 0.0,
        "ranges": None, "ranges_total": 0, "cache_root": "", "md5": "", "added": 0.0,
    }


def cache_path(t):
    return Path(t.get("cache_root") or CACHE_DIR) / ("dl_" + t["cache_key"])


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip(" .")
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = "_" + name
    if len(name) > 150:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:140] + dot + ext[:9]) if dot and len(ext) <= 9 else name[:150]
    return name or "repaired_file"


def _filename_from_disposition(value):
    if not value:
        return None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;\r\n]+)", value, re.IGNORECASE)
    if m:
        raw = m.group(2).strip().strip('"')
        try:
            return urllib.parse.unquote(raw, encoding=(m.group(1) or "utf-8"))
        except (LookupError, ValueError):
            return urllib.parse.unquote(raw)
    m = re.search(r'filename\s*=\s*"((?:[^"\\]|\\.)*)"', value, re.IGNORECASE)
    if m:
        return m.group(1).replace('\\"', '"')
    m = re.search(r"filename\s*=\s*([^;\r\n]+)", value, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def extract_filename_from_headers(headers, url):
    headers = lower_headers(headers)
    name = _filename_from_disposition(headers.get("content-disposition", ""))
    if name:
        name = sanitize_filename(name)
        if name != "repaired_file":
            return name
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        value = (qs.get("response-content-disposition") or [""])[0]
        name = _filename_from_disposition(value)
        if not name and value and "=" not in value and ";" not in value and "." in value:
            name = value  # some links carry just the bare file name in this parameter
        if name:
            return sanitize_filename(name)
        path_name = Path(urllib.parse.unquote(parsed.path)).name
        if path_name:
            return sanitize_filename(path_name)
    except Exception:
        pass
    return "downloaded_file"


def extract_filename_from_url(url):
    return extract_filename_from_headers({}, url)


class LinkRejected(RepairError):
    """The website refused the link (usually because it expired)."""


def http_error(code):
    msg = http_error_message(code)
    return LinkRejected(msg) if code in (401, 403, 410) else RepairError(msg)


# ---------------------------------------------------------------- settings (remembered between runs)
SETTINGS_FILE = CONFIG_DIR / "settings.json"
DEFAULT_FILE_TYPES = ("3GP 7Z AAC ACE AIF APK ARJ ASF AVI BIN BZ2 EXE GZ GZIP IMG ISO LZH M4A M4V MKV MOV MP3 MP4 "
                      "MPA MPE MPEG MPG MSI MSU OGG OGV PDF PLJ PPS PPT QT R0* R1* RA RAR RM RMVB SEA SIT SITX TAR "
                      "TIF TIFF WAV WMA WMV Z ZIP")
DEFAULT_EXCLUDE_SITES = "*.update.microsoft.com download.windowsupdate.com siteseal.thawte.com ecom.cimetz.com *.voice2page.com"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
CATEGORIES = ("Compressed", "Documents", "Music", "Programs", "Video", "General")
CATEGORY_EXTS = {
    "Compressed": "7z ace arj bz2 gz gzip lzh rar sea sit sitx tar z zip r0 r1",
    "Documents": "pdf doc docx xls xlsx ppt pptx pps txt rtf epub",
    "Music": "aac aif m4a mp3 mpa ogg ra wav wma flac",
    "Programs": "exe msi msu apk bin iso img",
    "Video": "3gp asf avi m4v mkv mov mp4 mpe mpeg mpg ogv qt rm rmvb wmv flv webm",
}
DUP_LABELS = {
    "ask": "Ask me what to do",
    "numbered": "Keep both - add a number to the new file's name",
    "overwrite": "Replace the existing file",
    "resume_or_complete": "Smart: finished file -> tell me; unfinished -> resume it",
}
UNIT_MAX = 64 * 1024 * 1024


def norm_path(p):
    return os.path.normpath(str(p)) if p else ""


def default_category_dirs():
    root = downloads_folder()
    return {c: str(root if c == "General" else root / c) for c in CATEGORIES}


DEFAULT_SETTINGS = {
    "show_start_dialog": True, "only_add_to_queue": False, "show_complete_dialog": True,
    "duplicate_policy": "resume_or_complete", "user_agent": DEFAULT_UA, "ignore_modification": False,
    "copy_link_to_clipboard": True, "verify_after_download": True, "idm_cleanup": "ask",
    "connections": 4, "speed_limit_kb": 0, "max_parallel": 2,
    "proxy_mode": "system", "proxy_url": "", "temp_dir": "", "theme": "dark", "accent": "teal", "sort_key": "added", "sort_desc": False,
    "category_dirs": default_category_dirs(), "remember_last_dir": True,
    "file_types": DEFAULT_FILE_TYPES, "exclude_sites": DEFAULT_EXCLUDE_SITES, "catch_all": False,
    "double_click": "details",
}
SETTINGS = copy.deepcopy(DEFAULT_SETTINGS)
_OPENER = None
_OPENER_LOCK = threading.Lock()


def get_setting(key):
    return SETTINGS.get(key, DEFAULT_SETTINGS.get(key))


def reset_opener():
    global _OPENER
    with _OPENER_LOCK:
        _OPENER = None


def load_settings():
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for key, value in saved.items():
            if key in merged:
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
    except FileNotFoundError:
        pass
    except Exception:
        log_error("load_settings")
    SETTINGS.clear()
    SETTINGS.update(merged)
    reset_opener()


def save_settings():
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        log_error("save_settings")


def category_for(filename):
    ext = Path(str(filename)).suffix.lower().lstrip(".")
    for cat, exts in CATEGORY_EXTS.items():
        if ext and ext in exts.split():
            return cat
    return "General"


def category_dir(cat):
    dirs = get_setting("category_dirs") or {}
    return Path(norm_path(dirs.get(cat) or dirs.get("General") or downloads_folder()))


def clipboard_url(widget):
    """A valid http(s) link currently on the clipboard, else ''."""
    try:
        parts = widget.clipboard_get().strip().split()
    except Exception:
        return ""
    if not parts:
        return ""
    try:
        check_url(parts[0])
        return parts[0]
    except RepairError:
        return ""


def hdrs_from_payload(payload):
    out = {}
    for key in ("referer", "user_agent", "cookie"):
        v = (payload or {}).get(key)
        if isinstance(v, str) and v.strip():
            out[key] = re.sub(r"[\r\n]", "", v.strip())
    return out


def link_expiry(url):
    """Best-effort expiry time (UTC) of a pre-signed link, or None."""
    try:
        q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        for date_key, exp_key in (("x-amz-date", "x-amz-expires"), ("x-goog-date", "x-goog-expires")):
            if date_key in q and exp_key in q:
                start = datetime.datetime.strptime(q[date_key], "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
                return start + datetime.timedelta(seconds=int(q[exp_key]))
        if q.get("expires", "").isdigit():
            return datetime.datetime.fromtimestamp(int(q["expires"]), tz=datetime.timezone.utc)
        if "se" in q:
            return datetime.datetime.fromisoformat(q["se"].replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def expiry_text(url):
    exp = link_expiry(url)
    if exp is None:
        return ""
    left = int((exp - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    if left <= 0:
        return "EXPIRED"
    hours, rem = divmod(left, 3600)
    return f"valid for {hours}h {rem // 60}m" if hours else f"valid for {rem // 60}m {rem % 60}s"


def plan_units(total, connections, plan=None):
    """Byte ranges to download: only the missing gaps (repair) or equal slices (normal)."""
    if plan:
        units = []
        for gap in plan["gaps"]:
            s = gap["start"]
            while s <= gap["end"]:
                e = min(s + UNIT_MAX - 1, gap["end"])
                units.append((s, e))
                s = e + 1
        return units
    n = connections if total >= connections * 256 * 1024 else 1
    seg = total // n
    return [(i * seg, total - 1 if i == n - 1 else (i + 1) * seg - 1) for i in range(n)]


def verify_file(path, md5_b64=None):
    """After merging: compare the server's MD5 (if given) and CRC-test ZIP files. Returns (ok, message)."""
    path = Path(path)
    problems = []
    if md5_b64:
        try:
            h = hashlib.md5()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
                    h.update(block)
            if base64.b64encode(h.digest()).decode() != md5_b64.strip():
                problems.append("The server's MD5 checksum does not match the file.")
        except Exception as e:
            problems.append(f"(MD5 check skipped: {e})")
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as z:
                bad = []
                for info in z.infolist():
                    try:
                        with z.open(info) as member:
                            while member.read(1024 * 1024):
                                pass
                    except Exception:
                        bad.append(info.filename)
            if bad:
                problems.append("These files inside the ZIP are damaged - download just those again: " + ", ".join(bad[:8]))
        except zipfile.BadZipFile as e:
            problems.append(f"This is not a valid ZIP file: {e}")
        except Exception as e:
            problems.append(f"(ZIP check skipped: {e})")
    return (not [p for p in problems if not p.startswith("(")]), " ".join(problems)


# ---------------------------------------------------------------- network (proxy, headers, referer, cookies)
def _build_opener():
    mode = get_setting("proxy_mode")
    if mode == "none":
        handlers = [urllib.request.ProxyHandler({})]
    elif mode == "manual" and str(get_setting("proxy_url")).strip():
        proxy = str(get_setting("proxy_url")).strip()
        if "://" not in proxy:
            proxy = "http://" + proxy
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]
    else:
        handlers = []  # system proxy settings
    return urllib.request.build_opener(*handlers)


def open_url(req, timeout=30):
    global _OPENER
    with _OPENER_LOCK:
        if _OPENER is None:
            _OPENER = _build_opener()
        opener = _OPENER
    return opener.open(req, timeout=timeout)


def make_request(url, start=None, end=None, extra=None):
    extra = extra or {}
    headers = {"User-Agent": extra.get("user_agent") or get_setting("user_agent") or USER_AGENT}
    if extra.get("referer"):
        headers["Referer"] = extra["referer"]
    if extra.get("cookie"):
        headers["Cookie"] = extra["cookie"]
    if start is not None:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"
    return urllib.request.Request(url, headers=headers)


def probe_url(url, timeout=15, extra=None):
    """Ask for 1 byte: learns size, Range support, name and ETag without downloading the file.
    (A ranged GET is used because pre-signed links often reject HEAD.)"""
    check_url(url)
    req = make_request(url, 0, 0, extra)
    try:
        with open_url(req, timeout) as resp:
            status, headers = resp.getcode(), lower_headers(resp.headers)
    except urllib.error.HTTPError as e:
        if e.code != 416:
            raise http_error(e.code)
        status, headers = 416, lower_headers(e.headers)
    except urllib.error.URLError as e:
        raise RepairError(f"Could not reach the server: {e.reason}")
    except (OSError, ValueError) as e:
        raise RepairError(f"Could not reach the server: {e}")

    total, ranged = 0, False
    if status == 206:
        m = re.match(r"bytes\s+\d+-\d+/(\d+)", headers.get("content-range", ""))
        total = int(m.group(1)) if m else 0
        ranged = total > 0
    elif status == 416:
        m = re.match(r"bytes\s+\*/(\d+)", headers.get("content-range", ""))
        total = int(m.group(1)) if m else 0
    else:
        total = safe_int(headers.get("content-length"))
    return {"total": total, "supports_range": ranged, "etag": headers.get("etag", ""),
            "md5": headers.get("content-md5", ""), "name": extract_filename_from_headers(headers, url)}


def fetch_range(url, start, end, dest_path, cancel, expected_total=0, limiter=None, on_progress=None,
                attempts=5, extra=None):
    """Download bytes start..end (inclusive) into dest_path, resuming a partial file.
    Returns True when the part is complete, False if cancelled.
    Raises RepairError for real problems (expired link, wrong file, no Range support)."""
    check_url(url)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    expected = end - start + 1
    last_error = "unknown error"

    for attempt in range(attempts):
        if cancel.is_set():
            return False
        already = dest_path.stat().st_size if dest_path.exists() else 0
        if already > expected:
            dest_path.unlink()
            already = 0
        if already == expected:
            return True

        resume_from = start + already
        req = make_request(url, resume_from, end, extra)
        try:
            with open_url(req, 30) as resp:
                if resp.getcode() != 206:
                    raise RepairError(
                        f"The server ignored the 'send me just this part' request (it answered {resp.getcode()} "
                        "instead of 206), so this link cannot be used to fetch a single part of the file.")
                headers = lower_headers(resp.headers)
                m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", headers.get("content-range", ""))
                if m:
                    if int(m.group(1)) != resume_from:
                        raise RepairError("The server sent a different part of the file than requested.")
                    if expected_total and m.group(3) != "*" and int(m.group(3)) != expected_total:
                        raise RepairError(
                            f"This link is for a different file: it is {format_bytes(int(m.group(3)))} but your "
                            f"download should be {format_bytes(expected_total)}. Make sure you copied the link "
                            "for the SAME file.")
                remaining = expected - already
                with open(dest_path, "ab" if already else "wb") as out:
                    while remaining > 0:
                        if cancel.is_set():
                            return False
                        block = resp.read(min(BUFFER_SIZE, remaining))
                        if not block:
                            break
                        out.write(block)
                        remaining -= len(block)
                        if on_progress:
                            on_progress(len(block))
                        if limiter:
                            limiter.wait(len(block))
        except RepairError:
            raise
        except urllib.error.HTTPError as e:
            if e.code in FATAL_HTTP:
                raise http_error(e.code)
            last_error = f"HTTP error {e.code}"
        except Exception as e:
            last_error = str(e) or e.__class__.__name__

        size = dest_path.stat().st_size if dest_path.exists() else 0
        if size == expected:
            return True
        if cancel.wait(min(2 * (attempt + 1), 8)):
            return False
    raise RepairError(f"Could not finish downloading this part after {attempts} tries ({last_error}).")


def stream_whole(url, dest_path, cancel, expected, limiter=None, on_progress=None, extra=None):
    """Plain single-connection download (no resume) for servers that do not support Range."""
    check_url(url)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = make_request(url, extra=extra)
    try:
        with open_url(req, 30) as resp, open(dest_path, "wb") as out:
            while True:
                if cancel.is_set():
                    return False
                block = resp.read(BUFFER_SIZE)
                if not block:
                    break
                out.write(block)
                if on_progress:
                    on_progress(len(block))
                if limiter:
                    limiter.wait(len(block))
    except urllib.error.HTTPError as e:
        raise http_error(e.code)
    except Exception as e:
        raise RepairError(f"Connection problem: {e}")
    size = dest_path.stat().st_size
    if expected and size != expected:
        raise RepairError(f"The connection closed early ({format_bytes(size)} of {format_bytes(expected)}). "
                          "This server does not support resuming, so the download has to start over.")
    return True


def format_bytes(bytes_val):
    if bytes_val >= 1024**3:
        return f"{bytes_val / 1024**3:.3f} GB"
    elif bytes_val >= 1024**2:
        return f"{bytes_val / 1024**2:.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{int(bytes_val)} B"


def format_time(seconds):
    if seconds < 0 or seconds > 86400:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def unique_destination(folder, filename):
    folder = Path(folder)
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while (folder / f"{stem} ({i}){suffix}").exists():
        i += 1
    return folder / f"{stem} ({i}){suffix}"


def merge_file_parts(piece_list, out_path, progress_cb=None, cancel_event=None, expected_total=None):
    """Join pieces into out_path. Items are (offset, path) or (offset, path, skip, length).
    Refuses to write a file with holes, overlaps or the wrong final size."""
    out_path = Path(out_path)
    parts = []
    for item in piece_list:
        offset, path = item[0], Path(item[1])
        skip = item[2] if len(item) > 2 else 0
        length = item[3] if len(item) > 3 else path.stat().st_size - skip
        parts.append((offset, path, skip, length))
    parts.sort(key=lambda p: p[0])

    pos = 0
    for offset, path, skip, length in parts:
        if offset != pos:
            raise RepairError(f"Cannot merge: the pieces leave a hole at byte {pos}.")
        check_part_readable(path)
        if path.stat().st_size < skip + length:
            raise RepairError(f"Piece {path.name} is smaller than expected, so the file would be incomplete.")
        pos += length
    total = pos
    if expected_total and total != expected_total:
        raise RepairError(f"Cannot merge: pieces add up to {total} bytes but the file should be {expected_total}.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    check_free_space(out_path.parent, total)
    tmp_out = out_path.with_name(out_path.name + ".part")
    done = 0
    try:
        with open(tmp_out, "wb") as out:
            for offset, path, skip, length in parts:
                with open(path, "rb") as f:
                    f.seek(skip)
                    remaining = length
                    while remaining > 0:
                        if cancel_event and cancel_event.is_set():
                            raise RepairError("Merge operation cancelled.")
                        block = f.read(min(MERGE_BLOCK, remaining))
                        if not block:
                            raise RepairError(f"Piece {path.name} ended early.")
                        out.write(block)
                        remaining -= len(block)
                        done += len(block)
                        if progress_cb:
                            progress_cb(done, total)
        if tmp_out.stat().st_size != total:
            raise RepairError("The merged file has the wrong size.")
        os.replace(tmp_out, out_path)
    except BaseException:
        try:
            if tmp_out.exists():
                tmp_out.unlink()
        except OSError:
            pass
        raise
    return total




def open_path(path):
    """Open a file or folder with the system's default app (Windows, macOS, Linux)."""
    try:
        if os.name == "nt":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False


def show_fatal_dialog(title, message):
    """Show a fatal error even if the main window never started."""
    try:
        if _TKINTER_AVAILABLE:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(title, message, parent=root)
            root.destroy()
            return
    except Exception:
        pass
    try:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)
            return
    except Exception:
        pass
    print(f"{title}: {message}", file=sys.stderr)


AV_HINT = ("Windows Security (or another antivirus) probably blocked or removed a piece of the download while it was being "
           "joined - this sometimes happens with .exe/.msi installers even when they are safe. Click Resume to fetch the "
           "missing piece again. If it keeps happening and you trust the source, add the hidden .renkit folder next to your "
           "download to Windows Security > Virus & threat protection > Exclusions.")


def check_part_readable(path):
    try:
        with open(path, "rb") as f:
            f.read(1)
    except OSError as e:
        raise RepairError(f"A downloaded piece ({Path(path).name}) can no longer be read ({e.strerror or e}). " + AV_HINT)


def explain_exception(e):
    if isinstance(e, OSError) and getattr(e, "errno", None) in (2, 5, 13, 22, 32):
        return f"A file operation failed ({e.strerror or e}). " + AV_HINT
    return f"Unexpected error: {e}"


def remove_cache_dir(path):
    shutil.rmtree(path, ignore_errors=True)
    parent = Path(path).parent
    if parent.name == ".renkit":
        try:
            parent.rmdir()
        except OSError:
            pass
