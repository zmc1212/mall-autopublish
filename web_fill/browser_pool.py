"""Cross-process ownership for Playwright pages used by parallel workers.

The Playwright CLI exposes a current page per daemon, while the connected
Chrome instance contains all workers' pages.  This module keeps a small,
file-backed ownership registry so a worker can prove that a page belongs to
its current item before selecting or closing it.  It deliberately does not
discover or close pages on its own; callers must provide the page identity and
decide when a protected page may be released.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
import threading
import time
import uuid


_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def default_registry_path(output_dir: str | os.PathLike[str] | None = None) -> Path:
    """Return the registry path shared by worker output directories.

    Workers normally receive ``output/playwright/workers/<id>``.  Placing the
    registry beside that directory gives every worker the same file while
    keeping ordinary CLI artifacts isolated.  An explicit environment value is
    useful for packaged deployments whose output root is relocated.
    """

    configured = str(os.environ.get("QIANNIU_BROWSER_REGISTRY") or "").strip()
    if configured:
        return Path(configured).resolve()
    directory = Path(output_dir or Path.cwd()).resolve()
    return directory.parent / "browser_ownership.json"


@dataclass
class PageLease:
    """The stable ownership record for one browser page."""

    owner: str
    key: str
    marker: str
    session_name: str
    index: int | None = None
    target_id: str = ""
    url: str = ""
    protected: bool = False
    created_at: float = 0.0
    # ``active`` means that the owner may still issue commands.  A detached
    # worker parks its leases before leaving; a later run may then atomically
    # hand them to a new owner.  An active lease from a live process remains
    # unclaimable, even when its session name belongs to an older run.
    state: str = "active"
    pid: int = 0
    epoch: str = ""

    def __post_init__(self) -> None:
        if any(not str(getattr(self, field) or "").strip()
               for field in ("owner", "key", "marker", "session_name")):
            raise ValueError("页面租约缺少 owner/key/marker/session_name")
        if self.state not in {"active", "parked"}:
            raise ValueError(f"页面租约 state 无效: {self.state}")
        if not self.created_at:
            self.created_at = time.time()

    @classmethod
    def new(cls, owner: str, key: str, session_name: str, **values: object) -> "PageLease":
        return cls(
            owner=str(owner),
            key=str(key),
            marker=str(values.pop("marker", "") or f"qn-page-{uuid.uuid4().hex}"),
            session_name=str(session_name),
            **values,
        )

    @classmethod
    def from_dict(cls, value: dict) -> "PageLease":
        fields = {
            "owner", "key", "marker", "session_name", "index", "target_id",
            "url", "protected", "created_at", "state", "pid", "epoch",
        }
        return cls(**{field: value.get(field) for field in fields if field in value})

    def as_dict(self) -> dict:
        return asdict(self)


@contextmanager
def _file_lock(path: Path):
    """Lock a one-byte sidecar file on Windows and POSIX."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(str(path), threading.RLock())
    with process_lock:
        with path.open("a+b") as stream:
            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _process_alive(pid: int) -> bool:
    """Return whether a recorded worker process is still running.

    Missing/zero PIDs are treated as alive.  That conservative result keeps
    old registry records from being stolen silently; an explicit detach or a
    manual registry cleanup is required before those records can be handed
    over.
    """
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return True
    if value == os.getpid():
        return True
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is a POSIX existence probe.  On Windows it is
        # not a harmless equivalent: depending on the CRT/runtime it can
        # map to a process termination request.  Query the process handle
        # instead and fail closed when the OS will not let us inspect it.
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            ERROR_INVALID_PARAMETER = 87
            STILL_ACTIVE = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
            ]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, value
            )
            if not handle:
                error = ctypes.get_last_error()
                if error == ERROR_INVALID_PARAMETER:
                    return False
                # Access denied and unknown API failures are conservative:
                # leave the page protected until an explicit detach/cleanup.
                return True
            exit_code = wintypes.DWORD()
            try:
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # A locked-down Python/runtime should never turn an uninspectable
            # process into an automatically stealable page lease.
            return True
    try:
        os.kill(value, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class PageOwnershipRegistry:
    """Small JSON registry shared by worker threads/processes."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path or default_registry_path()).resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _read_unlocked(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"浏览器页面租约 registry 已损坏: {self.path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"浏览器页面租约 registry 格式无效: {self.path}")
        return value

    def _write_unlocked(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)

    @staticmethod
    def _records(value: dict) -> list[dict]:
        if "pages" not in value:
            return []
        records = value.get("pages")
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise RuntimeError("浏览器页面租约 registry 的 pages 字段无效")
        return records

    def list(self, *, owner: str | None = None, key: str | None = None) -> list[PageLease]:
        with _file_lock(self.lock_path):
            records = self._records(self._read_unlocked())
        result = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if owner is not None and str(record.get("owner") or "") != str(owner):
                continue
            if key is not None and str(record.get("key") or "") != str(key):
                continue
            try:
                result.append(PageLease.from_dict(record))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"浏览器页面租约 registry 记录无效: {self.path}") from exc
        return result

    def get(self, owner: str, key: str) -> PageLease | None:
        records = self.list(owner=owner, key=key)
        return records[0] if records else None

    def get_marker(self, marker: str) -> PageLease | None:
        marker = str(marker or "")
        if not marker:
            return None
        for lease in self.list():
            if lease.marker == marker:
                return lease
        return None

    def claim(self, lease: PageLease) -> PageLease:
        with _file_lock(self.lock_path):
            value = self._read_unlocked()
            records = self._records(value)
            for record in records:
                if not isinstance(record, dict):
                    continue
                try:
                    current = PageLease.from_dict(record)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(f"浏览器页面租约 registry 记录无效: {self.path}") from exc
                if record.get("marker") == lease.marker:
                    return current
                if (
                    str(record.get("owner") or "") != lease.owner
                    and str(record.get("key") or "") == lease.key
                ):
                    raise RuntimeError(f"商品页面已被其他 worker 占用: {lease.key}")
            records.append(lease.as_dict())
            value["version"] = 1
            value["pages"] = records
            self._write_unlocked(value)
        return lease

    def acquire_key(
        self,
        key: str,
        *,
        owner: str,
        session_name: str,
        pid: int = 0,
        epoch: str = "",
    ) -> list[PageLease]:
        """Atomically acquire all parked pages for one item.

        A key can have several pages (home/category/material/edit).  The
        caller must acquire them as one lifecycle unit so a second run cannot
        create a duplicate page while the first run is still active.  Active
        leases transfer only after their recorded process has exited; parked
        leases are the normal handoff path after ``finish_item(preserve=True)``
        or a clean daemon detach.
        """
        key = str(key or "")
        owner = str(owner or "")
        epoch = str(epoch or "")
        with _file_lock(self.lock_path):
            value = self._read_unlocked()
            records = self._records(value)
            matching = []
            for record in records:
                if not isinstance(record, dict) or str(record.get("key") or "") != key:
                    continue
                try:
                    current = PageLease.from_dict(record)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(f"浏览器页面租约 registry 记录无效: {self.path}") from exc
                same_owner = current.owner == owner
                same_epoch = bool(epoch) and current.epoch == epoch
                if same_owner and same_epoch and current.state == "active":
                    matching.append((record, current))
                    continue
                if current.state == "active" and _process_alive(current.pid):
                    raise RuntimeError(f"商品页面已被其他 active worker 占用: {key}")
                matching.append((record, current))

            if not matching:
                return []
            acquired = []
            for record, current in matching:
                current.owner = owner
                current.session_name = str(session_name)
                current.pid = int(pid or 0)
                current.epoch = epoch
                current.state = "active"
                # The page is active again; registry ownership itself protects
                # it from global pruning.  ``protected`` is reserved for a
                # parked/manual-review checkpoint.
                current.protected = False
                record.clear()
                record.update(current.as_dict())
                acquired.append(current)
            value["version"] = 1
            value["pages"] = records
            self._write_unlocked(value)
            return acquired

    def park_owner(self, owner: str, *, epoch: str | None = None, key: str | None = None,
                   protected: bool | None = None) -> list[PageLease]:
        """Mark an owner's pages unavailable for commands but resumable.

        This operation is intentionally short and atomic.  It is used before
        a CLI daemon detaches, so a future run can distinguish a cleanly
        released page from a live active worker.
        """
        owner = str(owner or "")
        epoch = str(epoch or "")
        key = None if key is None else str(key)
        with _file_lock(self.lock_path):
            value = self._read_unlocked()
            records = self._records(value)
            parked = []
            changed = False
            for record in records:
                if not isinstance(record, dict):
                    continue
                current = PageLease.from_dict(record)
                if current.owner != owner:
                    continue
                if epoch and current.epoch != epoch:
                    continue
                if key is not None and current.key != key:
                    continue
                current.state = "parked"
                if protected is not None:
                    current.protected = bool(protected)
                record.clear()
                record.update(current.as_dict())
                parked.append(current)
                changed = True
            if changed:
                value["version"] = 1
                value["pages"] = records
                self._write_unlocked(value)
            return parked

    def update(self, lease: PageLease, **changes: object) -> PageLease:
        with _file_lock(self.lock_path):
            value = self._read_unlocked()
            records = self._records(value)
            for index, record in enumerate(records):
                if isinstance(record, dict) and record.get("marker") == lease.marker:
                    current = PageLease.from_dict(record)
                    for key, change in changes.items():
                        if not hasattr(current, key):
                            raise ValueError(f"未知页面租约字段: {key}")
                        setattr(current, key, change)
                    records[index] = current.as_dict()
                    value["version"] = 1
                    value["pages"] = records
                    self._write_unlocked(value)
                    return current
            raise KeyError(f"页面租约不存在: {lease.marker}")

    def release(self, lease: PageLease, *, force: bool = False) -> bool:
        with _file_lock(self.lock_path):
            value = self._read_unlocked()
            records = self._records(value)
            kept = []
            removed = False
            for record in records:
                if not isinstance(record, dict) or record.get("marker") != lease.marker:
                    kept.append(record)
                    continue
                if bool(record.get("protected")) and not force:
                    raise RuntimeError("受保护页面不能释放")
                removed = True
            if removed:
                value["version"] = 1
                value["pages"] = kept
                self._write_unlocked(value)
            return removed

    def protect(self, lease: PageLease, protected: bool = True) -> PageLease:
        return self.update(lease, protected=bool(protected))

    @contextmanager
    def operation_lock(self):
        """Short cross-worker lock for tab-select/target-id transactions."""
        with _file_lock(self.lock_path.with_name(self.lock_path.name + ".ops")):
            yield

    def protected_urls(self) -> set[str]:
        return {
            lease.url.rstrip("/")
            for lease in self.list()
            if lease.protected and lease.url
        }

    def owned_urls(self) -> set[str]:
        """Return URLs for every live or parked lease.

        Global tab cleanup must preserve active leases as well as pages marked
        for review.  A worker can be between stages while its page is not yet
        marked protected; closing that page would destroy its resumable state.
        """
        leases = self.list()
        if any(not lease.url for lease in leases):
            raise RuntimeError(f"浏览器页面租约缺少 URL，禁止全局清理: {self.path}")
        return {lease.url.rstrip("/") for lease in leases}

    def protected_markers(self) -> set[str]:
        return {lease.marker for lease in self.list() if lease.protected}


__all__ = ["PageLease", "PageOwnershipRegistry", "default_registry_path"]
