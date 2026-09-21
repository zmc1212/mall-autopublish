"""加载中文文件名模块，兼容源码运行与 PyInstaller。"""

from __future__ import annotations

import importlib
import importlib.util
import sys

from .paths import find_resource, project_root


def load_named(module_name: str, filename: str):
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    path = find_resource(filename)
    if not path.is_file():
        path = project_root() / filename
    if path.is_file():
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 {filename}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(module_name)


def load_seller():
    return load_named("千牛自动上架", "千牛自动上架.py")


def load_web():
    return load_named("千牛网页执行", "千牛网页执行.py")


def load_parser():
    return load_named("商品解析", "商品解析.py")


def load_workspace():
    return load_named("workspace", "workspace.py")
