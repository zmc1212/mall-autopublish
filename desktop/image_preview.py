"""入库列表商品主图预览。

预览只读当前商品的图片包，不参与校验、上传或入库。目录图片沿用
``商品解析.scan_image_pack`` 的命名和分组规则；ZIP 会先在一次性临时目录
中安全解包，再调用同一个解析器，避免预览规则和真实入库选图规则分叉。
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from 商品解析 import IMAGE_EXTS, scan_image_pack


MAX_PREVIEW_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
_PREVIEW_CACHE = {}
_PREVIEW_CACHE_LOCK = threading.RLock()
_MAX_PREVIEW_CACHE = 512
_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_MAIN_ONE_RE = re.compile(r"(?<!\d)主图0*1(?!\d)")


class PreviewUnavailable(FileNotFoundError):
    """商品当前没有可供列表预览的主图。"""


@dataclass(frozen=True)
class PreviewRef:
    """可安全读取的预览图片引用。"""

    name: str
    media_type: str
    kind: str
    path: Path | None = None
    archive_path: Path | None = None
    archive_member: str = ""


@dataclass(frozen=True)
class PreviewPayload:
    name: str
    media_type: str
    data: bytes


def _cache_put(key, value) -> None:
    with _PREVIEW_CACHE_LOCK:
        if len(_PREVIEW_CACHE) >= _MAX_PREVIEW_CACHE:
            _PREVIEW_CACHE.pop(next(iter(_PREVIEW_CACHE)))
        _PREVIEW_CACHE[key] = value


def _file_signature(path: Path):
    try:
        stat = path.stat()
    except OSError:
        return (str(path), "missing")
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _pack_signature(product, pack_fingerprint=""):
    product = product or {}
    raw_pack = str(product.get("pack_dir") or "").strip()
    parts = [str(pack_fingerprint or "").strip()]
    if raw_pack:
        pack = Path(raw_pack)
        parts.append(_file_signature(pack))
    for key in ("main_images", "portrait_images"):
        for raw in product.get(key) or []:
            parts.append(_file_signature(Path(str(raw))))
    return parts


def is_supported_pack_path(value) -> bool:
    """判断清单里的图片包是否是可预览的目录或 ZIP 文件。"""

    if not value:
        return False
    path = Path(str(value).strip())
    return path.is_dir() or (path.is_file() and path.suffix.lower() == ".zip")


def preview_cache_token(product, pack_fingerprint="") -> str:
    """返回不会暴露本地路径且包含主图 stat 的预览缓存版本标记。"""

    parts = _pack_signature(product, pack_fingerprint)
    try:
        ref = locate_preview(product, pack_fingerprint)
    except PreviewUnavailable:
        ref = None
    if ref is not None and ref.path is not None:
        # 未解析 main_images 的旧清单也必须感知主图原地替换；目录 mtime
        # 只在新增/删除文件时变化，不能单独作为图片内容的缓存版本。
        parts.append(_file_signature(ref.path))
    raw = repr(parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _media_type(path_or_name) -> str:
    suffix = Path(str(path_or_name)).suffix.lower()
    return _IMAGE_MEDIA_TYPES.get(suffix, mimetypes.guess_type(str(path_or_name))[0] or "")


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _valid_image_path(path: Path, root: Path | None = None) -> bool:
    if path.suffix.lower() not in IMAGE_EXTS or path.is_symlink() or not path.is_file():
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if root is not None:
        try:
            root_resolved = root.resolve()
        except OSError:
            return False
        if not _inside(root_resolved, resolved):
            return False
    return bool(_media_type(path))


def _pick_scanned_image(pack, root: Path) -> Path | None:
    """按实际上传顺序取第一张 1:1 主图，没有时退回 3:4 主图。"""

    return _fallback_product_image({
        "main_images": pack.get("main_1_1") or [],
        "portrait_images": pack.get("main_3_4") or [],
    }, root)


def _scan_directory(folder: Path) -> Path | None:
    try:
        pack = scan_image_pack(folder)
    except (OSError, ValueError):
        return None
    return _pick_scanned_image(pack, folder)


def _fallback_product_image(product, pack_path: Path | None = None) -> Path | None:
    """兼容没有图片包目录的旧清单，但仍限制到图片扩展名和真实文件。"""

    root = pack_path if pack_path is not None and pack_path.is_dir() else None
    candidates = []
    for key in ("main_images", "portrait_images"):
        for raw in (product or {}).get(key) or []:
            path = Path(str(raw))
            if _valid_image_path(path, root):
                candidates.append(path)
    if not candidates:
        return None
    # resolve_product 已按 scan_image_pack 排好顺序；这里仍显式优先主图01，
    # 兼容旧清单或调用方自行传入未排序的 main_images。
    exact_main = next((path for path in candidates if re.match(r"^主图0*1(?!\d)", path.stem)), None)
    return exact_main or next((path for path in candidates if _MAIN_ONE_RE.search(path.stem)), candidates[0])


def _zip_image_entries(archive: zipfile.ZipFile):
    try:
        infos = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        return []
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        return []
    entries = []
    total = 0
    for info in infos:
        name = str(info.filename or "").replace("\\", "/")
        if not name or name.endswith("/"):
            continue
        pure = PurePosixPath(name)
        # 只允许普通相对文件名；忽略软链接和 ..，不让 ZIP 影响临时目录之外的路径。
        if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
            continue
        if any(":" in part for part in pure.parts):
            continue
        mode = (int(info.external_attr) >> 16) & 0o170000
        if mode == 0o120000:
            continue
        if Path(name).suffix.lower() not in IMAGE_EXTS:
            continue
        size = int(info.file_size or 0)
        if size < 0 or size > MAX_PREVIEW_BYTES or total + size > MAX_ARCHIVE_BYTES:
            continue
        total += size
        entries.append((info, "/".join(pure.parts)))
    return entries


def _extract_zip_images(archive: zipfile.ZipFile, root: Path):
    extracted = []
    for info, member in _zip_image_entries(archive):
        parts = PurePosixPath(member).parts
        target = root.joinpath(*parts)
        try:
            target_parent = target.parent.resolve()
            root_resolved = root.resolve()
        except OSError:
            continue
        if not _inside(root_resolved, target_parent):
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
        except (OSError, RuntimeError, zipfile.BadZipFile):
            continue
        if _valid_image_path(target, root):
            extracted.append((target, member))
    return extracted


def _zip_selected_member(archive_path: Path) -> tuple[str, str] | None:
    try:
        with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(prefix="qianniu-preview-") as temp:
            extracted = _extract_zip_images(archive, Path(temp))
            if not extracted:
                return None
            by_directory = {}
            for path, member in extracted:
                by_directory.setdefault(path.parent, []).append((path, member))
            # 典型 ZIP 是“商品文件夹/主图01.jpg”；也兼容 ZIP 根目录直接放图。
            folders = sorted(by_directory, key=lambda item: (len(item.relative_to(Path(temp)).parts), str(item).lower()))
            for folder in folders:
                selected = _scan_directory(folder)
                if selected is None:
                    continue
                member = next((member for path, member in by_directory[folder] if path == selected), "")
                if member:
                    return member, selected.name
    except (OSError, zipfile.BadZipFile):
        return None
    return None


def _cache_key(product, pack_fingerprint=""):
    """生成轻量源快照键；ZIP 命中后不需要再次解压。"""

    product = product or {}
    raw_pack = str(product.get("pack_dir") or "").strip()
    if not raw_pack and not (product.get("main_images") or product.get("portrait_images")):
        return None
    try:
        pack = str(Path(raw_pack).resolve()) if raw_pack else ""
    except OSError:
        pack = raw_pack
    # 定位缓存只依赖源列表/目录/ZIP 的元数据；面向浏览器的版本另加所选图片
    # 的 stat，避免为了生成 URL 再次扫描图片包。
    return pack, hashlib.sha256(repr(_pack_signature(product, pack_fingerprint)).encode("utf-8", errors="replace")).hexdigest()


def _locate_preview_uncached(product) -> PreviewRef:
    product = product or {}
    raw_pack = str(product.get("pack_dir") or "").strip()
    pack_path = Path(raw_pack) if raw_pack else None
    if pack_path is not None and pack_path.is_dir():
        # validate_workbook/resolve_product 已按 scan_image_pack 解析过主图；
        # 优先复用 main_images，避免每次 /status 轮询都扫描目录和读取尺寸。
        fallback = _fallback_product_image(product, pack_path)
        if fallback is not None:
            return PreviewRef(fallback.name, _media_type(fallback), "file", path=fallback)
        selected = _scan_directory(pack_path)
        if selected is not None:
            return PreviewRef(selected.name, _media_type(selected), "file", path=selected)
    elif pack_path is not None and pack_path.is_file() and pack_path.suffix.lower() == ".zip":
        selected = _zip_selected_member(pack_path)
        if selected is not None:
            member, name = selected
            return PreviewRef(name, _media_type(name), "zip", archive_path=pack_path, archive_member=member)
        fallback = _fallback_product_image(product)
        if fallback is not None:
            return PreviewRef(fallback.name, _media_type(fallback), "file", path=fallback)
    else:
        fallback = _fallback_product_image(product, pack_path)
        if fallback is not None:
            return PreviewRef(fallback.name, _media_type(fallback), "file", path=fallback)
    raise PreviewUnavailable("图片包内没有可预览的主图")


def locate_preview(product, pack_fingerprint="") -> PreviewRef:
    """解析商品图片包并返回不含客户端路径输入的安全引用。"""

    key = _cache_key(product, pack_fingerprint)
    if key is not None:
        with _PREVIEW_CACHE_LOCK:
            if key in _PREVIEW_CACHE:
                cached = _PREVIEW_CACHE[key]
                if cached is None:
                    raise PreviewUnavailable("图片包内没有可预览的主图")
                return cached
    try:
        ref = _locate_preview_uncached(product)
    except PreviewUnavailable:
        if key is not None:
            _cache_put(key, None)
        raise
    if key is not None:
        _cache_put(key, ref)
    return ref


def _read_file_limited(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            data = source.read(MAX_PREVIEW_BYTES + 1)
    except OSError as exc:
        raise PreviewUnavailable("主图暂时无法读取") from exc
    if len(data) > MAX_PREVIEW_BYTES:
        raise PreviewUnavailable("主图文件过大")
    return data


def read_preview(product, pack_fingerprint="") -> PreviewPayload:
    """读取预览图片内容；超出大小或图片包异常时按不可用处理。"""

    ref = locate_preview(product, pack_fingerprint)
    if ref.kind == "file" and ref.path is not None:
        data = _read_file_limited(ref.path)
    elif ref.kind == "zip" and ref.archive_path is not None:
        try:
            with zipfile.ZipFile(ref.archive_path) as archive:
                with archive.open(ref.archive_member, "r") as source:
                    data = source.read(MAX_PREVIEW_BYTES + 1)
        except (OSError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
            raise PreviewUnavailable("图片包暂时无法读取") from exc
    else:
        raise PreviewUnavailable("图片包内没有可预览的主图")
    if len(data) > MAX_PREVIEW_BYTES:
        raise PreviewUnavailable("主图文件过大")
    return PreviewPayload(ref.name, ref.media_type, data)


def preview_metadata(product, pack_fingerprint="") -> dict:
    try:
        ref = locate_preview(product, pack_fingerprint)
    except PreviewUnavailable:
        return {
            "available": False,
            "name": "",
            "media_type": "",
            "cache_token": preview_cache_token(product, pack_fingerprint),
        }
    return {
        "available": True,
        "name": ref.name,
        "media_type": ref.media_type,
        "cache_token": preview_cache_token(product, pack_fingerprint),
    }

