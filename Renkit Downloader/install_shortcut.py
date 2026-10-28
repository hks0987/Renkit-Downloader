"""Creates a Renkit shortcut: Desktop + Start menu on Windows, app-menu + Desktop entry on Linux."""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def windows():
    pyw = Path(sys.executable).with_name("pythonw.exe")
    target = pyw if pyw.exists() else Path(sys.executable)
    q = lambda p: str(p).replace("'", "''")
    ps = ("$ws = New-Object -ComObject WScript.Shell; "
          "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
          "$s = $ws.CreateShortcut((Join-Path $dir 'Renkit.lnk')); "
          f"$s.TargetPath = '{q(target)}'; $s.Arguments = '\"{q(HERE / 'Renkit.pyw')}\"'; "
          f"$s.WorkingDirectory = '{q(HERE)}'; $s.IconLocation = '{q(HERE / 'assets' / 'renkit.ico')}'; "
          "$s.Description = 'Renkit downloader'; $s.Save() }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print("Done. Look for 'Renkit' on your Desktop and in the Start menu.")


def linux():
    entry = ("[Desktop Entry]\nType=Application\nName=Renkit\nComment=Download manager\n"
             f"Exec=python3 \"{HERE / 'renkit.py'}\"\nPath={HERE}\nIcon={HERE / 'assets' / 'renkit_256.png'}\n"
             "Terminal=false\nCategories=Network;FileTransfer;\n")
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    targets = [apps / "renkit.desktop"]
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        targets.append(desktop / "Renkit.desktop")
    for path in targets:
        path.write_text(entry, encoding="utf-8")
        path.chmod(0o755)
    print("Done. Renkit is in your applications menu" + (" and on your Desktop." if len(targets) > 1 else "."))


if __name__ == "__main__":
    if os.name == "nt":
        windows()
    elif sys.platform == "darwin":
        print("Shortcuts are not set up for macOS yet. Run:  python3 renkit.py")
    else:
        linux()
