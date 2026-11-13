"""用真实 Chrome + 项目 Playwright CLI 验证并发页面隔离。

脚本只启动本机临时 HTTP 夹具，不访问淘宝，也不会连接默认的 9222 端口。
默认报告写入 ``output/playwright/browser-isolation/report.json``；每次运行的
Chrome profile、Playwright daemon、页面 registry 和截图都在该目录的独立运行
子目录中。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def free_port(exclude: set[int] | None = None) -> int:
    excluded = exclude or set()
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in excluded:
            return port


def _html(origin_name: str, page: str) -> bytes:
    origin = json.dumps(origin_name, ensure_ascii=False)
    if page == "owned":
        body = (
            f'<h1>owned page {origin_name}</h1>'
            '<p id="owned-marker">This page belongs to one item.</p>'
        )
    elif page == "cross":
        body = """
        <h1>cross origin fixture</h1>
        <label for="cross-value">cross value</label>
        <input id="cross-value" aria-label="cross value" type="text">
        <output id="cross-output"></output>
        <script>
        (() => {
          const input = document.querySelector('#cross-value');
          const output = document.querySelector('#cross-output');
          const key = 'cross-origin-fixture-state';
          const save = () => {
            output.textContent = input.value;
            sessionStorage.setItem(key, JSON.stringify({value: input.value}));
          };
          try { input.value = (JSON.parse(sessionStorage.getItem(key) || '{}').value || ''); } catch (_) {}
          input.addEventListener('input', save);
          save();
        })();
        </script>
        """
    else:
        body = """
        <h1>same URL item fixture</h1>
        <label for="value">worker value</label>
        <input id="value" aria-label="worker value" type="text">
        <label for="note">worker note</label>
        <textarea id="note" aria-label="worker note"></textarea>
        <label for="upload">worker file</label>
        <input id="upload" aria-label="worker file" type="file">
        <output id="file-name"></output>
        <script>
        (() => {
          const value = document.querySelector('#value');
          const note = document.querySelector('#note');
          const upload = document.querySelector('#upload');
          const fileName = document.querySelector('#file-name');
          const key = 'same-url-fixture-state';
          const read = () => { try { return JSON.parse(sessionStorage.getItem(key) || '{}'); } catch (_) { return {}; } };
          const save = (extra) => {
            const state = {...read(), value: value.value, note: note.value, ...extra};
            fileName.textContent = state.file || '';
            sessionStorage.setItem(key, JSON.stringify(state));
          };
          const state = read();
          value.value = state.value || '';
          note.value = state.note || '';
          fileName.textContent = state.file || '';
          value.addEventListener('input', () => save({}));
          note.addEventListener('input', () => save({}));
          upload.addEventListener('change', () => save({file: (upload.files[0] || {}).name || ''}));
        })();
        </script>
        """
    document = f"""<!doctype html>
    <html><head><meta charset="utf-8"><title>{origin_name} {page}</title></head>
    <body data-origin={origin} data-page={json.dumps(page)}>{body}</body></html>"""
    return document.encode("utf-8")


class LocalFixture:
    """Two independent loopback origins serving deterministic pages."""

    def __init__(self, name: str):
        self.name = name
        self.port = free_port({9222})
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name=f"fixture-{name}",
            daemon=True,
        )

    def _handler(self):
        label = self.name

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib handler API
                path = urlparse(self.path).path
                if path == "/health":
                    payload = b"ok"
                    content_type = "text/plain; charset=utf-8"
                elif path in {"/item", "/owned", "/cross"}:
                    payload = _html(label, path[1:])
                    content_type = "text/html; charset=utf-8"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        return Handler

    def start(self) -> None:
        self.thread.start()
        with urlopen(self.url("/health"), timeout=5) as response:
            if response.read() != b"ok":
                raise RuntimeError(f"夹具 {self.name} 健康检查失败")

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def wait_cdp(port: int, timeout: float = 20.0) -> dict:
    if int(port) == 9222:
        raise AssertionError("隔离验收禁止使用 9222")
    deadline = time.monotonic() + timeout
    endpoint = f"http://127.0.0.1:{int(port)}/json/version"
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(endpoint, timeout=1) as response:
                value = json.loads(response.read().decode("utf-8"))
            if isinstance(value, dict) and value.get("Browser"):
                return value
        except Exception as exc:  # Chrome may need a few seconds to start.
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"临时 Chrome CDP 未就绪: {endpoint}; {last_error}")


def launch_chrome(web, chrome: Path, profile: Path, port: int, first_url: str):
    if int(port) == 9222:
        raise AssertionError("临时 Chrome 端口不能是 9222")
    args = web.chrome_launch_args(
        chrome=chrome,
        profile=profile,
        port=port,
        url=first_url,
    )
    args.extend(("--headless=new", "--disable-gpu", "--window-size=1280,900"))
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(args, **kwargs)
    return process, args


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    pid = int(process.pid or 0)
    try:
        if os.name == "nt" and pid:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        elif pid:
            os.killpg(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass


def registry_snapshot(registry_path: Path) -> list[dict]:
    from web_fill.browser_pool import PageOwnershipRegistry

    return [lease.as_dict() for lease in PageOwnershipRegistry(registry_path).list()]


def read_item_state(session):
    return session.eval_json(
        "() => ({"
        "href: location.href, origin: location.origin,"
        "value: (document.querySelector('#value') || {}).value || '',"
        "note: (document.querySelector('#note') || {}).value || '',"
        "file: (document.querySelector('#file-name') || {}).textContent || ''"
        "})"
    )


def read_cross_state(session):
    return session.eval_json(
        "() => ({href: location.href, origin: location.origin, "
        "value: (document.querySelector('#cross-value') || {}).value || ''})"
    )


def screenshot(session, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use the project's native CLI screenshot command with an ASCII filename
    # in the worker output directory.  A later copy puts the evidence beside
    # the report; this avoids Windows CLI daemon path handling for the Chinese
    # workspace directory while keeping the capture in Playwright itself.
    filename = f"isolation-{path.stem}.png"
    evidence = {"path": str(path), "ok": False, "filename": filename}
    try:
        result = session.cmd(
            "screenshot",
            f"--filename={filename}",
            raw=False,
            timeout=15,
        )
        evidence["cli_result"] = str(result or "")[:4000]
    except Exception as exc:
        evidence["error"] = str(exc)
        return evidence
    candidates = [session.output_dir / filename]
    candidates.extend(session.output_dir.rglob(filename))
    source = next((candidate for candidate in candidates if candidate.is_file()), None)
    if source is not None and source.resolve() != path.resolve():
        shutil.copy2(source, path)
    if path.is_file() and path.stat().st_size > 0:
        evidence["ok"] = True
    else:
        evidence["error"] = f"Playwright 截图未生成: {path}"
    return evidence


def safe_session_detach(session) -> None:
    if session is None:
        return
    try:
        session.detach()
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "playwright" / "browser-isolation",
        help="报告目录，默认 output/playwright/browser-isolation",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    cdp_port = free_port({9222})
    report = {
        "status": "preflight",
        "run_id": run_id,
        "started_at": time.time(),
        "cdp_endpoint": f"http://127.0.0.1:{cdp_port}",
        "cdp_port": cdp_port,
        "forbidden_cdp_port": 9222,
        "workspace": str(ROOT),
        "run_dir": str(run_dir),
        "network_scope": "loopback fixture only; no real Taobao URL",
        "assertions": {},
        "steps": [],
        "errors": [],
    }
    write_json(report_path, report)

    temp_root = Path(tempfile.mkdtemp(prefix="qn-browser-isolation-", dir=str(run_dir)))
    fixture_a = LocalFixture("origin-a")
    fixture_b = LocalFixture("origin-b")
    fixture_started = []
    chrome_process = None
    sessions = []
    env_names = (
        "QIANNIU_APPDATA", "QIANNIU_OUTPUT_DIR", "QIANNIU_RESULTS_DIR",
        "QIANNIU_PROFILE", "QIANNIU_CDP_PORT", "QIANNIU_BROWSER_REGISTRY",
        "QIANNIU_CLI_JS", "PWTEST_DAEMON_SESSION_DIR",
    )
    old_env = {name: os.environ.get(name) for name in env_names}
    registry_path = run_dir / "browser-ownership.json"
    profile_path = temp_root / "chrome-profile"
    daemon_dir = temp_root / "playwright-daemon"
    browser_output = run_dir / "browser"
    browser_output.mkdir(parents=True, exist_ok=True)

    try:
        fixture_a.start()
        fixture_started.append(fixture_a)
        fixture_b.start()
        fixture_started.append(fixture_b)
        item_url = fixture_a.url("/item")
        cross_url = fixture_b.url("/cross")
        owned_url = fixture_a.url("/owned")
        report.update({
            "origins": {"a": fixture_a.url("/item"), "b": fixture_b.url("/cross")},
            "registry_path": str(registry_path),
            "profile_path": str(profile_path),
            "playwright_daemon_dir": str(daemon_dir),
        })
        for url in (item_url, cross_url, owned_url):
            parsed = urlparse(url)
            if parsed.hostname != "127.0.0.1":
                raise AssertionError(f"夹具 URL 非 loopback: {url}")
        write_json(report_path, report)

        os.environ.update({
            "QIANNIU_APPDATA": str(temp_root / "appdata"),
            "QIANNIU_OUTPUT_DIR": str(browser_output),
            "QIANNIU_RESULTS_DIR": str(temp_root / "results"),
            "QIANNIU_PROFILE": str(profile_path),
            "QIANNIU_CDP_PORT": str(cdp_port),
            "QIANNIU_BROWSER_REGISTRY": str(registry_path),
            "QIANNIU_CLI_JS": str(ROOT / ".work" / "node_modules" / "playwright-core" / "lib" / "tools" / "cli-client" / "cli.js"),
            "PWTEST_DAEMON_SESSION_DIR": str(daemon_dir),
        })
        web = importlib.import_module("千牛网页执行")
        chrome = Path(web.CHROME).resolve()
        if not chrome.is_file():
            raise RuntimeError(f"未找到真实 Chrome: {chrome}")
        chrome_process, launch_args = launch_chrome(web, chrome, profile_path, cdp_port, item_url)
        version = wait_cdp(cdp_port)
        report.update({
            "browser": str(chrome),
            "browser_pid": chrome_process.pid,
            "browser_version": version,
            "launch_args": launch_args,
        })
        report["steps"].append("temporary_chrome_ready")
        write_json(report_path, report)

        from web_fill.browser_pool import PageOwnershipRegistry

        file_dir = run_dir / "fixture-files"
        file_dir.mkdir(parents=True, exist_ok=True)
        file_a = file_dir / "worker-a.txt"
        file_b = file_dir / "worker-b.txt"
        file_a.write_text("file payload for worker A", encoding="utf-8")
        file_b.write_text("file payload for worker B", encoding="utf-8")
        report["fixture_files"] = {"a": str(file_a), "b": str(file_b)}

        run_tag = run_id.replace("-", "")
        key_a = f"browser-isolation-{run_tag}-a"
        key_b = f"browser-isolation-{run_tag}-b"
        session_a = web.CliSession(
            session_name=f"isolation-{run_tag}-a",
            output_dir=browser_output / "worker-a",
            isolated=True,
            cdp_endpoint=f"http://127.0.0.1:{cdp_port}",
            registry_path=registry_path,
            worker_id=f"worker-a-{run_tag}",
        )
        session_b = web.CliSession(
            session_name=f"isolation-{run_tag}-b",
            output_dir=browser_output / "worker-b",
            isolated=True,
            cdp_endpoint=f"http://127.0.0.1:{cdp_port}",
            registry_path=registry_path,
            worker_id=f"worker-b-{run_tag}",
        )
        sessions.extend((session_a, session_b))
        barrier = threading.Barrier(2, timeout=90)
        flow_results = {}
        flow_errors = {}
        flow_lock = threading.Lock()
        primary_leases = {}

        def await_both():
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                raise RuntimeError("两个 CLI worker 未能到达交错操作屏障")

        def worker_flow(label, session, key, file_path):
            try:
                lease = session.begin_item(key, item_url)
                with flow_lock:
                    primary_leases[label] = lease
                    report["steps"].append(f"{label}_begin_same_url")
                await_both()
                session.fill("#value", label)
                await_both()
                session.fill("#note", f"note-{label}")
                # The project CLI's high-level ``upload`` command consumes a
                # file-chooser modal.  The isolation guard must run a
                # Target.getTargetInfo check immediately before every page
                # command, and that check cannot execute while the modal is
                # open.  Use the same real Playwright CLI through run-code and
                # setInputFiles directly, which performs the upload without
                # opening a modal and still fires the page's change handler.
                file_literal = json.dumps(str(Path(file_path).resolve()).replace("\\", "/"))
                session.cmd(
                    "run-code",
                    "async page => { await page.locator('#upload').setInputFiles(%s); return true; }" % file_literal,
                    raw=False,
                    timeout=120,
                )
                await_both()
                before_cross = read_item_state(session)
                session.goto(cross_url)
                session.fill("#cross-value", f"cross-{label}")
                cross = read_cross_state(session)
                await_both()
                session.goto(item_url)
                after_cross = read_item_state(session)
                with flow_lock:
                    flow_results[label] = {
                        "before_cross": before_cross,
                        "cross": cross,
                        "after_cross": after_cross,
                    }
            except Exception as exc:
                with flow_lock:
                    flow_errors[label] = {"error": str(exc), "traceback": traceback.format_exc()}
                try:
                    barrier.abort()
                except Exception:
                    pass

        threads = [
            threading.Thread(target=worker_flow, args=("A", session_a, key_a, file_a), name="isolation-flow-A"),
            threading.Thread(target=worker_flow, args=("B", session_b, key_b, file_b), name="isolation-flow-B"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=150)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("并发 CLI worker 超时")
        if flow_errors:
            raise RuntimeError(json.dumps(flow_errors, ensure_ascii=False))
        report["flow_results"] = flow_results

        report["assertions"].update({
            "same_initial_url": item_url == fixture_a.url("/item"),
            "distinct_values": (
                flow_results["A"]["after_cross"].get("value") == "A"
                and flow_results["B"]["after_cross"].get("value") == "B"
                and flow_results["A"]["after_cross"].get("value") != flow_results["B"]["after_cross"].get("value")
            ),
            "distinct_uploads": (
                flow_results["A"]["after_cross"].get("file") == file_a.name
                and flow_results["B"]["after_cross"].get("file") == file_b.name
            ),
            "cross_origin_values": (
                flow_results["A"]["cross"].get("origin") == fixture_b.url("/").rstrip("/")
                and flow_results["B"]["cross"].get("origin") == fixture_b.url("/").rstrip("/")
                and flow_results["A"]["cross"].get("value") == "cross-A"
                and flow_results["B"]["cross"].get("value") == "cross-B"
            ),
        })

        # Each item owns a second page.  Closing A's complete item page set
        # must leave B's two pages and its values usable.
        secondary_a = session_a.tab_new(owned_url, owner_key=key_a)
        secondary_b = session_b.tab_new(owned_url, owner_key=key_b)
        session_a.tab_select(primary_leases["A"])
        session_b.tab_select(primary_leases["B"])
        report["steps"].append("two_owned_pages_per_worker")
        screenshot_a = screenshot(session_a, run_dir / "screenshots" / "a-before-close.png")
        report.setdefault("screenshots", []).append(screenshot_a)
        if not screenshot_a.get("ok"):
            report.setdefault("warnings", []).append({"screenshot": screenshot_a})
        session_a.finish_item(preserve=False)
        b_after_a_close = read_item_state(session_b)
        b_leases_after_a_close = registry_snapshot(registry_path)
        b_owned = [lease for lease in b_leases_after_a_close if lease["key"] == key_b]
        a_owned = [lease for lease in b_leases_after_a_close if lease["key"] == key_a]
        report["assertions"].update({
            "close_one_item_preserves_other": (
                b_after_a_close.get("value") == "B"
                and b_after_a_close.get("file") == file_b.name
                and len(b_owned) == 2
                and not a_owned
            ),
        })
        report["registry_after_a_close"] = b_leases_after_a_close

        # Park B for review, detach its daemon, then let a new run atomically
        # take over the same key and read its preserved DOM state.
        session_b.finish_item(preserve=True)
        session_b.detach()
        session_b = None
        session_b2 = web.CliSession(
            session_name=f"isolation-{run_tag}-b-reclaim",
            output_dir=browser_output / "worker-b-reclaim",
            isolated=True,
            cdp_endpoint=f"http://127.0.0.1:{cdp_port}",
            registry_path=registry_path,
            worker_id=f"worker-b-reclaim-{run_tag}",
        )
        sessions.append(session_b2)
        reclaimed_lease = session_b2.begin_item(key_b)
        reclaimed = read_item_state(session_b2)
        screenshot_b = screenshot(session_b2, run_dir / "screenshots" / "b-after-reclaim.png")
        report.setdefault("screenshots", []).append(screenshot_b)
        if not screenshot_b.get("ok"):
            report.setdefault("warnings", []).append({"screenshot": screenshot_b})
        report["reclaimed_state"] = reclaimed
        report["assertions"]["parked_page_reclaimed_by_new_run"] = (
            reclaimed_lease is not None
            and reclaimed.get("value") == "B"
            and reclaimed.get("note") == "note-B"
            and reclaimed.get("file") == file_b.name
        )
        session_b2.finish_item(preserve=False)
        report["registry_final"] = registry_snapshot(registry_path)
        report["assertions"]["terminal_cleanup_empty_registry"] = not report["registry_final"]
        if not all(report["assertions"].values()):
            failed = [name for name, value in report["assertions"].items() if not value]
            raise AssertionError("隔离断言失败: " + ", ".join(failed))
        report["status"] = "passed"
        report["steps"].append("isolation_assertions_passed")
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append({"error": str(exc), "traceback": traceback.format_exc()})
    finally:
        # Sessions are named uniquely and point at the temporary daemon store;
        # detaching them does not inspect or close unrelated user sessions.
        for session in reversed(sessions):
            safe_session_detach(session)
        stop_process(chrome_process)
        for fixture in reversed(fixture_started):
            try:
                fixture.stop()
            except Exception as exc:
                report["errors"].append({"fixture_stop": str(exc)})
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        report["finished_at"] = time.time()
        report["temporary_root_removed"] = False
        try:
            shutil.rmtree(temp_root, ignore_errors=True)
            report["temporary_root_removed"] = not temp_root.exists()
        except OSError as exc:
            report["errors"].append({"temporary_cleanup": str(exc)})
        write_json(report_path, report)

    print(json.dumps({"status": report["status"], "report": str(report_path), "errors": report["errors"]}, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
