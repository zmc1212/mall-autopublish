"""在两个独立 Chromium profile 之间同步淘宝登录态。

入库浏览器和商品详情浏览器继续使用不同的 ``user-data-dir``。同步时由
发行版内置的 Node + Playwright Core 通过 CDP 临时连接两个浏览器，在 Node
进程内完成 storage state 的读取、域名过滤和恢复，不复制 Chromium 数据库，
也不把完整 state 写入磁盘、日志或返回给 UI。
"""

from __future__ import annotations

import json
import ipaddress
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from . import paths


def _endpoint(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def _endpoint_identity(value: str | None) -> tuple[str, str, int] | None:
    """Return a local CDP endpoint identity without retaining credentials.

    CDP URLs are normally HTTP URLs, but accepting an omitted scheme here
    makes the guard conservative for configuration values such as
    ``127.0.0.1:9222``. The path is intentionally ignored: ``/json/version``
    and a WebSocket endpoint on the same listener still identify one browser.
    """

    raw = _endpoint(value)
    if not raw:
        return None
    candidate = raw if "://" in raw else f"http://{raw}"
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
        if not host:
            return None
        port = parsed.port
    except (TypeError, ValueError):
        return None
    scheme = str(parsed.scheme or "http").lower()
    if scheme not in {"http", "https", "ws", "wss"}:
        return None
    if port is None:
        port = 443 if scheme in {"https", "wss"} else 80

    host = host.rstrip(".").lower()
    # These names and addresses can all refer to the same local Chromium
    # listener. The port check below is deliberately conservative as well:
    # even different host spellings must never allow source and target to
    # share a CDP port.
    canonical_host = host
    if host in {"localhost", "localhost.localdomain"}:
        canonical_host = "local"
    else:
        try:
            address = ipaddress.ip_address(host)
            if address.is_loopback or address.is_unspecified:
                canonical_host = "local"
            elif address.version == 6 and address.ipv4_mapped is not None:
                mapped = address.ipv4_mapped
                if mapped.is_loopback or mapped.is_unspecified:
                    canonical_host = "local"
        except ValueError:
            pass
    return scheme, canonical_host, int(port)


def _same_endpoint(source_endpoint: str, target_endpoint: str) -> bool:
    """Reject any source/target pair that can address one CDP listener."""

    source = _endpoint_identity(source_endpoint)
    target = _endpoint_identity(target_endpoint)
    if source is None or target is None:
        return False
    # A CDP port is the ownership boundary for the local browsers this app
    # launches. Comparing the port even when host spellings differ protects
    # against localhost/127.0.0.1/IPv6 aliases and accidental same-port use.
    return source[2] == target[2]


def _endpoint_available(endpoint: str, timeout: float = 0.35) -> bool:
    """Check a local CDP endpoint without exposing its response contents."""

    if not endpoint:
        return False
    try:
        with urlopen(endpoint + "/json/version", timeout=timeout) as response:
            return bool(response.status == 200)
    except Exception:
        return False


# This script intentionally receives only endpoint/path/URL metadata through
# stdin. Cookies and localStorage stay in the Node process memory and the only
# stdout value is the compact count/status object emitted at the end.
_NODE_SYNC_SCRIPT = r'''
"use strict";

const chunks = [];
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => chunks.push(chunk));
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(chunks.join(""));
  } catch (_) {
    emitFailure();
    return;
  }
  run(input).then(emit).catch(() => emitFailure());
});

const ROOTS = new Set(["taobao.com", "tmall.com", "tmall.hk"]);
const SUFFIXES = [".taobao.com", ".tmall.com", ".tmall.hk"];

function emit(value) {
  try {
    process.stdout.write(JSON.stringify(value));
  } catch (_) {
    emitFailure();
  }
}

function emitFailure() {
  process.stdout.write(JSON.stringify(failure("sync_failed", false)));
}

function failure(reason, sourceAvailable, applied = false) {
  return {
    ok: false,
    source_available: Boolean(sourceAvailable),
    applied: Boolean(applied),
    cookies: 0,
    origins: 0,
    navigated: false,
    reason,
  };
}

function allowedHost(host) {
  const value = String(host || "").toLowerCase().replace(/^\.+|\.+$/g, "");
  return ROOTS.has(value) || SUFFIXES.some(suffix => value.endsWith(suffix));
}

function loginHost(url) {
  try {
    const host = new URL(String(url || "")).hostname.toLowerCase();
    return new Set([
      "login.taobao.com",
      "login.tmall.com",
      "loginmyseller.taobao.com",
      "login.m.taobao.com",
      "passport.taobao.com",
    ]).has(host);
  } catch (_) {
    return false;
  }
}

function filterCookie(value) {
  if (!value || typeof value !== "object") return null;
  const name = String(value.name || "");
  const domain = String(value.domain || "").trim();
  if (!name || !domain || !allowedHost(domain)) return null;
  const cookie = {
    name,
    value: String(value.value || ""),
    domain,
    path: String(value.path || "/"),
  };
  for (const key of ["expires", "httpOnly", "secure", "sameSite", "partitionKey"]) {
    if (value[key] !== undefined && value[key] !== null) cookie[key] = value[key];
  }
  return cookie;
}

function filterState(value) {
  if (!value || typeof value !== "object") return null;
  const cookies = [];
  for (const item of Array.isArray(value.cookies) ? value.cookies : []) {
    const cookie = filterCookie(item);
    if (cookie) cookies.push(cookie);
  }
  const origins = [];
  for (const item of Array.isArray(value.origins) ? value.origins : []) {
    if (!item || typeof item !== "object") continue;
    const origin = String(item.origin || "").trim();
    let parsed;
    try { parsed = new URL(origin); } catch (_) { continue; }
    if (!["http:", "https:"].includes(parsed.protocol) || !allowedHost(parsed.hostname)) continue;
    const localStorage = [];
    for (const entry of Array.isArray(item.localStorage) ? item.localStorage : []) {
      if (!entry || typeof entry !== "object") continue;
      const name = String(entry.name || "");
      if (name) localStorage.push({ name, value: String(entry.value || "") });
    }
    origins.push({ origin, localStorage });
  }
  return { cookies, origins };
}

async function closeConnection(browser) {
  if (!browser) return;
  try { await browser.close(); } catch (_) {}
}

function allowedFrames(context) {
  const frames = [];
  for (const page of context.pages()) {
    for (const frame of page.frames()) {
      try {
        const url = new URL(frame.url());
        if (["http:", "https:"].includes(url.protocol) && allowedHost(url.hostname)) {
          frames.push({ frame, origin: url.origin });
        }
      } catch (_) {}
    }
  }
  return frames;
}

async function readLiveStorage(context) {
  // A newly attached CDP context does not track origins from existing tabs:
  // storageState() can return zero origins even when those tabs have tokens.
  // Read existing frames without opening, navigating or closing source tabs.
  const origins = new Map();
  for (const { frame, origin } of allowedFrames(context)) {
    if (origins.has(origin)) continue;
    try {
      const localStorage = await frame.evaluate(() => Object.keys(window.localStorage).map(
        name => ({ name, value: window.localStorage.getItem(name) || "" })
      ));
      origins.set(origin, { origin, localStorage });
    } catch (_) {
      // A navigating/detached frame can disappear; another same-origin frame
      // may still provide the storage. Cookies are captured independently.
    }
  }
  return [...origins.values()];
}

async function run(input) {
  const playwright = require(String(input.playwrightPath || ""));
  const sourceEndpoint = String(input.sourceEndpoint || "");
  const targetEndpoint = String(input.targetEndpoint || "");
  const navigateUrl = String(input.navigateUrl || "");
  let sourceBrowser;
  let targetBrowser;
  let state;
  try {
    try {
      sourceBrowser = await playwright.chromium.connectOverCDP(sourceEndpoint, { timeout: 5000 });
    } catch (_) {
      return failure("source_unavailable", false);
    }
    const sourceContexts = sourceBrowser.contexts();
    if (!sourceContexts.length) return failure("capture_failed", false);
    try {
      const sourceContext = sourceContexts[0];
      state = filterState({
        cookies: await sourceContext.cookies(),
        origins: await readLiveStorage(sourceContext),
      });
    } catch (_) {
      return failure("capture_failed", true);
    }
    if (!state) return failure("capture_failed", true);
    if (!state.cookies.length) return {
      ...failure("not_logged_in", true),
      cookies: 0,
      origins: state.origins.length,
    };
  } finally {
    await closeConnection(sourceBrowser);
  }

  try {
    try {
      targetBrowser = await playwright.chromium.connectOverCDP(targetEndpoint, { timeout: 5000 });
    } catch (_) {
      return failure("sync_failed", true);
    }
    let targetContexts;
    try {
      targetContexts = targetBrowser.contexts();
    } catch (_) {
      return failure("sync_failed", true);
    }
    if (!targetContexts.length) return failure("sync_failed", true);
    const context = targetContexts[0];
    // Playwright's public setStorageState clears target cookies/localStorage,
    // then restores the filtered state using a temporary internal page. It
    // does not install a persistent init script or close existing detail tabs.
    try {
      const capturedOrigins = new Set(state.origins.map(item => item.origin));
      for (const { origin } of allowedFrames(context)) {
        if (!capturedOrigins.has(origin)) {
          state.origins.push({ origin, localStorage: [] });
          capturedOrigins.add(origin);
        }
      }
      await context.setStorageState(state);
    } catch (_) {
      return {
        ...failure("sync_failed", true),
        cookies: state.cookies.length,
        origins: state.origins.length,
      };
    }
    let navigated = false;
    if (navigateUrl) {
      try {
        const pages = context.pages();
        const page = pages[0] || await context.newPage();
        await page.goto(navigateUrl, { waitUntil: "domcontentloaded", timeout: 8000 });
        if (loginHost(page.url())) {
          return {
            ...failure("redirected_to_login", true, true),
            cookies: state.cookies.length,
            origins: state.origins.length,
          };
        }
      } catch (_) {
        return {
          ...failure("navigation_failed", true, true),
          cookies: state.cookies.length,
          origins: state.origins.length,
        };
      }
      navigated = true;
    }
    return {
      ok: true,
      source_available: true,
      applied: true,
      cookies: state.cookies.length,
      origins: state.origins.length,
      navigated,
    };
  } finally {
    await closeConnection(targetBrowser);
  }
}
'''


def _node_sync_result(source_endpoint: str, target_endpoint: str, navigate_url: str) -> dict[str, Any] | None:
    """Run the bundled in-memory sync helper and return only status/counts."""

    # Keep this defense in the low-level helper as well as sync_login_session:
    # a future caller must not be able to bypass the ownership boundary and
    # clear the source context with setStorageState.
    if _same_endpoint(source_endpoint, target_endpoint):
        return _failure(reason="same_endpoint")

    node_path = paths.node_exe_path()
    cli_path = paths.cli_js_path()
    package_path = cli_path.parents[3] if cli_path else None
    if not node_path or not package_path or not (Path(package_path) / "index.js").is_file():
        return None
    payload = json.dumps(
        {
            "sourceEndpoint": source_endpoint,
            "targetEndpoint": target_endpoint,
            "navigateUrl": navigate_url,
            "playwrightPath": str(package_path),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    kwargs: dict[str, Any] = {
        "input": payload,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 15,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        completed = subprocess.run(
            [str(node_path), "-e", _NODE_SYNC_SCRIPT],
            **kwargs,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    try:
        result = json.loads(str(completed.stdout or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict):
        return None
    # Whitelist the fields that can reach the desktop API. Never forward the
    # subprocess stdout/stderr or any storage-state field.
    normalized = {
        "ok": bool(result.get("ok")),
        "source_available": bool(result.get("source_available")),
        "applied": bool(result.get("applied")),
        "cookies": int(result.get("cookies") or 0),
        "origins": int(result.get("origins") or 0),
        "navigated": bool(result.get("navigated")),
    }
    reason = str(result.get("reason") or "").strip()
    if reason in {
        "source_unavailable",
        "capture_failed",
        "not_logged_in",
        "sync_failed",
        "navigation_failed",
        "redirected_to_login",
    }:
        normalized["reason"] = reason
    return normalized


def _failure(*, source_available: bool = False, reason: str = "") -> dict[str, Any]:
    result = {
        "ok": False,
        "source_available": bool(source_available),
        "applied": False,
        "cookies": 0,
        "origins": 0,
        "navigated": False,
    }
    if reason:
        result["reason"] = reason
    return result


def sync_login_session(
    target_endpoint: str,
    *,
    source_endpoint: str = "",
    navigate_url: str = "",
    web_module: Any = None,
) -> dict[str, Any]:
    """Copy current login state into the independent detail browser.

    ``navigate_url`` is used only for a newly started detail browser. When it
    is empty, existing detail pages stay open and the next tab sees the
    refreshed context storage. Failure is explicit so callers cannot report a
    detail page as opened when its session was not synchronized.
    """

    try:
        if web_module is None:
            from .modules import load_web

            web_module = load_web()
        if not source_endpoint:
            source_endpoint = str(getattr(web_module, "CDP_ENDPOINT", "") or "")
        source_endpoint = _endpoint(source_endpoint)
        target_endpoint = _endpoint(target_endpoint)
        # Check before either endpoint probe. Most importantly, never call
        # the Node helper with the source endpoint as its target: setStorageState
        # clears cookies/localStorage and would otherwise erase the live login.
        if _same_endpoint(source_endpoint, target_endpoint):
            return _failure(reason="same_endpoint")
        if not _endpoint_available(source_endpoint):
            return _failure(reason="source_unavailable")
        if not _endpoint_available(target_endpoint):
            return _failure(source_available=True, reason="sync_failed")
        result = _node_sync_result(source_endpoint, target_endpoint, str(navigate_url or ""))
        if result is None:
            return _failure(source_available=True, reason="sync_failed")
        result_reason = str(result.get("reason") or "")
        if result_reason == "not_logged_in":
            return _failure(source_available=True, reason="not_logged_in")
        if not result.get("ok"):
            if result_reason:
                return result
            result["reason"] = "sync_failed"
            return result
        if not int(result.get("cookies") or 0):
            return _failure(source_available=True, reason="not_logged_in")
        return result
    except Exception:
        return _failure(reason="sync_failed")


__all__ = ["sync_login_session"]
