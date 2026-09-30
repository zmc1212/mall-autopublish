"""本机 FastAPI：清单、任务、Chrome 连接、设置。仅绑定 127.0.0.1。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import paths
from .jobs import MANAGER

app = FastAPI(title="千牛自动上架", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


class WorkbookIn(BaseModel):
    path: str


class TemplateIn(BaseModel):
    path: str


class JobStartIn(BaseModel):
    limit: int = Field(0, ge=0)
    force_new: bool = False
    retry_failed: bool = False


class WorkspaceIn(BaseModel):
    path: str
    selected_categories: list[str] | None = None


class WorkspaceSelectionIn(BaseModel):
    selected_categories: list[str] | None = None


class WorkspaceDefaultsIn(BaseModel):
    brand: str | None = None
    attributes_template: str | None = None
    logistics_template: str | None = None
    sales_template: str | None = None
    price: float | None = None
    stock: int | None = None


class ItemOpenIn(BaseModel):
    row: int
    product_id: str = ""
    action: str


class ItemClearIn(BaseModel):
    row: int
    product_id: str = ""


class SettingsIn(BaseModel):
    chrome_path: str | None = None
    chrome_profile: str | None = None
    cdp_port: int | None = Field(default=None, ge=1, le=65535)
    debug_browser: bool | None = None
    sku_template_import: bool | None = None
    skip_spec_images: bool | None = None
    sku_image_strategy: str | None = None
    settings_version: int | None = None
    limit: int | None = Field(default=None, ge=0)
    spec_upload_batch_size: int | None = Field(default=None, ge=0, le=99)
    results_dir: str | None = None


def _fail(exc: Exception, code=400):
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@app.get("/api/health")
def health():
    return {"ok": True, "app": "千牛自动上架"}


@app.get("/api/status")
async def status():
    try:
        chrome = await run_in_threadpool(MANAGER.chrome_status)
    except Exception as exc:
        chrome = {
            "error": str(exc),
            "cdp": False,
            "logged_in": False,
            "checking": False,
            "chrome_found": False,
            "browser_source": "missing",
        }
    job = MANAGER.snapshot()
    settings = paths.load_settings()
    try:
        workspace = MANAGER.workspace_info()
    except Exception:
        workspace = {"path": job.get("workspace_path") or "", "defaults": {}, "registry": {}}
    payload = {
        "chrome": chrome,
        "job": job,
        "workspace": workspace,
        "settings": {
            "chrome_path": settings.chrome_path,
            "chrome_profile": settings.chrome_profile,
            "cdp_port": settings.cdp_port,
            "debug_browser": settings.debug_browser,
            "sku_template_import": settings.sku_template_import,
            "skip_spec_images": settings.skip_spec_images,
            "sku_image_strategy": settings.sku_image_strategy,
            "settings_version": settings.settings_version,
            "limit": settings.limit,
            "spec_upload_batch_size": settings.spec_upload_batch_size,
            "results_dir": settings.results_dir,
        },
    }
    # 内容指纹：内容未变时前端跳过 setState，消除空闲时的整树重渲染
    payload["_rev"] = hashlib.md5(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return payload


@app.post("/api/chrome/open")
async def chrome_open():
    try:
        return await run_in_threadpool(MANAGER.open_chrome)
    except Exception as exc:
        _fail(exc)


@app.post("/api/chrome/check-login")
def chrome_check_login():
    """前端加载时触发一次后台登录态检测；每进程只执行一次，重复调用自动忽略。"""
    return {"started": MANAGER.begin_login_check()}


@app.post("/api/chrome/reveal")
async def chrome_reveal():
    try:
        return await run_in_threadpool(MANAGER.reveal_chrome)
    except Exception as exc:
        _fail(exc)


@app.post("/api/workbook/import")
async def import_workbook(body: WorkbookIn):
    try:
        return await run_in_threadpool(MANAGER.import_workbook, body.path)
    except Exception as exc:
        _fail(exc)


@app.post("/api/workbook/validate")
async def validate_workbook():
    if not MANAGER.workbook_path:
        _fail(RuntimeError("请先导入商品清单或选择工作空间"))
    try:
        if MANAGER.workspace_path and Path(MANAGER.workspace_path).is_dir():
            # 校验前先同步一次工作空间文件夹，保证清单与磁盘现状一致
            return await run_in_threadpool(MANAGER.rescan_workspace)
        return await run_in_threadpool(MANAGER.import_workbook, MANAGER.workbook_path)
    except Exception as exc:
        _fail(exc)


@app.post("/api/workspace/open")
async def workspace_open(body: WorkspaceIn):
    try:
        return await run_in_threadpool(
            MANAGER.open_workspace,
            body.path,
            False,
            body.selected_categories,
        )
    except Exception as exc:
        _fail(exc)


@app.post("/api/workspace/rescan")
async def workspace_rescan(body: WorkspaceSelectionIn | None = None):
    try:
        selected = body.selected_categories if body is not None else None
        return await run_in_threadpool(MANAGER.rescan_workspace, selected)
    except Exception as exc:
        _fail(exc)


@app.get("/api/workspace/defaults")
def workspace_defaults_get():
    try:
        return MANAGER.load_workspace_defaults()
    except Exception as exc:
        _fail(exc)


@app.put("/api/workspace/defaults")
def workspace_defaults_put(body: WorkspaceDefaultsIn):
    try:
        return MANAGER.save_workspace_defaults(body.model_dump())
    except Exception as exc:
        _fail(exc)


@app.post("/api/template")
async def create_template(body: TemplateIn):
    try:
        path = await run_in_threadpool(MANAGER.create_template, body.path)
        return {"path": path}
    except Exception as exc:
        _fail(exc)


@app.get("/api/settings")
def get_settings():
    return paths.load_settings().__dict__


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    current = paths.load_settings()
    if body.chrome_path is not None:
        current.chrome_path = body.chrome_path.strip()
    if body.chrome_profile is not None:
        current.chrome_profile = body.chrome_profile.strip()
    if body.cdp_port is not None:
        current.cdp_port = body.cdp_port
    if body.debug_browser is not None:
        current.debug_browser = body.debug_browser
    if body.sku_template_import is not None:
        current.sku_template_import = body.sku_template_import
    if body.skip_spec_images is not None:
        current.skip_spec_images = body.skip_spec_images
    if body.sku_image_strategy is not None:
        strategy = body.sku_image_strategy.strip()
        if strategy not in {"slim_material", "publish_page", "both"}:
            raise HTTPException(status_code=400, detail="sku_image_strategy 必须是 slim_material、publish_page 或 both")
        current.sku_image_strategy = strategy
    if body.settings_version is not None:
        current.settings_version = max(1, int(body.settings_version))
    if body.limit is not None:
        current.limit = body.limit
    if body.spec_upload_batch_size is not None:
        current.spec_upload_batch_size = body.spec_upload_batch_size
    if body.results_dir is not None:
        current.results_dir = body.results_dir.strip()
    saved = paths.save_settings(current)
    paths.apply_to_loaded_modules()
    try:
        MANAGER.apply_debug_browser(saved.debug_browser)
    except Exception:
        pass
    return saved.__dict__


@app.get("/api/job")
def job_state():
    snap = MANAGER.snapshot()
    snap["step"] = snap.get("phase") or ""
    return snap


@app.post("/api/job/start")
def job_start(body: JobStartIn):
    settings = paths.load_settings()
    limit = int(body.limit or settings.limit or 0)
    try:
        return MANAGER.start_job(
            confirm_submit=True,
            limit=limit,
            force_new=bool(body.force_new),
            retry_failed=bool(body.retry_failed),
        )
    except Exception as exc:
        _fail(exc)


@app.get("/api/job/history")
def job_history():
    try:
        return {"items": MANAGER.job_history()}
    except Exception as exc:
        _fail(exc)


@app.post("/api/job/stop")
def job_stop():
    return MANAGER.stop_job()


@app.post("/api/item/open")
def item_open(body: ItemOpenIn):
    try:
        return MANAGER.open_item(body.row, body.product_id, body.action)
    except Exception as exc:
        _fail(exc)


@app.post("/api/item/clear")
def item_clear(body: ItemClearIn):
    try:
        return MANAGER.clear_row_state(body.row, body.product_id)
    except Exception as exc:
        _fail(exc)


def mount_frontend(application: FastAPI) -> None:
    directory = paths.web_dir()
    index = directory / "index.html"
    if not index.is_file():
        dev = Path(__file__).resolve().parent / "ui" / "dist" / "index.html"
        if dev.is_file():
            directory = dev.parent
            index = dev
    if index.is_file():
        application.mount("/", StaticFiles(directory=str(directory), html=True), name="web")
        return

    @application.get("/")
    def missing_ui():
        return {
            "ok": True,
            "message": "前端尚未打包。开发时请先在 desktop/ui 执行 npm run build，或使用 npm run dev 并打开 Vite。",
        }


mount_frontend(app)


@app.middleware("http")
async def no_cache_html(request, call_next):
    # index.html 必须每次回源校验：资源文件名带 hash 可长缓存，
    # 但 index.html 被缓存会让前端更新后仍显示旧界面。
    response = await call_next(request)
    if request.url.path in {"/", "/index.html"}:
        response.headers["Cache-Control"] = "no-cache"
    return response


def pick_free_port() -> int:
    import socket

    env = os.environ.get("QIANNIU_PORT")
    if env:
        return int(env)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def run_server(port: int) -> None:
    import uvicorn

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server.run()
