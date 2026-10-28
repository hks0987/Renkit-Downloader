A free, open-source download manager for **Windows and Linux**, with a clean card-based interface in
**dark and light** themes. It downloads with several connections, resumes after interruptions, and copes with
links that expire.

## Why I made this
Many download links are temporary and expire after a few hours. When a big download stops and its link has
expired, most programs just fail and everything already downloaded is wasted. Renkit lets you paste a **fresh link
for the same file** and continues where it stopped.

## Features
- Multi-connection downloads, pause/resume, waiting list (queue), speed limit, proxy support
- **Expired-link handling**: asks for a new link and carries on (right-click -> *Replace expired link...*)
- **Remaining** shows the time left *and* the % left, and keeps the last value for paused downloads
- Cards with a live progress bar, one-click Pause / Resume / Open / Retry, and a detailed progress window
- Sidebar views (Everything, file types, Active, Waiting, Needs attention, Finished) and instant search
- **Sort** by date added, name, size, status, progress or last activity (ascending or descending, remembered)
- Right-click menu: *Show progress details*, open, show in folder, rename/move, download again, remove
- **Light and dark themes** plus three accent colours (Settings -> Appearance), or follow your system
- Browser extension (Chrome / Edge): sends downloads to Renkit, copies the link to your clipboard as a backup,
  passes referer and cookies for sites that need them
- Smart duplicate handling (finished file -> tells you; unfinished -> resumes it with the new link)
- Checks ZIP files after download and names any damaged files inside
- Press **Ctrl+V** with a link copied to add it instantly

## Install and run

### Windows
1. Install Python 3.8+ from https://www.python.org/downloads/ (tick **Add Python to PATH**).
2. Download this project (**Code -> Download ZIP**) and extract it.
3. **Double-click `Renkit.pyw`** to start it (no console window).
4. Optional: double-click **`Install shortcut.bat`** once. It puts a Renkit icon on your Desktop and in the Start menu.

### Linux (Debian/Ubuntu)
```
sudo apt install python3 python3-tk git
git clone gh repo clone hks0987/Renkit-Downloader
cd renkit
python3 renkit.py
python3 install_shortcut.py     # optional: adds Renkit to your applications menu and Desktop
```
Files open with `xdg-open`. Settings are stored in `~/.config/renkit`. No other packages are needed.

### Browser extension (optional but recommended)
1. Open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**.
2. **Load unpacked** and choose the `extension` folder.
3. Keep Renkit running. If it isn't running, your browser downloads normally.

**Links not arriving?** Open http://127.0.0.1:18123/ping in your browser; it should show `{"ok": true ...}`.
Another download manager's browser extension may grab downloads first, so turn it off or right-click a link -> *Send Link to Renkit*.

## Antivirus warnings on .exe / .msi downloads
Windows Security sometimes flags unfinished installer pieces from *any* new, unsigned program. Renkit keeps
unfinished parts in a hidden `.renkit` folder next to your file (like a browser does). If a piece is still blocked,
Renkit tells you, and **Resume** fetches it again. If you trust the source, you can add the `.renkit` folder to
Windows Security -> Virus & threat protection -> Exclusions. To check a file is genuine, right-click the finished
file -> Properties -> Digital Signatures.

## Privacy and safety
- Everything runs on your computer. Renkit listens only on `127.0.0.1:18123` and only accepts requests from your browser extension.
- The extension asks for access to all sites because reading the cookies a download needs requires it. Cookies stay in memory and are not saved to disk.
- Only download files you have the right to download.
- no Data is collected.

## Status
Early release. Automated tests run on Linux against a simulated server. Windows is the main platform in daily use.
**Bug reports are very welcome.**

## Roadmap
- Firefox extension, drag-and-drop box, translations
- Single-file / installer download so Python isn't needed
- Better UI/UX.

## Support the project
I'm building this in my free time and want to keep improving it for Windows and Linux.
- **Star** the repo and share it
- **Report bugs** and ideas in *Issues*
- **Send a pull request** (code, translations, docs)
- **Donate:** [I'll put up my links here.didn't setup those yet.]

## Contributing
Open an issue first for big changes. Files: `renkit.py` (start), `app.py` (main window + engine), `ui.py` (cards and widgets),
`theme.py` (colours/fonts), `common.py` (settings, network), `dialogs.py`, `windows.py`, `server.py`, `extension/`, `assets/`.

## License
Copyright (c) 2026 hks0987
All rights reserved.

Made by [hks0987].
