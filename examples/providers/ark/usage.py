#!/usr/bin/env python3
"""
ark_usage.py — Check Volcengine Ark (火山方舟) Coding Plan usage.

Two layers, because Volcengine splits credentials:

  1. INFERENCE API KEY  (env: VOLCES_ARK_API_KEY)
     - The bearer key you use to call models.
     - Can: verify access, list which Coding-Plan models you can call,
       and report per-call token usage that you accumulate locally.
     - Cannot: read your subscription's remaining quota. Volcengine does
       NOT expose a usage/quota REST endpoint or response header for the
       inference key (verified by probing — every candidate path 404s).

  2. OPENAPI AK/SK      (env: VOLC_ACCESSKEY + VOLC_SECRETKEY)
     - The Access Key / Secret Key from
       https://console.volcengine.com/iam/keymanage/
     - These are what the console's "subscribe" page uses (signed OpenAPI)
       to show remaining package tokens/requests. Provide them to fetch the
       real dashboard numbers via `dashboard` below.

Usage:
    python3 ark_usage.py check        # works with API key alone
    python3 ark_usage.py ledger       # show locally tracked token totals
    python3 ark_usage.py dashboard    # needs AK/SK; Coding Plan quota
    python3 ark_usage.py afp          # needs AK/SK; Agent Plan AFP usage
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ARK_HOST = "https://ark.cn-beijing.volces.com"
CODING_BASE = f"{ARK_HOST}/api/coding/v3"
LEDGER_PATH = Path.home() / ".ark_usage_ledger.json"

# Models worth probing for Coding-Plan access (update as the plan changes).
CODING_MODELS = [
    "doubao-seed-code-1.6",
    "doubao-seed-2.0-code",
    "kimi-k2.5",
    "glm-4.7",
]


# --------------------------------------------------------------------------- #
# Layer 1: inference API key
# --------------------------------------------------------------------------- #
def _api_key() -> str:
    key = os.environ.get("VOLCES_ARK_API_KEY")
    if not key:
        sys.exit("ERROR: VOLCES_ARK_API_KEY is not set in the environment.")
    return key


def _post_chat(model: str, max_tokens: int = 1) -> tuple[int, dict]:
    """Send a minimal chat request. Returns (status_code, json_body)."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(
        f"{CODING_BASE}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check() -> None:
    """Verify the key and list which Coding-Plan models are callable.

    Note: this sends one tiny (max_tokens=1) request per model, which costs a
    negligible amount of your plan quota. Pass `--no-probe` to skip.
    """
    probe = "--no-probe" not in sys.argv
    print(f"Endpoint : {CODING_BASE}")
    print(f"API key  : ...{_api_key()[-6:]}\n")

    if not probe:
        print("(skipping model probe)")
        return

    print("Coding-Plan model access:")
    for m in CODING_MODELS:
        status, body = _post_chat(m)
        if status == 200:
            usage = body.get("usage", {})
            _record_usage(m, usage)
            print(f"  [OK]   {m}  (this probe: {usage.get('total_tokens', '?')} tokens)")
        else:
            err = body.get("error", {})
            print(f"  [{status}] {m}  {err.get('code', '')}: {err.get('message', '')[:80]}")
    print(f"\nLocal token ledger updated -> {LEDGER_PATH}")
    print("Run `python3 ark_usage.py ledger` to see cumulative totals.")


# --------------------------------------------------------------------------- #
# Local cumulative token ledger (the only "usage" the API key can give you)
# --------------------------------------------------------------------------- #
def _load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return {"calls": 0, "by_model": {}, "totals": {}}


def _record_usage(model: str, usage: dict) -> None:
    led = _load_ledger()
    led["calls"] += 1
    bm = led["by_model"].setdefault(
        model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    tot = led["totals"]
    bm["calls"] += 1
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = int(usage.get(k, 0) or 0)
        bm[k] += v
        tot[k] = tot.get(k, 0) + v
    LEDGER_PATH.write_text(json.dumps(led, indent=2))


def ledger() -> None:
    led = _load_ledger()
    print(f"Local ledger ({LEDGER_PATH})")
    print(f"  total calls : {led['calls']}")
    t = led["totals"]
    print(
        f"  tokens      : prompt={t.get('prompt_tokens', 0)} "
        f"completion={t.get('completion_tokens', 0)} "
        f"total={t.get('total_tokens', 0)}"
    )
    if led["by_model"]:
        print("  by model:")
        for m, bm in led["by_model"].items():
            print(f"    {m}: {bm['calls']} calls, {bm['total_tokens']} tokens")
    print(
        "\nNOTE: this only counts calls made THROUGH this script. To track all of"
        "\nyour usage, route your client's responses' `usage` field into _record_usage()."
    )


# --------------------------------------------------------------------------- #
# Layer 2: signed OpenAPI (AK/SK) — the real subscription dashboard
# --------------------------------------------------------------------------- #
OPENAPI_HOST = "open.volcengineapi.com"
OPENAPI_REGION = "cn-beijing"
OPENAPI_SERVICE = "ark"

# Discovered by probing the Ark OpenAPI: this GET action (no params) returns the
# same Coding-Plan usage shown on the console "subscribe" page — session / weekly
# / monthly percent-used and their reset timestamps.
OPENAPI_ACTION = os.environ.get("ARK_USAGE_ACTION", "GetCodingPlanUsage")
OPENAPI_VERSION = os.environ.get("ARK_USAGE_VERSION", "2024-01-01")


def _sign(secret: bytes, msg: str) -> bytes:
    return hmac.new(secret, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret_key: str, date: str) -> bytes:
    k = _sign(secret_key.encode(), date)
    k = _sign(k, OPENAPI_REGION)
    k = _sign(k, OPENAPI_SERVICE)
    return _sign(k, "request")


def _openapi_request(
    action: str, version: str, method: str = "GET", body: bytes = b""
) -> dict:
    """Signed request against Volcengine OpenAPI (Volcengine signature v4)."""
    ak = os.environ.get("VOLC_ACCESSKEY")
    sk = os.environ.get("VOLC_SECRETKEY")
    if not (ak and sk):
        sys.exit(
            "ERROR: dashboard/afp needs VOLC_ACCESSKEY and VOLC_SECRETKEY.\n"
            "Create them at https://console.volcengine.com/iam/keymanage/ and:\n"
            "  export VOLC_ACCESSKEY=...\n  export VOLC_SECRETKEY=..."
        )

    q = {"Action": action, "Version": version}
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(q.items())
    )

    now = _dt.datetime.now(_dt.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload_hash = hashlib.sha256(body).hexdigest()

    canonical_headers = (
        f"host:{OPENAPI_HOST}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        [method, "/", canonical_query, canonical_headers, signed_headers, payload_hash]
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
        data=body if method == "POST" else None,
        method=method,
        headers={
            "Host": OPENAPI_HOST,
            "X-Date": x_date,
            "X-Content-Sha256": payload_hash,
            "Authorization": authorization,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


def openapi_get(action: str, version: str, query: dict | None = None) -> dict:
    """Signed GET against Volcengine OpenAPI (Volcengine signature v4)."""
    return _openapi_request(action, version, "GET")


def _fmt_ts(ts: int) -> str:
    return _dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")


def _bar(pct: float, width: int = 24) -> str:
    filled = int(round(pct / 100 * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def dashboard() -> None:
    """Fetch and print Coding-Plan and Agent Plan AFP usage."""
    # --- Coding Plan ---
    result = openapi_get(OPENAPI_ACTION, OPENAPI_VERSION)
    meta = result.get("ResponseMetadata", {})
    err = meta.get("Error")
    if err:
        sys.exit(f"OpenAPI error: {err.get('Code')}: {err.get('Message')}")

    res = result.get("Result", {})
    print(f"Coding Plan status : {res.get('Status', '?')}")
    if res.get("UpdateTimestamp"):
        print(f"As of              : {_fmt_ts(res['UpdateTimestamp'])}")
    print()
    print(f"{'Window':<9} {'Used %':>8}  {'Usage':<26}  {'Resets at'}")
    print("-" * 67)
    for q in res.get("QuotaUsage", []):
        pct = float(q.get("Percent", 0))
        reset = _fmt_ts(q["ResetTimestamp"]) if int(q.get("ResetTimestamp", 0)) > 0 else "-"
        used = f"{pct:.2f}%"
        print(f"{q.get('Level', '?'):<9} {used:>8}  {_bar(pct):<26}  {reset}")

    # --- Agent Plan AFP ---
    afp_result = _openapi_request("GetAFPUsage", OPENAPI_VERSION, "POST", b"{}")
    afp_meta = afp_result.get("ResponseMetadata", {})
    afp_err = afp_meta.get("Error")
    if afp_err:
        print(f"\nAFP OpenAPI error: {afp_err.get('Code')}: {afp_err.get('Message')}")
    else:
        afp_res = afp_result.get("Result", {})
        print()
        print(f"Agent Plan status  : {afp_res.get('PlanType', '?')}")
        print()
        print(f"{'Window':<9} {'Used':>8}  {'Usage':<26}  {'Quota':<17}  {'Resets at'}")
        print("-" * 86)
        for label, key in [("5h", "AFPFiveHour"), ("Daily", "AFPDaily"), ("Weekly", "AFPWeekly"), ("Monthly", "AFPMonthly")]:
            w = afp_res.get(key, {})
            used = float(w.get("Used", 0))
            quota = float(w.get("Quota", 0))
            reset_ts = int(w.get("ResetTime", 0))
            reset = _fmt_ts(reset_ts // 1000) if reset_ts > 0 else "-"
            if quota > 0:
                pct = (used / quota) * 100
                print(f"{label:<9} {pct:>7.2f}%  {_bar(pct):<26}  {used:>6.0f} / {quota:<6.0f}  {reset}")
            else:
                print(f"{label:<9} {'--':>8}  {'N/A':<26}  {used:>6.0f} / {quota:<6.0f}  {reset}")

    if "--json" in sys.argv:
        print("\n" + json.dumps({"coding": res, "afp": afp_result.get("Result", {})}, indent=2, ensure_ascii=False))


def afp() -> None:
    """Fetch and print the Agent Plan AFP (Agent Foundation Package) usage."""
    result = _openapi_request("GetAFPUsage", OPENAPI_VERSION, "POST", b"{}")
    meta = result.get("ResponseMetadata", {})
    err = meta.get("Error")
    if err:
        sys.exit(f"OpenAPI error: {err.get('Code')}: {err.get('Message')}")

    res = result.get("Result", {})
    print(f"Agent Plan status  : {res.get('Status', '?')}")
    if res.get("UpdateTimestamp"):
        print(f"As of              : {_fmt_ts(res['UpdateTimestamp'])}")
    print()

    windows = [
        ("5h", res.get("AFPFiveHour", {})),
        ("Daily", res.get("AFPDaily", {})),
        ("Weekly", res.get("AFPWeekly", {})),
        ("Monthly", res.get("AFPMonthly", {})),
    ]

    print(f"{'Window':<9} {'Used':>8}  {'Usage':<26}  {'Quota':<17}  {'Resets at'}")
    print("-" * 86)
    for label, w in windows:
        used = float(w.get("Used", 0))
        quota = float(w.get("Quota", 0))
        reset_ts = int(w.get("ResetTime", 0))
        reset = _fmt_ts(reset_ts // 1000) if reset_ts > 0 else "-"
        if quota > 0:
            pct = (used / quota) * 100
            print(f"{label:<9} {pct:>7.2f}%  {_bar(pct):<26}  {used:>6.0f} / {quota:<6.0f}  {reset}")
        else:
            print(f"{label:<9} {'--':>8}  {'N/A':<26}  {used:>6.0f} / {quota:<6.0f}  {reset}")

    if "--json" in sys.argv:
        print("\n" + json.dumps(res, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
import urllib.parse  # noqa: E402  (kept near use for clarity)

COMMANDS = {"check": check, "ledger": ledger, "dashboard": dashboard, "afp": afp}

if __name__ == "__main__":
    cmd = next((a for a in sys.argv[1:] if not a.startswith("-")), "dashboard")
    fn = COMMANDS.get(cmd)
    if not fn:
        sys.exit(f"Unknown command '{cmd}'. Choose: {', '.join(COMMANDS)}")
    fn()
