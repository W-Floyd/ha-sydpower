#!/usr/bin/env python3
"""
Rebuild sydpower/product_catalog.json from a BrightEMS XAPK.

The catalog is not embedded in the app. BrightEMS is a uni-app front end talking
to a uniCloud (aliyun) backend, and the product list, categories and per-product
feature definitions are all served by one cloud function. This script:

  1. unpacks the XAPK and its base APK to reach the uni-app bundle,
  2. beautifies the bundle, because it ships as one ~2 MB line and any
     non-trivial regex against that backtracks badly,
  3. reads the backend credentials and endpoint out of the beautified source
     rather than hardcoding them, so a new app version is picked up,
  4. fetches the public catalog endpoints and caches the raw responses,
  5. builds the catalog from the cache, offline.

Stages are separable, and the fetched JSON is cached, because the backend resets
the connection under repeated calls — so iterate on parsing without re-fetching.

Usage:
    python extract_catalog.py --xapk BrightEMS_1.6.6_APKPure.xapk
    python extract_catalog.py --xapk app.xapk --stage beautify   # read the source
    python extract_catalog.py --stage build                      # offline, from cache
    python extract_catalog.py --xapk app.xapk --refresh          # re-fetch

`--locale` is forwarded to the backend, which localises feature names. The
catalog previously shipped French labels ("Sortie USB"), so the default is
English and the locale used is recorded in the output.

Requires: jsbeautifier (pip install jsbeautifier).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import getpass
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# Every call goes through one cloud function; the action travels as `$url` in its
# arguments with the payload nested under `data` (vk-unicloud convention).
ROUTER_FUNCTION = "router"
ACTIONS = {
    "products": "client/product/pub/listProductByWhereJson_v2",
    "detail": "client/product/pub/getAllProductList",
}

# Reachable only with a signed-in user token: anything under client/device/ replies
# `token校验未通过` ("token verification failed") to an anonymous one. Fetched when
# --token is supplied, skipped otherwise.
AUTHENTICATED_ACTIONS = {
    "firmware_hint": "client/device/kh/getFirmwareUpgradeHint",
    "fault_codes": "client/device/faultCode.getList",
}

# Copied from a category onto each of its products, matching the previous
# catalog's shape so sydpower/catalog.py needs no change.
CATEGORY_FIELDS = ("modbus_address", "modbus_count", "page_path")


def log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


# ── 1. unpack ─────────────────────────────────────────────────────────────────


def unpack(xapk: Path, workdir: Path) -> Path:
    """Unpack the XAPK and its base APK; return the uni-app `www` directory."""
    apk_dir = workdir / "xapk"
    apk_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(xapk) as archive:
        apks = [n for n in archive.namelist() if n.endswith(".apk")]
        # Splits are named config.*; the remaining APK is the base one carrying
        # the assets. Language splits hold Android resources, not the bundle.
        base = next((n for n in apks if not Path(n).name.startswith("config.")), None)
        if base is None:
            sys.exit(f"no base APK among {apks}")
        log("unpack", f"base APK: {base}")
        archive.extract(base, apk_dir)

    www_root = workdir / "apk"
    with zipfile.ZipFile(apk_dir / base) as archive:
        members = [n for n in archive.namelist() if "/www/" in n and n.endswith(".js")]
        if not members:
            sys.exit("no uni-app JavaScript found under assets/apps/*/www/")
        archive.extractall(www_root, members)

    service = next(www_root.rglob("app-service.js"), None)
    if service is None:
        sys.exit("app-service.js not found in the bundle")
    log("unpack", f"bundle: {service.parent.relative_to(www_root)}")
    return service.parent


# ── 2. beautify ───────────────────────────────────────────────────────────────


def beautify(www: Path, out_dir: Path) -> Path:
    """
    Beautify the bundle's JavaScript into *out_dir*.

    Worth doing even though only a few constants are needed here: the source is a
    single enormous line, so searching it is slow and unreadable, and the
    beautified copy is what makes further reverse engineering practical.
    """
    try:
        import jsbeautifier
    except ImportError:
        sys.exit("jsbeautifier is required: pip install jsbeautifier")

    out_dir.mkdir(parents=True, exist_ok=True)
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.max_preserve_newlines = 2

    count = 0
    for src in sorted(www.glob("*.js")):
        if src.name.startswith("__uniapp"):
            continue  # framework shims, not app code
        log("beautify", f"{src.name} ({src.stat().st_size // 1024} KB)")
        (out_dir / src.name).write_text(
            jsbeautifier.beautify(src.read_text(errors="replace"), options)
        )
        count += 1

    log("beautify", f"wrote {count} file(s) to {out_dir}")
    return out_dir


# ── 3. discover backend config ────────────────────────────────────────────────


def discover_config(beautified: Path) -> dict[str, str]:
    """
    Read the uniCloud space id, client secret and endpoint from the source.

    Read rather than hardcoded so a newer XAPK, or a rotated secret, is picked up
    without editing this script.
    """
    sources = sorted(p for p in beautified.glob("*.js") if p.name.startswith("app-"))
    if not sources:
        sys.exit(f"no beautified app-*.js in {beautified}; run an earlier stage first")
    text = "\n".join(p.read_text(errors="replace") for p in sources)

    def find(pattern: str) -> str | None:
        match = re.search(pattern, text)
        return match.group(1) if match else None

    space_id = find(r'"spaceId"\s*:\s*"([^"]+)"') or find(r'spaceId\s*:\s*"(mp-[^"]+)"')
    secret = find(r'"clientSecret"\s*:\s*"([^"]+)"')
    endpoint = find(r'"endpoint"\s*:\s*"(https://[^"]+)"')
    appid = find(r'"?appid"?\s*[:=]\s*"(__UNI__[A-Z0-9]+)"') or ""

    if not (space_id and secret):
        sys.exit("could not find spaceId / clientSecret in the bundle")
    if not endpoint:
        # Mirrors the bundle's own rule for choosing a host.
        endpoint = (
            "https://api.next.bspapp.com"
            if space_id.startswith("mp-")
            else "https://api.bspapp.com"
        )

    log("config", f"spaceId  {space_id}")
    log("config", f"endpoint {endpoint}")
    return {
        "space_id": space_id,
        "client_secret": secret,
        "endpoint": endpoint,
        "appid": appid,
    }


# ── 4. fetch (cached) ─────────────────────────────────────────────────────────


def sign(data: dict[str, Any], client_secret: str) -> str:
    """
    Reproduce the bundle's request signature.

    Its implementation sorts the keys, joins the truthy ones as `&k=v`, strips the
    leading separator, and HMAC-MD5s the result with the client secret.
    """
    joined = "".join(f"&{k}={data[k]}" for k in sorted(data) if data[k])[1:]
    return hmac.new(client_secret.encode(), joined.encode(), hashlib.md5).hexdigest()


def post(
    config: dict[str, str],
    data: dict[str, Any],
    locale: str,
    token: str | None,
    attempts: int = 3,
    user_token: str | None = None,
) -> Any:
    """
    Sign and POST one request, retrying the connection resets the API throws.

    Two tokens are in play and they are not interchangeable. *token* is the
    anonymous access token that authenticates the client to the uniCloud gateway,
    carried in the body and in `x-basement-token`. *user_token* is the uni-id
    token identifying the signed-in user, carried in `x-client-token`. Putting a
    user token where the gateway expects its own yields
    `GATEWAY_INVALID_TOKEN / session_expired`.
    """
    data = dict(data)
    data.setdefault("spaceId", config["space_id"])
    data.setdefault("timestamp", int(time.time() * 1000))
    if token:
        # The token participates in the signature, so set it before signing.
        data["token"] = token

    client_info = {
        "PLATFORM": "app-plus",
        "OS": "android",
        "APPID": config.get("appid", ""),
        "DEVICEID": "0" * 16,
        "locale": locale,
        "LOCALE": locale,
    }
    headers = {
        "Content-Type": "application/json",
        "x-serverless-sign": sign(data, config["client_secret"]),
        "x-client-info": urllib.parse.quote(json.dumps(client_info)),
    }
    if token:
        headers["x-basement-token"] = token
    # Always present, empty when not signed in, as the app does.
    headers["x-client-token"] = user_token or ""

    request = urllib.request.Request(
        config["endpoint"] + "/client",
        data=json.dumps(data).encode(),
        headers=headers,
        method="POST",
    )

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            sys.exit(f"HTTP {exc.code}: {exc.read()[:400]!r}")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last = exc
            log("fetch", f"attempt {attempt}/{attempts} failed ({exc}); retrying")
            time.sleep(2 * attempt)
    sys.exit(f"request failed after {attempts} attempts: {last}")


# vk-unicloud resolves the identifier itself, so one field covers a username, a
# mobile number or an email address.
#
# Note the missing `client/` prefix: user-centre actions are unprefixed while the
# app's own actions carry it. Prefixing this one returns
# `404 not found【client/user/pub/login】`.
LOGIN_ACTION = "user/pub/login"
LOGIN_BY_EMAIL_ACTION = "user/pub/loginByEmail"
SEND_EMAIL_CODE_ACTION = "user/pub/sendEmailCode"


def load_dotenv(path: Path) -> list[str]:
    """
    Load ``KEY=value`` pairs from *path* into the environment.

    Existing environment variables win, so an explicit export still overrides the
    file. Sourcing a dotenv in a shell only sets shell variables unless each line
    is exported, which means a child process sees nothing — reading the file here
    avoids that trap entirely.

    Returns the names that were set, never the values.
    """
    if not path.exists():
        return []

    loaded: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not _:
            continue
        # Strip one layer of matching quotes, as shells would.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def login(config: dict[str, str], locale: str, anon_token: str) -> str:
    """
    Exchange credentials for a user token.

    Credentials come from BRIGHTEMS_USER / BRIGHTEMS_PASSWORD, or an interactive
    prompt. They are never echoed, never logged, and never passed on a command
    line — a password in argv would be visible to other processes and would land
    in shell history.
    """
    username = os.environ.get("BRIGHTEMS_USER")
    password = os.environ.get("BRIGHTEMS_PASSWORD")
    if not username:
        username = input("BrightEMS account (username, email or mobile): ").strip()
    if not password:
        password = getpass.getpass("BrightEMS password (not echoed): ")
    if not (username and password):
        sys.exit("no credentials supplied")

    if "@" in username:
        result = _login_by_email(config, locale, anon_token, username)
    else:
        result = _login_by_password(config, locale, anon_token, username, password)

    if result.get("code") not in (0, None):
        # Deliberately does not echo the response wholesale: it can contain the
        # submitted account.
        sys.exit(f"login failed: code {result.get('code')} {result.get('msg', '')}")

    token = result.get("token") or (result.get("userInfo") or {}).get("token")
    if not token:
        sys.exit(f"login succeeded but returned no token; keys: {sorted(result)}")
    log("login", "user token acquired")
    return token


def _invoke(
    config: dict[str, str], locale: str, token: str, action: str, data: dict
) -> dict[str, Any]:
    """Invoke one router action with a payload, returning the unwrapped result."""
    body = post(
        config,
        {
            "method": "serverless.function.runtime.invoke",
            "params": json.dumps(
                {
                    "functionTarget": ROUTER_FUNCTION,
                    "functionArgs": {"$url": action, "data": data, "encrypt": False},
                },
                separators=(",", ":"),
            ),
        },
        locale,
        token,
    )
    return body.get("data", body)


def _login_by_password(
    config: dict[str, str], locale: str, anon_token: str, username: str, password: str
) -> dict[str, Any]:
    """Username and password login. `username` is mandatory for this action."""
    return _invoke(
        config, locale, anon_token, LOGIN_ACTION,
        {"username": username, "password": password},
    )


def _login_by_email(
    config: dict[str, str], locale: str, anon_token: str, email: str
) -> dict[str, Any]:
    """
    Email login, which needs an emailed verification code rather than a password.

    Password login requires a `username`; an email address is rejected as
    "user does not exist", and loginByEmail answers "verification code wrong or
    expired" whatever password is supplied. So this requests a code and asks for
    it. Set BRIGHTEMS_CODE to skip the prompt.
    """
    code = os.environ.get("BRIGHTEMS_CODE")
    if not code:
        log("login", "requesting an email verification code")
        sent = _invoke(
            config, locale, anon_token, SEND_EMAIL_CODE_ACTION,
            {"email": email, "type": "login"},
        )
        if sent.get("code") not in (0, None):
            sys.exit(
                f"could not send an email code: {sent.get('code')} {sent.get('msg', '')}"
            )
        log("login", "code sent; check the inbox for the account in .env")
        code = input("Emailed verification code: ").strip()
    if not code:
        sys.exit("no verification code supplied")

    return _invoke(
        config, locale, anon_token, LOGIN_BY_EMAIL_ACTION,
        {"email": email, "code": code},
    )


def load_user_token(
    config: dict[str, str],
    locale: str,
    cache: Path,
    anon_token: str,
    do_login: bool,
    relogin: bool,
) -> str | None:
    """
    Return a cached user token, signing in only when necessary.

    The cache is consulted regardless of --login so a one-off sign-in keeps
    working on later runs. --refresh deliberately does not invalidate it: that
    flag is about re-fetching API payloads, and dropping the token would mean
    another emailed code. Use --relogin for that.
    """
    path = cache / "user_token.json"
    if path.exists() and not relogin:
        log("auth", "using cached user token")
        return json.loads(path.read_text()).get("token")
    if not do_login:
        log("auth", "no cached user token; pass --login to sign in")
        return None

    token = login(config, locale, anon_token)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token}))
    path.chmod(0o600)
    log("auth", f"token cached in {path.name} (mode 600)")
    return token


def get_access_token(config: dict[str, str], locale: str) -> str:
    """
    Obtain an anonymous access token.

    The router rejects even its public actions without one, replying
    `param_token_required`.
    """
    body = post(
        config,
        {"method": "serverless.auth.user.anonymousAuthorize", "params": "{}"},
        locale,
        token=None,
    )
    result = body.get("data") or body.get("result") or body
    token = result.get("accessToken") if isinstance(result, dict) else None
    if not token:
        sys.exit(f"anonymous authorize returned no accessToken: {json.dumps(body)[:400]}")
    log("auth", "anonymous accessToken acquired")
    return token


def call(
    config: dict[str, str],
    action: str,
    locale: str,
    token: str,
    user_token: str | None = None,
) -> Any:
    """Invoke one router action and return its unwrapped result."""
    args: dict[str, Any] = {"$url": action, "data": {}, "encrypt": False}
    if user_token:
        # The router reads the user token from here as well as the header.
        args["uniIdToken"] = user_token
    body = post(
        config,
        {
            "method": "serverless.function.runtime.invoke",
            "params": json.dumps(
                {"functionTarget": ROUTER_FUNCTION, "functionArgs": args},
                separators=(",", ":"),
            ),
        },
        locale,
        token,
        user_token=user_token,
    )
    if body.get("error"):
        sys.exit(f"{action}: backend error {body['error']}")

    # Aliyun nests the function's return value under `data`; vk-unicloud then
    # wraps its own payload in a code/msg envelope.
    result = body.get("data", body)
    if isinstance(result, dict) and result.get("code") not in (0, None):
        sys.exit(f"{action}: code {result.get('code')} {result.get('msg', '')}")
    return result


def fetch(
    config: dict[str, str],
    locale: str,
    cache: Path,
    refresh: bool,
    user_token: str | None = None,
    do_login: bool = False,
    relogin: bool = False,
) -> dict[str, Any]:
    """
    Return the raw API payloads, fetching only what is not already cached.

    The cache exists because the backend resets connections under repeated calls,
    and because parsing is worth iterating on without re-fetching.
    """
    cache.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, Any] = {}
    token: str | None = None

    if not user_token:
        token = get_access_token(config, locale)
        user_token = load_user_token(config, locale, cache, token, do_login, relogin)

    wanted = dict(ACTIONS)
    if user_token:
        wanted.update(AUTHENTICATED_ACTIONS)
    else:
        log("fetch", "skipping " + ", ".join(AUTHENTICATED_ACTIONS) + " (not signed in)")

    for name, action in wanted.items():
        path = cache / f"{name}.{locale}.json"
        if path.exists() and not refresh:
            log("cache", f"{name} <- {path.name}")
            payloads[name] = json.loads(path.read_text())
            continue
        if token is None:
            token = get_access_token(config, locale)
        log("fetch", action)
        # The gateway always gets the anonymous token; user-scoped actions
        # additionally carry the uni-id token.
        payloads[name] = call(
            config,
            action,
            locale,
            token,
            user_token=user_token if name in AUTHENTICATED_ACTIONS else None,
        )
        path.write_text(json.dumps(payloads[name], ensure_ascii=False, indent=1))
        log("cache", f"{name} -> {path.name} ({path.stat().st_size // 1024} KB)")

    return payloads


# ── 5. build ──────────────────────────────────────────────────────────────────


def _feature(entry: dict[str, Any]) -> dict[str, Any]:
    """Strip a state/setting record down to the fields worth keeping."""
    keep = (
        "function_name",
        "holding_index",
        "input_index",
        "protocol_version",
        "data_list",
        "data_state",
        "unit_list",
        "icon",
        "type",
    )
    out = {"id": entry.get("_id")}
    out.update({k: entry[k] for k in keep if k in entry})
    return out


def build_catalog(payloads: dict[str, Any], locale: str, config: dict[str, str]) -> dict[str, Any]:
    """Assemble the catalog from cached payloads, resolving ids to definitions."""
    rows = payloads["products"].get("rows", [])
    detail = payloads["detail"]["allProducts"]

    products_detail = {p["_id"]: p for p in detail.get("products", [])}
    states = {s["_id"]: s for s in detail.get("state_list_all", [])}
    settings = {s["_id"]: s for s in detail.get("setting_list_all", [])}
    brands = {b["_id"]: b for b in detail.get("brandInfo_list_all", [])}

    catalog: dict[str, Any] = {
        "_meta": {
            "generated_by": "analysis/extract_catalog.py",
            "locale": locale,
            "space_id": config["space_id"],
        },
        "categories": {},
        "products": {},
        "features": {},
    }

    # Settings are normalised: one deduplicated definition table, with products
    # referencing entries by integer index. Inlining full records per product is
    # what made the previous catalog 750 KB.
    setting_defs: list[dict[str, Any]] = []
    setting_index: dict[str, int] = {}
    for entry in detail.get("setting_list_all", []):
        definition = {
            k: entry[k]
            for k in ("function_name", "holding_index", "input_index", "bit", "data_list", "protocol_version")
            if k in entry
        }
        # unit_list is overloaded: when it has as many entries as data_list the
        # app renders them as per-option labels, otherwise entry 0 is a shared
        # unit for every option. Keep the list and let consumers apply that rule.
        units = [u.get("lang_text", "") for u in (entry.get("unit_list") or [])]
        if units:
            definition["units"] = units
        setting_index[entry["_id"]] = len(setting_defs)
        setting_defs.append(definition)
    catalog["settings"] = setting_defs
    log("build", f"{len(setting_defs)} setting definitions")

    # Firmware gates: the app hides some setting options on specific product +
    # panel-version combinations. Only present when fetched with a user token.
    # The router wraps its payload in a code/msg envelope, so the useful fields
    # sit under `data`.
    hint = (payloads.get("firmware_hint") or {}).get("data") or {}
    gates = hint.get("AC_standby_time_list")
    if gates:
        catalog["firmware_gates"] = {"ac_standby_time": gates}
        log("build", f"{len(gates)} firmware gate rule(s)")
    else:
        log("build", "no firmware gate rules (needs --login or --token)")

    for category in detail.get("category_list_all", []):
        catalog["categories"][category["_id"]] = {
            k: category[k] for k in CATEGORY_FIELDS if k in category
        }
    log("build", f"{len(catalog['categories'])} categories")

    for row in rows:
        uuid, name = row.get("uuid"), row.get("name")
        if not (uuid and name):
            continue
        # The app keys its product map as uuid + "_" + name.
        key = f"{uuid}_{name}"
        product_id = row["_id"]
        extra = products_detail.get(product_id, {})
        category_id = row.get("category_id") or extra.get("category_id", "")

        entry: dict[str, Any] = {"product_id": product_id}
        if category_id:
            entry["category_id"] = category_id
        entry["protocol_version"] = row.get(
            "protocol_version", extra.get("protocol_version", 1)
        )
        # Modbus parameters live on the category; copy them onto the product so
        # lookups need no second hop.
        category = catalog["categories"].get(category_id, {})
        for field in ("modbus_address", "modbus_count"):
            if field in category:
                entry[field] = category[field]

        # Identity, so a model can be reported rather than guessed.
        #
        # `product_name` holds the OEM model code — "P210-A0E01" for an AFERIY
        # P210. `brand_id` is deliberately ignored: the largest bucket is
        # 省油灯(中性通用), "neutral/universal", the OEM's white-label group, and
        # resellers such as AFERIY and FOSSiBOT do not appear in the catalog at
        # all. Reporting that as a brand would be worse than reporting nothing.
        model = (row.get("product_name") or row.get("product_alias") or "").strip()
        if model:
            entry["model"] = model

        catalog["products"][key] = entry

        module = extra.get("function_module", {})
        # Reference the shared definitions rather than copying them.
        indexes = [
            setting_index[i]
            for i in module.get("setting_list_ids", [])
            if i in setting_index
        ]
        if indexes:
            catalog["products"][key]["setting_indexes"] = indexes

        resolved_states = [
            _feature(states[i]) for i in module.get("state_list_ids", []) if i in states
        ]
        resolved_settings = [
            _feature(settings[i])
            for i in module.get("setting_list_ids", [])
            if i in settings
        ]
        if resolved_states or resolved_settings:
            catalog["features"][product_id] = {
                "states": resolved_states,
                "settings": resolved_settings,
            }

    log("build", f"{len(catalog['products'])} products, {len(catalog['features'])} feature sets")
    named = sum(1 for p in catalog["products"].values() if p.get("model"))
    log("build", f"{named} products carry a model name")
    return catalog


# ── 6. manifest matchers ──────────────────────────────────────────────────────


def update_manifest(catalog: dict[str, Any], manifest_path: Path) -> bool:
    """
    Regenerate the integration manifest's `bluetooth` matchers from the catalog.

    Home Assistant matches on *advertised* service UUIDs, and every product key
    is `<SERVICE_UUID>_<NAME>`, so the matcher list is mechanically derivable.
    Hand-maintaining it meant the list silently lagged the catalog: a refresh from
    151 to 169 products left 18 devices undiscoverable.

    Only the `bluetooth` block is touched; every other field keeps its value and
    position. Returns True if the file changed.
    """
    if not manifest_path.exists():
        log("manifest", f"skipped, no such file: {manifest_path}")
        return False

    manifest = json.loads(manifest_path.read_text())
    uuids = sorted({key.split("_", 1)[0].upper() for key in catalog["products"]})
    matchers = [{"service_uuid": u, "connectable": True} for u in uuids]

    before = manifest.get("bluetooth", [])
    if before == matchers:
        log("manifest", f"{len(matchers)} matchers already current")
        return False

    manifest["bluetooth"] = matchers
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    log(
        "manifest",
        f"{len(before)} -> {len(matchers)} matchers "
        f"({len(matchers) - len(before):+d})",
    )
    return True


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--xapk", type=Path, help="BrightEMS XAPK (not needed for --stage build)")
    parser.add_argument("--workdir", type=Path, default=here / "build")
    parser.add_argument("--out", type=Path, default=here.parent / "sydpower" / "product_catalog.json")
    parser.add_argument(
        "--full-out",
        type=Path,
        default=here.parent / "reference" / "product_catalog.full.json",
        help="where to write the complete catalog including features",
    )
    parser.add_argument("--locale", default="en", help="locale requested from the backend")
    parser.add_argument("--refresh", action="store_true", help="ignore cached API responses")
    parser.add_argument(
        "--env",
        type=Path,
        default=here / ".env",
        help="dotenv file read for credentials (default: analysis/.env)",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help=(
            "sign in to fetch the firmware gate table and fault codes. Reads "
            "BRIGHTEMS_USER / BRIGHTEMS_PASSWORD or prompts; the password is "
            "never taken on the command line, echoed, or logged."
        ),
    )
    parser.add_argument(
        "--relogin",
        action="store_true",
        help="discard the cached user token and sign in again",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("BRIGHTEMS_TOKEN"),
        help=(
            "signed-in BrightEMS user token (or set BRIGHTEMS_TOKEN). Only needed "
            "for the firmware gate table and fault codes, which reject anonymous "
            "requests. Obtainable from the app's own network traffic."
        ),
    )
    parser.add_argument(
        "--stage",
        choices=("unpack", "beautify", "config", "fetch", "build"),
        default="build",
        help="stop after this stage (default: build, the whole pipeline)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=here.parent / "custom_components" / "sydpower" / "manifest.json",
        help="integration manifest whose bluetooth matchers are regenerated",
    )
    parser.add_argument(
        "--no-manifest", action="store_true", help="leave the manifest untouched"
    )
    parser.add_argument("--clean", action="store_true", help="remove the workdir first")
    args = parser.parse_args()

    # Read credentials from a dotenv beside the script, if present.
    loaded = load_dotenv(args.env)
    if loaded:
        log("env", f"loaded {', '.join(sorted(loaded))} from {args.env.name}")

    if args.clean and args.workdir.exists():
        shutil.rmtree(args.workdir)

    beautified = args.workdir / "js"
    if args.xapk:
        if not args.xapk.exists():
            sys.exit(f"no such file: {args.xapk}")
        www = unpack(args.xapk, args.workdir)
        if args.stage == "unpack":
            return 0
        beautify(www, beautified)
        if args.stage == "beautify":
            log("done", f"beautified source in {beautified}")
            return 0
    elif args.stage in ("unpack", "beautify"):
        sys.exit("--xapk is required for this stage")

    config = discover_config(beautified)
    if args.stage == "config":
        return 0

    payloads = fetch(config, args.locale, args.workdir / "api", args.refresh, args.token, args.login, args.relogin)
    if args.stage == "fetch":
        return 0

    catalog = build_catalog(payloads, args.locale, config)

    if args.full_out:
        args.full_out.parent.mkdir(parents=True, exist_ok=True)
        args.full_out.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n")
        log("done", f"wrote {args.full_out} ({args.full_out.stat().st_size // 1024} KB), with features")

    # The shipped copy omits `features`: nothing reads it at runtime, and its
    # indices are sub-indices within a parent rather than register numbers, which
    # has already caused wrong sensors once. The full file above keeps it.
    slim = {k: v for k, v in catalog.items() if k != "features"}
    slim["_meta"] = {**catalog["_meta"], "features": "see reference/product_catalog.full.json"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(slim, ensure_ascii=False, indent=1) + "\n")
    log("done", f"wrote {args.out} ({args.out.stat().st_size // 1024} KB), products + categories")

    if not args.no_manifest:
        update_manifest(catalog, args.manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
