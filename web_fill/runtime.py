"""Per-worker state; never change process environment from a filling thread."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable


class CheckpointError(RuntimeError):
    """A durable checkpoint failed, so no further remote writes are safe."""


@dataclass
class WorkerRuntime:
    worker_id: int
    row: Any
    product_id: str
    item_key: str
    output_dir: Path
    scripts_dir: Path
    logs_dir: Path
    session: Any = None
    seller_account: str = ""
    emit: Callable | None = None
    checkpoint: Callable | None = None
    latest_item: dict = field(default_factory=dict)
    pending_creation: bool = False

    def progress(self, phase, **extra):
        if self.emit:
            self.emit("progress", phase=phase, status="running", **extra)

    def save_checkpoint(self, item):
        self.latest_item.update(item)
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            target = self.output_dir / "item_checkpoint.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps({"item_key": self.item_key,
                                              "worker_id": self.worker_id,
                                              "item": self.latest_item}, ensure_ascii=False,
                                             indent=2, default=str), encoding="utf-8")
            temporary.replace(target)
        except OSError as exc:
            raise CheckpointError(f"PAUSE:任务断点保存失败，已停止继续写入: {exc}") from exc


_CURRENT = ContextVar("qianniu_worker_runtime", default=None)


def current_runtime():
    return _CURRENT.get()


@contextmanager
def worker_runtime(runtime):
    token = _CURRENT.set(runtime)
    try:
        yield runtime
    finally:
        _CURRENT.reset(token)
