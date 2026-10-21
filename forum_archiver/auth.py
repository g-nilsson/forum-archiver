"""Getting a Forum session without copying cookies by hand.

In order of preference:
  1. a session saved by a previous run,
  2. a login window: a Chromium-based browser (Chrome, Edge, Brave, ...) opens with its own profile,
     you sign in to Forum as usual, and the session cookie is read over the DevTools protocol,
  3. cookies read from a browser you are already logged in with (Firefox, or Safari/Chrome via yt-dlp).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LOGIN_URL = "https://forum.minerva.edu/app/"


class LoginError(Exception):
    pass


# --------------------------------------------------------------------------- saved session

def app_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "forum-archiver"


def session_file() -> Path:
    return app_dir() / "session.json"


def load_session():
    try:
        return json.loads(session_file().read_text(encoding="utf-8"))["cookies"]
    except (OSError, ValueError, KeyError):
        return None


def save_session(cookies):
    path = session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cookies": cookies}),
                    encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def logout():
    """Forget the saved session and the login window's browser profile."""
    session_file().unlink(missing_ok=True)
    shutil.rmtree(app_dir() / "browser-profile", ignore_errors=True)


def parse_cookie_header(header):
    cookies = []
    for part in header.split(";"):
        if "=" in part:
            name, value = part.strip().split("=", 1)
            cookies.append({"name": name, "value": value, "domain": "forum.minerva.edu"})
    return cookies


def _minerva(domain):
    return domain.lstrip(".").endswith("minerva.edu")


# --------------------------------------------------------------------------- login window

def find_chromium():
    """Path of an installed Chromium-based browser, or None."""
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi", "Opera"):
            for root in (Path("/Applications"), Path.home() / "Applications"):
                exe = root / f"{app}.app" / "Contents" / "MacOS" / app
                if exe.exists():
                    return str(exe)
        return None
    if os.name == "nt":
        rels = (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe")
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            for rel in rels:
                if base and (Path(base) / rel).exists():
                    return str(Path(base) / rel)
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                 "microsoft-edge-stable", "brave-browser", "brave", "brave-origin", "vivaldi"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


class DevTools:
    """Just enough of a WebSocket client to send Chrome DevTools Protocol commands (stdlib only)."""

    def __init__(self, port, path):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self._fill()
        head, _, self.buf = self.buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise LoginError("browser refused the DevTools connection")
        self.last_id = 0

    def _fill(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("browser closed")
        self.buf += chunk

    def _take(self, n):
        while len(self.buf) < n:
            self._fill()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, payload: bytes, opcode=0x1):
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 1 << 16:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        mask = os.urandom(4)  # clients must mask their frames
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _receive(self):
        message = b""
        while True:
            b1, b2 = self._take(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._take(8))[0]
            mask = self._take(4) if b2 & 0x80 else None
            payload = self._take(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            opcode = b1 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("browser closed")
            if opcode == 0x9:
                self._send(payload, 0xA)
                continue
            if opcode == 0xA:
                continue
            message += payload
            if b1 & 0x80:
                return json.loads(message)

    def call(self, method, **params):
        self.last_id += 1
        self._send(json.dumps({"id": self.last_id, "method": method, "params": params}).encode())
        while True:
            msg = self._receive()
            if msg.get("id") == self.last_id:
                if "error" in msg:
                    raise LoginError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def login_with_browser(is_valid, exe=None, timeout=900):
    """Open a browser window on the Forum login page and wait until the user has signed in.

    The window uses a separate profile kept in app_dir(), so Google remembers you next time, and
    your everyday browser profile is never touched. Returns the Forum cookies.
    """
    exe = exe or find_chromium()
    if not exe:
        raise LoginError("no Chrome, Edge, Brave or Chromium found for the login window")
    profile = app_dir() / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    port_file = profile / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)

    proc = subprocess.Popen(
        [exe, f"--user-data-dir={profile}", "--remote-debugging-port=0", "--no-first-run",
         "--no-default-browser-check", "--new-window", LOGIN_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    devtools = None
    try:
        for _ in range(60):
            if port_file.exists() and len(port_file.read_text().split()) >= 2:
                break
            if proc.poll() is not None:
                raise LoginError("the login browser exited right away (is an earlier login window still open?)")
            time.sleep(0.5)
        else:
            raise LoginError("the login browser did not start")
        port, path = port_file.read_text().split()[:2]
        devtools = DevTools(int(port), path)

        print(f"\nA {Path(exe).stem} window opened on the Forum login page.\n"
              "Sign in there as usual (e.g. with Google). This continues by itself once you're in.",
              file=sys.stderr, flush=True)
        deadline, last_sid, last_check = time.time() + timeout, None, 0.0
        while time.time() < deadline:
            raw = devtools.call("Storage.getCookies").get("cookies", [])
            cookies = [{"name": c["name"], "value": c["value"], "domain": c["domain"]}
                       for c in raw if _minerva(c.get("domain", ""))]
            sid = next((c["value"] for c in cookies if c["name"] == "sessionid"), None)
            if sid and (sid != last_sid or time.time() - last_check > 10):
                last_sid, last_check = sid, time.time()
                if is_valid(cookies):
                    return cookies
            time.sleep(1.5)
        raise LoginError("timed out waiting for the login")
    except ConnectionError:
        raise LoginError("the login window was closed before signing in")
    finally:
        if devtools:
            try:
                devtools.call("Browser.close")
            except (LoginError, OSError, ConnectionError):
                pass
            devtools.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()


# --------------------------------------------------------------------------- cookies from an everyday browser

FIREFOX_ROOTS = [
    "~/.mozilla/firefox",
    "~/.config/mozilla/firefox",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    "~/snap/firefox/common/.mozilla/firefox",
    "~/Library/Application Support/Firefox/Profiles",
    "$APPDATA/Mozilla/Firefox/Profiles",
]


def _read_firefox_db(db: Path):
    # Firefox locks the database and keeps recent writes in the -wal file, so read a copy of both.
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ("", "-wal"):
            src = Path(f"{db}{suffix}")
            if src.exists():
                shutil.copyfile(src, Path(tmp) / f"cookies.sqlite{suffix}")
        con = sqlite3.connect(Path(tmp) / "cookies.sqlite")
        try:
            return con.execute("SELECT name, value, host, lastAccessed FROM moz_cookies "
                               "WHERE host LIKE '%minerva.edu'").fetchall()
        except sqlite3.Error:
            return []
        finally:
            con.close()


def firefox_cookies():
    """Cookies from the Firefox profile with the most recently used Forum session."""
    best, best_seen = [], -1
    for root in FIREFOX_ROOTS:
        for db in Path(os.path.expandvars(os.path.expanduser(root))).glob("*/cookies.sqlite"):
            rows = _read_firefox_db(db)
            seen = max((r[3] for r in rows if r[0] == "sessionid"), default=-1)
            if seen > best_seen:
                best, best_seen = rows, seen
    return [{"name": n, "value": v, "domain": h} for n, v, h, _ in best]


def browser_cookies(browser):
    """Forum cookies from a browser you're logged in with. Safari and Chromium browsers need yt-dlp."""
    if browser == "firefox":
        return firefox_cookies()
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except ImportError:
        raise LoginError(f"reading {browser} cookies needs yt-dlp (pip install yt-dlp)")
    try:
        jar = extract_cookies_from_browser(browser)
    except Exception as e:  # yt-dlp raises many kinds; on macOS Safari usually needs Full Disk Access
        hint = (" On macOS, give your terminal Full Disk Access (System Settings > Privacy & Security)."
                if browser == "safari" else "")
        raise LoginError(f"could not read {browser} cookies: {e}.{hint}")
    return [{"name": c.name, "value": c.value, "domain": c.domain} for c in jar if _minerva(c.domain)]
