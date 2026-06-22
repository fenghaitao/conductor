#!/usr/bin/env python3
r"""
Status line for Droid: Ark Coding Plan usage, git branch, context usage, PS1-style path.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------
RESET = "\033[00m"
BOLD_BLUE = "\033[01;34m"
YELLOW = "\033[93m"
RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"

# ---------------------------------------------------------------------------
# Ark API configuration
# ---------------------------------------------------------------------------
ARK_CACHE_PATH = Path.home() / ".cache" / "ark_status_cache.json"
ARK_CACHE_TTL = 300  # 5 minutes

OPENAPI_HOST = "open.volcengineapi.com"
OPENAPI_REGION = "cn-beijing"
OPENAPI_SERVICE = "ark"
OPENAPI_ACTION = os.environ.get("ARK_USAGE_ACTION", "GetCodingPlanUsage")
OPENAPI_VERSION = os.environ.get("ARK_USAGE_VERSION", "2024-01-01")

def _sign(secret: bytes, msg: str) -> bytes:
    return hmac.new(secret, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret_key: str, date: str) -> bytes:
    k = _sign(secret_key.encode(), date)
    k = _sign(k, OPENAPI_REGION)
    k = _sign(k, OPENAPI_SERVICE)
    return _sign(k, "request")


def fetch_ark_usage() -> str | None:
    """Fetch Ark Coding Plan usage from Volcengine API (cached)."""
    ak = os.environ.get("VOLC_ACCESSKEY")
    sk = os.environ.get("VOLC_SECRETKEY")
    if not (ak and sk):
        return None

    if ARK_CACHE_PATH.exists():
        try:
            cache = json.loads(ARK_CACHE_PATH.read_text())
            age = _dt.datetime.now().timestamp() - cache.get("ts", 0)
            if age < ARK_CACHE_TTL:
                return cache.get("status")
        except (json.JSONDecodeError, KeyError):
            pass

    q = {"Action": OPENAPI_ACTION, "Version": OPENAPI_VERSION}
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(q.items())
    )

    now = _dt.datetime.now(_dt.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload_hash = hashlib.sha256(b"").hexdigest()

    canonical_headers = (
        f"host:{OPENAPI_HOST}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        ["GET", "/", canonical_query, canonical_headers, signed_headers, payload_hash]
    )

    scope = f"{short_date}/{OPENAPI_REGION}/{OPENAPI_SERVICE}/request"
    string_to_sign = "\n".join(
        [
            "HMAC-SHA256",
            x_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(sk, short_date), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"HMAC-SHA256 Credential={ak}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    req = urllib.request.Request(
        f"https://{OPENAPI_HOST}/?{canonical_query}",
        method="GET",
        headers={
            "Host": OPENAPI_HOST,
            "X-Date": x_date,
            "X-Content-Sha256": payload_hash,
            "Authorization": authorization,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except Exception:
        return None

    meta = result.get("ResponseMetadata", {})
    if meta.get("Error"):
        return None

    res = result.get("Result", {})
    quotas = res.get("QuotaUsage", [])

    parts = []
    for q in quotas:
        level = q.get("Level", "").lower()
        abbrev = {"session": "S", "weekly": "W", "monthly": "M", "daily": "D"}.get(level, level[:1].upper())
        pct = float(q.get("Percent", 0))
        parts.append(f"{abbrev}:{pct:.0f}%")

    status = "Ark " + " ".join(parts) if parts else "Ark: ?"

    ARK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARK_CACHE_PATH.write_text(
        json.dumps({"ts": _dt.datetime.now().timestamp(), "status": status})
    )

    return status


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def get_git_info(cwd: str) -> str | None:
    """Return 'branch' or 'branch *' (dirty) for the given directory."""
    try:
        branch = subprocess.check_output(
            ["git", "-C", cwd, "branch", "--show-current"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    if not branch:
        return None

    # Truncate long branch names
    if len(branch) > 40:
        branch = branch[:37] + "..."

    # Check for dirty working tree
    try:
        subprocess.check_call(
            ["git", "-C", cwd, "diff", "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        dirty = False
    except subprocess.CalledProcessError:
        dirty = True

    return f"{branch} *" if dirty else branch


# ---------------------------------------------------------------------------
# Path shortening
# ---------------------------------------------------------------------------
def shorten_path(path: str) -> str:
    """Shorten a path for compact display."""
    home = os.path.expanduser("~")
    if path.startswith(home + os.sep):
        rel = path[len(home) + 1 :]
    elif path.startswith(home):
        rel = path[len(home) :]
    else:
        rel = path

    parts = rel.split(os.sep)

    # Show first component / ... / last component for deep paths
    if len(parts) > 3:
        return f"~/{parts[0]}/.../{parts[-1]}"
    elif path.startswith(home):
        return f"~/{rel}"
    else:
        return path


# ---------------------------------------------------------------------------
# Context usage bar
# ---------------------------------------------------------------------------
def format_context(context: dict | None) -> str | None:
    """Format context usage as a compact progress bar."""
    if not context:
        return None

    display = context.get("display", "")
    percentage = context.get("percentage", 0)

    if not display and not percentage:
        return None

    filled = min(int(percentage / 10), 10)
    empty = 10 - filled
    bar = "█" * filled + "░" * empty

    if percentage >= 70:
        color = RED
    elif percentage >= 50:
        color = YELLOW
    else:
        color = GREEN

    return f"{color}[{bar}] {display}{RESET}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Read Droid's stdin JSON
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    cwd = input_data.get("cwd", os.getcwd())
    context = input_data.get("context")

    # Build output parts
    parts: list[str] = []

    # 1. Ark usage (async, non-blocking via cache)
    ark = fetch_ark_usage()
    if ark:
        parts.append(f"{DIM}{ark}{RESET}")

    # 3. Directory
    short_dir = shorten_path(cwd)
    parts.append(f"{BOLD_BLUE}{short_dir}{RESET}")

    # 4. Git branch
    git_info = get_git_info(cwd)
    if git_info:
        parts.append(f"{YELLOW}{git_info}{RESET}")

    # 5. Context usage
    ctx = format_context(context)
    if ctx:
        parts.append(ctx)

    # Join with separator
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
