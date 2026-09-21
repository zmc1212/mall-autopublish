"""本机 FastAPI：清单、任务、Chrome 连接、设置。仅绑定 127.0.0.1。"""

from __future__ import annotations

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
    confirm_submit: bool = False
    limit: int = Field(0, ge=0)
    force_new: bool = False
    retry_failed: bool = False


class WorkspaceIn(BaseModel):
    path: str


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


class SettingsIn(BaseModel):
    chrome_path: str | None = None
    chrome_profile: str | None = None
    cdp_port: int | None = Field(default=None, ge=1, le=65535)
    debug_browser: bool | None = None
    confirm_submit: bool | None = None
    limit: int | None = Field(default=None, ge=0)
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
        chrome = {"error": str(exc), "cdp": False, "logged_in": False, "chrome_found": False}
    job = MANAGER.snapshot()
    settings = paths.load_settings()
    try:
        workspace = MANAGER.workspace_info()
    except Exception:
        workspace = {"path": job.get("workspace_path") or "", "defaults": {}, "registry": {}}
    return {
        "chrome": chrome,
        "job": job,
        "workspace": workspace,
        "settings": {
            "chrome_path": settings.chrome_path,
            "chrome_profile": settings.chrome_profile,
            "cdp_port": settings.cdp_port,
            "debug_browser": settings.debug_browser,
            "confirm_submit": settings.confirm_submit,
            "limit": settings.limit,
            "results_dir": settings.results_dir,
        },
    }


@app.post("/api/chrome/open")
async def chrome_open():
    try:
        return await run_in_threadpool(MANAGER.open_chrome)
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
        return await run_in_threadpool(MANAGER.import_workbook, MANAGER.workbook_path)
    except Exception as exc:
        _fail(exc)


@app.post("/api/workspace/open")
async def workspace_open(body: WorkspaceIn):
    try:
        return await run_in_threadpool(MANAGER.open_workspace, body.path)
    except Exception as exc:
        _fail(exc)


@app.post("/api/workspace/rescan")
async def workspace_rescan():
    try:
        return await run_in_threadpool(MANAGER.rescan_workspace)
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
    if body.confirm_submit is not None:
        current.confirm_submit = body.confirm_submit
    if body.limit is not None:
        current.limit = body.limit
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
    confirm = bool(body.confirm_submit)
    limit = int(body.limit or settings.limit or 0)
    try:
        return MANAGER.start_job(
            confirm_submit=confirm,
            limit=limit,
            force_new=bool(body.force_new),
            retry_failed=bool(body.retry_failed),
        )
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
