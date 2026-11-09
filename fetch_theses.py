#!/usr/bin/env python3
"""Fetch thesis topics from applications.e-ce.uth.gr into theses.json, connecting the UTH VPN when needed."""
import html
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path

SITE_HOST = "applications.e-ce.uth.gr"
BASE = f"https://{SITE_HOST}"
PAGE_URL = f"{BASE}/?page_id=4851"
LOGIN_URL = f"{BASE}/wp-login.php"
DATA_MARKER = "window.tablesomeTables = "
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) Gecko/20100101 Firefox/156.0"
HERE = Path(__file__).resolve().parent
JSON_PATH = HERE / "theses.json"
VPN_CONFIG = HERE / "uth.ovpn"
VPN_NAME = VPN_CONFIG.stem
COLUMNS = {
    "ΤΙΤΛΟΣ": "title",
    "ΠΕΡΙΓΡΑΦΗ": "description",
    "ΕΠΙΒΛΕΠΩΝ": "supervisor",
    "ΔΙΑΘΕΣΙΜΟ": "available",
    "ΗΜΕΡΟΜΗΝΙΑ": "date",
}
TRACKED_FIELDS = ("title", "supervisor", "date", "description")


class FetchError(Exception):
    pass


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def credentials():
    load_env(HERE / ".env")
    user, password = os.environ.get("UTH_USER"), os.environ.get("UTH_PASS")
    if not user or not password:
        raise FetchError("Set UTH_USER and UTH_PASS in .env")
    return user, password


def nmcli(*args):
    try:
        result = subprocess.run(["nmcli", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise FetchError("nmcli not found: install NetworkManager and networkmanager-openvpn")
    if result.returncode:
        raise FetchError(f"nmcli {' '.join(args[:3])} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def site_address():
    try:
        return socket.gethostbyname(SITE_HOST)
    except OSError as error:
        raise FetchError(f"Cannot resolve {SITE_HOST} ({error})")


def reachable(address):
    try:
        socket.create_connection((address, 443), timeout=3).close()
        return True
    except OSError:
        return False


@contextmanager
def vpn(user, password):
    address = site_address()
    if reachable(address):
        yield
        return
    if VPN_NAME not in nmcli("-g", "NAME", "connection", "show").splitlines():
        nmcli("connection", "import", "type", "openvpn", "file", str(VPN_CONFIG))
    # Split tunnel: only the applications site goes through the VPN, default route and DNS stay untouched
    nmcli(
        "connection", "modify", VPN_NAME,
        "connection.autoconnect", "no",
        "+vpn.data", f"username={user}",
        "+vpn.data", "password-flags=2",
        "ipv4.never-default", "yes",
        "ipv4.ignore-auto-routes", "yes",
        "ipv4.ignore-auto-dns", "yes",
        "ipv4.routes", f"{address}/32",
        "ipv6.method", "ignore",
    )
    # mkstemp creates the file 0600; the password never appears on a command line
    with tempfile.NamedTemporaryFile("w") as secrets:
        secrets.write(f"vpn.secrets.password:{password}\n")
        secrets.flush()
        nmcli("--wait", "60", "connection", "up", VPN_NAME, "passwd-file", secrets.name)
    try:
        yield
    finally:
        result = subprocess.run(["nmcli", "connection", "down", VPN_NAME], capture_output=True, text=True)
        if result.returncode:
            print(f"Warning: VPN '{VPN_NAME}' still up: {result.stderr.strip()}", file=sys.stderr)


def login_and_fetch(user, password):
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    form = urllib.parse.urlencode(
        {"log": user, "pwd": password, "wp-submit": "Log In", "redirect_to": PAGE_URL}
    ).encode()
    with opener.open(LOGIN_URL, form, timeout=60) as response:
        page = response.read().decode("utf-8")
    if not any(cookie.name.startswith("wordpress_logged_in_") for cookie in jar):
        raise FetchError("Login failed: check UTH_USER and UTH_PASS in .env")
    return page


def extract_table(page):
    start = page.find(DATA_MARKER)
    if start == -1:
        raise FetchError("Table data not found: page layout changed or not logged in")
    try:
        tables, _ = json.JSONDecoder().raw_decode(page, start + len(DATA_MARKER))
    except json.JSONDecodeError as error:
        raise FetchError(f"Table data is not valid JSON: {error}")
    return tables[0]


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.href = None

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n- " if tag == "li" else "\n")
        if tag == "a":
            self.href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.parts.append(f" ({self.href})")
            self.href = None

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(markup):
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def clean(value):
    return " ".join(html.unescape(value or "").split())


def parse_theses(table):
    field_by_column = {
        str(column["id"]): COLUMNS.get(column["name"].split()[0])
        for column in table["items"]["columns"]
    }
    missing = set(COLUMNS.values()) - set(field_by_column.values())
    if missing:
        raise FetchError(f"Columns missing from table: {sorted(missing)}")

    theses = []
    for row in table["items"]["rows"]:
        cells = {
            field_by_column[column_id]: cell.get("value")
            for column_id, cell in row["content"].items()
            if field_by_column.get(column_id)
        }
        thesis = {
            "id": int(row["record_id"]),
            "title": clean(cells.get("title")),
            "supervisor": clean(cells.get("supervisor")),
            # Tablesome stores a checked box as "1" or the check timestamp, unchecked as ""
            "available": bool(cells.get("available")),
            "date": cells.get("date") or None,
            "description": html_to_text(cells.get("description") or ""),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        # The table has empty rows and a row that repeats the column headers
        if thesis["title"] and thesis["title"] != "ΤΙΤΛΟΣ":
            theses.append(thesis)
    return sorted(theses, key=lambda thesis: thesis["created_at"], reverse=True)


def describe(thesis):
    return f"[{thesis['id']}] {thesis['title']} ({thesis['supervisor']})"


def diff(old, new):
    before = {thesis["id"]: thesis for thesis in old}
    new_ids = {thesis["id"] for thesis in new}
    kept = [(before[thesis["id"]], thesis) for thesis in new if thesis["id"] in before]
    return {
        "New": [describe(t) for t in new if t["id"] not in before],
        "Removed": [describe(t) for t in old if t["id"] not in new_ids],
        "Now available": [describe(t) for o, t in kept if t["available"] and not o["available"]],
        "No longer available": [describe(t) for o, t in kept if o["available"] and not t["available"]],
        "Changed": [
            f"{describe(t)}: {', '.join(fields)}"
            for o, t in kept
            if (fields := [field for field in TRACKED_FIELDS if o[field] != t[field]])
        ],
    }


def print_report(changes):
    for label, lines in changes.items():
        if lines:
            print(f"{label} ({len(lines)}):")
            for line in lines:
                print(f"  {line}")
    if not any(changes.values()):
        print("No changes since last run")


def load_snapshot():
    return json.loads(JSON_PATH.read_text()) if JSON_PATH.exists() else None


def refresh(user, password):
    try:
        with vpn(user, password):
            page = login_and_fetch(user, password)
    except urllib.error.HTTPError as error:
        raise FetchError(f"HTTP {error.code} from {error.url}")
    except (urllib.error.URLError, TimeoutError) as error:
        raise FetchError(f"Cannot reach {BASE} ({getattr(error, 'reason', error)})")

    theses = parse_theses(extract_table(page))
    previous = load_snapshot()
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": PAGE_URL,
        "count": len(theses),
        "available_count": sum(thesis["available"] for thesis in theses),
        "theses": theses,
    }
    # Write then rename so the server never reads a half-written file
    partial = JSON_PATH.with_suffix(".tmp")
    partial.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    partial.replace(JSON_PATH)
    return snapshot, (diff(previous["theses"], theses) if previous else None)


def main():
    try:
        snapshot, changes = refresh(*credentials())
    except FetchError as error:
        raise SystemExit(str(error))
    print(f"{snapshot['count']} topics ({snapshot['available_count']} available)")
    if changes is not None:
        print_report(changes)
    print(f"Wrote {JSON_PATH.name}")


if __name__ == "__main__":
    main()
