"""发码工具（仅开发者使用，绝不随软件分发）。

双击 dist\\千牛发码工具.exe 或 发码工具.bat 打开图形界面；
命令行模式保留备用：

  python tools/license_keygen.py generate-keys     首次使用：生成私钥，输出需内置的公钥
  python tools/license_keygen.py issue --machine-code XXXX-XXXX-XXXX-XXXX [--days 365] [--memo 客户A]
  python tools/license_keygen.py gui               图形界面发码
  python tools/license_keygen.py selftest          自检（RFC 8032 测试向量 + 签发验证闭环）

私钥默认保存在 %USERPROFILE%\\.qianniu-license\\private.key（仓库之外），
丢失后无法再为已有客户补发，泄露后需换钥并重新内置公钥。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop import license as lic  # noqa: E402
from desktop import license_service as service  # noqa: E402

_HEX = set("0123456789ABCDEF")


def key_dir() -> Path:
    override = os.environ.get("QIANNIU_LICENSE_KEY_DIR")
    base = Path(override) if override else Path.home() / ".qianniu-license"
    base.mkdir(parents=True, exist_ok=True)
    return base


def private_key_path() -> Path:
    return key_dir() / "private.key"


def load_private_seed(path: Path | None = None) -> bytes:
    path = path or private_key_path()
    if not path.is_file():
        raise FileNotFoundError(f"未找到私钥文件：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        seed = base64.b64decode(str(data.get("seed") or ""))
    except Exception as exc:
        raise ValueError(f"私钥文件损坏：{path}（{exc}）")
    if len(seed) != 32:
        raise ValueError(f"私钥文件内容异常：{path}")
    return seed


def generate_keypair() -> tuple[Path, bytes]:
    """生成新密钥对；返回 (私钥路径, 公钥原始字节)。已存在时抛 FileExistsError。"""
    path = private_key_path()
    if path.exists():
        raise FileExistsError(str(path))
    seed = os.urandom(32)
    public = lic.ed25519_public_key(seed)
    path.write_text(
        json.dumps(
            {
                "seed": base64.b64encode(seed).decode("ascii"),
                "public": base64.b64encode(public).decode("ascii"),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path, public


def import_keypair(source: Path) -> tuple[Path, bytes]:
    """从备份导入私钥：校验格式后复制到默认位置，返回 (路径, 公钥)。"""
    seed = load_private_seed(source)
    target = private_key_path()
    if target.exists():
        raise FileExistsError(str(target))
    shutil.copyfile(source, target)
    return target, lic.ed25519_public_key(seed)


def normalize_machine_code(text: str) -> str:
    cleaned = "".join(ch for ch in str(text).upper() if ch in _HEX)
    if len(cleaned) != 16:
        raise ValueError("机器码应为 16 位，形如 XXXX-XXXX-XXXX-XXXX（请让客户从激活页复制）。")
    return cleaned


def issue_code(machine_code: str, days: int, memo: str) -> tuple[str, dict]:
    seed = load_private_seed()
    fingerprint = normalize_machine_code(machine_code)
    days = max(0, int(days or 0))
    payload = {
        "v": 1,
        "fp": fingerprint,
        "exp": int(time.time()) + days * 86400 if days else 0,
        "memo": str(memo or "").strip()[:40],
    }
    return lic.build_code(payload, seed), payload


def append_history(payload: dict, code: str, days: int, *, registered: bool = False) -> None:
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "machine_code": "-".join(payload["fp"][i : i + 4] for i in range(0, 16, 4)),
        "days": days if days else "永久",
        "expires_at": payload["exp"],
        "memo": payload["memo"],
        "code": code,
        "registered": bool(registered),
        "revoked": False,
    }
    history = key_dir() / "history.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_history_status(code: str, revoked: bool) -> None:
    """把本机流水里的吊销状态与授权服务同步，便于发码时一眼看到。"""
    history = key_dir() / "history.jsonl"
    if not history.is_file():
        return
    records = load_history()
    changed = False
    for record in records:
        if str(record.get("code") or "").strip() == str(code or "").strip():
            record["revoked"] = bool(revoked)
            changed = True
    if not changed:
        return
    temp = history.with_suffix(".tmp")
    temp.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    os.replace(temp, history)


def register_code(payload: dict, code: str) -> tuple[bool, str]:
    """发码时同步登记到授权服务；失败不阻塞发码，但会明确提示。"""
    try:
        service.register(
            code,
            fingerprint=payload["fp"],
            expires_at=int(payload.get("exp") or 0),
            memo=payload.get("memo") or "",
        )
    except service.LicenseServiceError as exc:
        return False, f"未登记到授权服务：{exc}"
    return True, "已登记到授权服务（可吊销）"


def revoked_text(record: dict) -> str:
    return "已停用" if record.get("revoked") else "正常"


def load_history() -> list[dict]:
    """读取全部签发流水（按签发时间正序）；损坏行跳过。"""
    history = key_dir() / "history.jsonl"
    if not history.is_file():
        return []
    try:
        lines = history.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("code"):
            records.append(rec)
    return records


def validity_text(rec: dict) -> str:
    expires_at = int(rec.get("expires_at") or 0)
    if expires_at:
        return "到期 " + datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d")
    if rec.get("days") == "永久":
        return "永久"
    return "—"


def filter_history(records: list[dict], query: str) -> list[dict]:
    """按时间 / 机器码 / 备注模糊过滤（大小写不敏感）。"""
    text = str(query or "").strip().lower()
    if not text:
        return records
    return [
        rec
        for rec in records
        if text in str(rec.get("time", "")).lower()
        or text in str(rec.get("machine_code", "")).lower()
        or text in str(rec.get("memo", "")).lower()
    ]


def embedded_public_key() -> bytes:
    return base64.b64decode(lic.PUBLIC_KEY_B64)


# ---------------------------------------------------------------------------
# 命令行模式
# ---------------------------------------------------------------------------
def cmd_generate_keys(_args) -> int:
    try:
        path, public = generate_keypair()
    except FileExistsError:
        print(f"私钥已存在，拒绝覆盖：{private_key_path()}")
        print("如确需更换密钥，请手动删除该文件，并重新内置公钥后给所有客户重新发码。")
        return 1
    print(f"私钥已生成：{path}")
    print("请立即备份并妥善保管：丢失后无法补发激活码；泄露后须换钥重发。")
    print()
    print("请把下面这行公钥填入 desktop/license.py 的 PUBLIC_KEY_B64：")
    print(base64.b64encode(public).decode("ascii"))
    print()
    if lic.PUBLIC_KEY_B64 != base64.b64encode(public).decode("ascii"):
        print("注意：desktop/license.py 当前内置的公钥与本私钥不匹配，需更新后再打包。")
    return 0


def cmd_issue(args) -> int:
    try:
        code, payload = issue_code(args.machine_code, args.days, args.memo)
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1
    print("激活码（请整段复制发给客户）：")
    print(code)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(code + "\n", encoding="utf-8")
        print(f"已写入文件：{out_path}")
    if args.no_register:
        registered, note = False, "已跳过授权服务登记（该码无法远程吊销）"
    else:
        registered, note = register_code(payload, code)
    append_history(payload, code, max(0, int(args.days or 0)), registered=registered)
    print(note)
    print(f"已记录签发流水：{key_dir() / 'history.jsonl'}")
    return 0


def _find_history_code(code: str) -> str:
    """允许只输入机器码/备注前缀时，取最近一条匹配记录。"""
    text = str(code or "").strip()
    records = load_history()
    for record in reversed(records):
        if str(record.get("code") or "") == text:
            return text
    matches = [r for r in records if text and text in str(r.get("code") or "")]
    return str(matches[-1].get("code")) if matches else text


def cmd_revoke(args) -> int:
    code = _find_history_code(args.code)
    try:
        service.revoke(code)
    except service.LicenseServiceError as exc:
        print(f"吊销失败：{exc}")
        return 1
    update_history_status(code, True)
    print("已吊销：客户下次心跳（最长 6 小时）或重新打开软件后失效。")
    return 0


def cmd_unrevoke(args) -> int:
    code = _find_history_code(args.code)
    try:
        service.unrevoke(code)
    except service.LicenseServiceError as exc:
        print(f"恢复失败：{exc}")
        return 1
    update_history_status(code, False)
    print("已恢复授权。")
    return 0


def cmd_rebind(args) -> int:
    code = _find_history_code(args.code)
    try:
        service.rebind(code)
    except service.LicenseServiceError as exc:
        print(f"换绑失败：{exc}")
        return 1
    print("已解绑全部设备，客户可在新设备上重新激活。")
    return 0


def cmd_lookup(args) -> int:
    code = _find_history_code(args.code)
    try:
        data = service.lookup(code)
    except service.LicenseServiceError as exc:
        print(f"查询失败：{exc}")
        return 1
    print(json.dumps(data.get("record") or data, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_args) -> int:
    failures: list[str] = []

    def expect(condition: bool, name: str) -> None:
        print(f"  {'通过' if condition else '失败'}：{name}")
        if not condition:
            failures.append(name)

    print("[1] RFC 8032 标准测试向量")
    vectors = [
        (
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
            b"",
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
        ),
        (
            "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
            "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
            bytes([0x72]),
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
        ),
    ]
    for index, (seed_hex, public_hex, message, signature_hex) in enumerate(vectors, 1):
        seed = bytes.fromhex(seed_hex)
        public = lic.ed25519_public_key(seed)
        signature = lic.ed25519_sign(seed, message)
        expect(
            public == bytes.fromhex(public_hex)
            and signature == bytes.fromhex(signature_hex)
            and lic.ed25519_verify(public, message, signature),
            f"测试向量 {index}（公钥/签名/验证）",
        )
        tampered = bytearray(signature)
        tampered[0] ^= 0x01
        expect(
            not lic.ed25519_verify(public, message, bytes(tampered)),
            f"测试向量 {index}（篡改签名被拒绝）",
        )

    print("[2] 签发与验证闭环")
    seed = os.urandom(32)
    public = lic.ed25519_public_key(seed)
    payload = {"v": 1, "fp": "0123456789ABCDEF", "exp": int(time.time()) + 3600, "memo": "自检"}
    code = lic.build_code(payload, seed)
    expect(lic.check_signature(code, public).get("fp") == "0123456789ABCDEF", "签发后验签通过")
    expect(
        lic.normalize_code(code.lower().replace("-", " \n ")) == lic.normalize_code(code),
        "小写/横线/空白清洗后内容一致",
    )

    print("[3] 异常输入全部拒绝")
    tampered_payload = code.replace(code[10], "A" if code[10] != "A" else "B", 1)
    try:
        lic.check_signature(tampered_payload, public)
        expect(False, "篡改激活码被拒绝")
    except lic.LicenseError:
        expect(True, "篡改激活码被拒绝")
    other_key = os.urandom(32)
    try:
        lic.check_signature(code, other_key)
        expect(False, "错误公钥被拒绝")
    except lic.LicenseError:
        expect(True, "错误公钥被拒绝")
    try:
        lic.verify_code(code, public)
        expect(False, "非本机机器码被拒绝")
    except lic.LicenseError:
        expect(True, "非本机机器码被拒绝")

    local_payload = {**payload, "fp": lic._fingerprint(lic.machine_code())}
    local_code = lic.build_code(local_payload, seed)
    expired_payload = {**local_payload, "exp": int(time.time()) - 10}
    try:
        lic.verify_code(lic.build_code(expired_payload, seed), public)
        expect(False, "过期激活码被拒绝")
    except lic.LicenseError as exc:
        expect("过期" in str(exc), "过期激活码被拒绝")
    expect(lic.check_signature(local_code, public).get("memo") == "自检", "本机码+备注签发可验签")

    print()
    if failures:
        print(f"自检失败 {len(failures)} 项：{'、'.join(failures)}")
        return 1
    print("自检全部通过。")
    return 0


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------
def cmd_gui(_args) -> int:
    root = tk.Tk()
    root.withdraw()

    # 私钥就绪检查：缺失走首次向导，异常弹窗退出（窗口化运行没有控制台可看）
    if private_key_path().is_file():
        try:
            load_private_seed()
        except (FileNotFoundError, ValueError) as exc:
            messagebox.showerror("发码工具", str(exc), parent=root)
            return 1
    else:
        choice = _first_run_dialog(root)
        if choice is None:
            return 0
        try:
            if choice == "generate":
                path, public = generate_keypair()
            else:
                source = filedialog.askopenfilename(
                    title="选择私钥备份文件",
                    filetypes=[("私钥文件", "*.key"), ("所有文件", "*.*")],
                    parent=root,
                )
                if not source:
                    return 0
                path, public = import_keypair(Path(source))
        except Exception as exc:
            messagebox.showerror("发码工具", f"私钥准备失败：{exc}", parent=root)
            return 1
        if choice == "generate":
            _show_public_key_dialog(root, base64.b64encode(public).decode("ascii"), path)

    _build_main_window(root)
    root.mainloop()
    return 0


def _first_run_dialog(parent) -> str | None:
    """首次使用向导：返回 "generate" / "import" / None（退出）。"""
    dialog = tk.Toplevel(parent)
    dialog.title("发码工具 · 首次使用")
    dialog.resizable(False, False)
    dialog.grab_set()
    result = {"choice": None}

    def choose(value: str | None) -> None:
        result["choice"] = value
        dialog.destroy()

    frame = ttk.Frame(dialog, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="未找到发码私钥。", font=("", 11, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="首次使用请生成新私钥；从别的电脑迁移过来可导入备份。\n"
        "私钥保存在本机用户目录，绝不随软件分发，请务必备份。",
        wraplength=360,
        justify="left",
    ).pack(anchor="w", pady=(6, 14))
    buttons = ttk.Frame(frame)
    buttons.pack()
    ttk.Button(buttons, text="生成新私钥", command=lambda: choose("generate")).pack(
        side="left", padx=4
    )
    ttk.Button(buttons, text="导入备份私钥…", command=lambda: choose("import")).pack(
        side="left", padx=4
    )
    ttk.Button(buttons, text="退出", command=lambda: choose(None)).pack(side="left", padx=4)
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    dialog.wait_window()
    return result["choice"]


def _show_public_key_dialog(parent, public_b64: str, key_path: Path) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("私钥已生成")
    dialog.resizable(False, False)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text=f"私钥已保存到：\n{key_path}\n\n请立即备份（丢失后无法补发激活码）。",
        justify="left",
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text="新私钥需与软件配套才能生效：把下面公钥填入 desktop/license.py\n"
        "的 PUBLIC_KEY_B64，然后重新打包软件，否则客户端验签会失败。",
        wraplength=380,
        justify="left",
        foreground="#B91C1C",
    ).pack(anchor="w", pady=(10, 6))

    text = tk.Text(frame, height=3, width=52, wrap="char", font=("Consolas", 9))
    text.insert("1.0", public_b64)
    text.configure(state="disabled")
    text.pack(fill="x")

    def copy_key() -> None:
        dialog.clipboard_clear()
        dialog.clipboard_append(public_b64)
        dialog.update()

    ttk.Button(frame, text="复制公钥", command=copy_key).pack(anchor="e", pady=(8, 0))
    ttk.Button(frame, text="完成", command=dialog.destroy).pack(anchor="e", pady=(4, 0))
    dialog.wait_window()


def _build_main_window(root) -> None:
    root.title("千牛自动上架 · 发码工具")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frame, text="客户机器码：").grid(row=0, column=0, sticky="w", pady=4)
    machine_var = tk.StringVar()
    machine_entry = tk.Entry(
        frame, textvariable=machine_var, width=30, font=("Consolas", 11)
    )
    machine_entry.grid(row=0, column=1, columnspan=2, sticky="we", pady=4)

    ttk.Label(frame, text="有效天数：").grid(row=1, column=0, sticky="w", pady=4)
    # 默认限期：永久码在客户退款后无法收回，仅在明确要求时手动改为 0。
    days_var = tk.StringVar(value="365")
    days_box = ttk.Combobox(frame, textvariable=days_var, width=7, values=("365", "180", "90", "30", "0"))
    days_box.grid(row=1, column=1, sticky="w", pady=4)
    ttk.Label(frame, text="默认 365 天；0 = 永久（退款后无法收回，慎用）").grid(row=1, column=2, sticky="w", padx=(8, 0))

    ttk.Label(frame, text="客户备注：").grid(row=2, column=0, sticky="w", pady=4)
    memo_var = tk.StringVar()
    ttk.Entry(frame, textvariable=memo_var, width=30).grid(
        row=2, column=1, columnspan=2, sticky="we", pady=4
    )

    status_var = tk.StringVar(value="粘贴客户发来的机器码，点击生成。")
    ttk.Label(frame, textvariable=status_var, foreground="#0F766E").grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(8, 4)
    )

    output = tk.Text(frame, height=6, width=66, wrap="char", state="disabled", font=("Consolas", 9))
    output.grid(row=4, column=0, columnspan=3, sticky="we", pady=4)

    def show_code(code: str) -> None:
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", code)
        output.configure(state="disabled")

    def on_issue() -> None:
        try:
            days_text = days_var.get().strip()
            if not days_text:
                raise ValueError("请填写有效天数；0 表示永久（退款后无法收回）")
            if not days_text.isdigit():
                raise ValueError("有效天数应为非负整数。")
            if int(days_text) == 0 and not messagebox.askyesno(
                "确认签发永久激活码",
                "永久激活码在客户退款后无法收回，只能依赖远程吊销。\n\n确定要签发永久码吗？",
                parent=root,
            ):
                return
            code, payload = issue_code(machine_var.get(), int(days_text), memo_var.get())
        except ValueError as exc:
            messagebox.showerror("发码失败", str(exc), parent=root)
            return
        except FileNotFoundError as exc:
            messagebox.showerror("发码失败", str(exc), parent=root)
            return
        show_code(code)
        root.clipboard_clear()
        root.clipboard_append(code)
        root.update()
        if service.server_url():
            registered, note = register_code(payload, code)
        else:
            registered, note = False, "未配置授权服务（该码无法远程吊销）"
        append_history(payload, code, int(days_text), registered=registered)
        refresh_history()
        status_var.set(f"激活码已复制到剪贴板；{note}。")

    def on_copy() -> None:
        output.configure(state="normal")
        text = output.get("1.0", "end").strip()
        output.configure(state="disabled")
        if not text:
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        status_var.set("已复制。")

    def on_open_history_dir() -> None:
        try:
            os.startfile(str(key_dir()))  # type: ignore[attr-defined]
        except OSError:
            messagebox.showinfo("发码工具", f"流水目录：{key_dir()}", parent=root)

    ttk.Button(frame, text="生成并复制", command=on_issue).grid(row=5, column=0, sticky="w", pady=8)
    ttk.Button(frame, text="复制激活码", command=on_copy).grid(row=5, column=1, sticky="w", pady=8)
    ttk.Label(
        frame,
        text=f"私钥：{private_key_path()}（请勿外传）",
        foreground="#B91C1C",
    ).grid(row=6, column=0, columnspan=2, sticky="w")
    ttk.Label(
        frame,
        text="授权服务：已配置" if service.server_url() else "授权服务：未配置",
        foreground="#0F766E" if service.server_url() else "#B45309",
    ).grid(row=6, column=2, sticky="e")

    # ---- 签发流水：全量列表 + 搜索 + 查看完整激活码 ----
    ttk.Separator(frame).grid(row=7, column=0, columnspan=3, sticky="we", pady=(6, 2))
    history_header = ttk.Frame(frame)
    history_header.grid(row=8, column=0, columnspan=3, sticky="we")
    ttk.Label(history_header, text="签发记录").pack(side="left")
    ttk.Label(history_header, text="搜索（时间/机器码/备注）：").pack(side="left", padx=(16, 4))
    history_query = tk.StringVar()
    query_entry = ttk.Entry(history_header, textvariable=history_query, width=18)
    query_entry.pack(side="left")
    ttk.Button(history_header, text="打开流水文件夹", command=on_open_history_dir).pack(side="right")

    history_columns = ("time", "machine", "memo", "validity", "status")
    history_tree = ttk.Treeview(frame, columns=history_columns, show="headings", height=8)
    for column, text, width in (
        ("time", "时间", 148),
        ("machine", "机器码", 142),
        ("memo", "备注", 100),
        ("validity", "有效期", 84),
        ("status", "状态", 56),
    ):
        history_tree.heading(column, text=text)
        history_tree.column(column, width=width, anchor="w", stretch=False)
    history_scroll = ttk.Scrollbar(frame, orient="vertical", command=history_tree.yview)
    history_tree.configure(yscrollcommand=history_scroll.set)
    history_tree.grid(row=9, column=0, columnspan=2, sticky="we", pady=(2, 0))
    history_scroll.grid(row=9, column=2, sticky="ns", pady=(2, 0))
    history_hint = ttk.Label(frame, text="", foreground="#94A3B8")
    history_hint.grid(row=10, column=0, columnspan=3, sticky="w")

    detail = tk.Text(frame, height=4, width=66, wrap="char", state="disabled", font=("Consolas", 9))
    detail.grid(row=11, column=0, columnspan=2, sticky="we", pady=(4, 0))

    detail_records: dict[str, dict] = {}

    def refresh_history() -> None:
        records = list(reversed(filter_history(load_history(), history_query.get())))
        history_tree.delete(*history_tree.get_children())
        detail_records.clear()
        for index, rec in enumerate(records):
            iid = str(index)
            detail_records[iid] = rec
            history_tree.insert(
                "", "end", iid=iid,
                values=(
                    str(rec.get("time", "")).replace("T", " "),
                    rec.get("machine_code", ""),
                    rec.get("memo") or "—",
                    validity_text(rec),
                    revoked_text(rec),
                ),
            )
        total = len(load_history())
        shown = len(records)
        history_hint.configure(
            text=f"共 {total} 条记录，当前显示 {shown} 条；点击行查看/复制完整激活码。"
            if shown != total
            else f"共 {total} 条记录；点击行查看/复制完整激活码。"
        )
        show_detail()

    def show_detail() -> None:
        selected = history_tree.selection()
        code = ""
        if selected:
            rec = detail_records.get(selected[0])
            if rec:
                code = str(rec.get("code") or "")
        detail.configure(state="normal")
        detail.delete("1.0", "end")
        if code:
            detail.insert("1.0", code)
        detail.configure(state="disabled")

    def on_copy_history_code() -> None:
        detail.configure(state="normal")
        text = detail.get("1.0", "end").strip()
        detail.configure(state="disabled")
        if not text:
            messagebox.showinfo("发码工具", "请先在上方点击一条签发记录。", parent=root)
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        status_var.set("已复制该条激活码，可直接粘贴发给客户。")

    def _selected_record() -> dict | None:
        selected = history_tree.selection()
        return detail_records.get(selected[0]) if selected else None

    def on_revoke(revoked: bool) -> None:
        record = _selected_record()
        if not record:
            messagebox.showinfo("发码工具", "请先在上方点击一条签发记录。", parent=root)
            return
        code = str(record.get("code") or "")
        action = "吊销" if revoked else "恢复"
        detail_text = "吊销后客户会在下次心跳（最长 6 小时）或重新打开软件时失效。" if revoked else "恢复后客户可继续使用。"
        if not messagebox.askyesno(
            f"确认{action}",
            f"确定要{action}备注为「{record.get('memo') or '—'}」的授权吗？\n\n{detail_text}",
            parent=root,
        ):
            return
        try:
            (service.revoke if revoked else service.unrevoke)(code)
        except service.LicenseServiceError as exc:
            messagebox.showerror(f"{action}失败", str(exc), parent=root)
            return
        update_history_status(code, revoked)
        refresh_history()
        status_var.set(f"已{action}该授权。")

    def on_rebind() -> None:
        record = _selected_record()
        if not record:
            messagebox.showinfo("发码工具", "请先在上方点击一条签发记录。", parent=root)
            return
        if not messagebox.askyesno(
            "确认换绑设备",
            "换绑会清空该激活码已绑定的设备，客户需在新设备上重新激活。\n\n确定继续吗？",
            parent=root,
        ):
            return
        try:
            service.rebind(str(record.get("code") or ""))
        except service.LicenseServiceError as exc:
            messagebox.showerror("换绑失败", str(exc), parent=root)
            return
        status_var.set("已解绑全部设备，客户可在新设备上重新激活。")

    detail_buttons = ttk.Frame(frame)
    detail_buttons.grid(row=11, column=2, sticky="n", pady=(4, 0))
    ttk.Button(detail_buttons, text="复制激活码", command=on_copy_history_code).pack(anchor="e")
    ttk.Button(detail_buttons, text="吊销授权", command=lambda: on_revoke(True)).pack(anchor="e", pady=(4, 0))
    ttk.Button(detail_buttons, text="恢复授权", command=lambda: on_revoke(False)).pack(anchor="e", pady=(4, 0))
    ttk.Button(detail_buttons, text="换绑设备", command=on_rebind).pack(anchor="e", pady=(4, 0))

    history_tree.bind("<<TreeviewSelect>>", lambda _event: show_detail())
    history_query.trace_add("write", lambda *_args: refresh_history())
    refresh_history()

    root.bind("<Return>", lambda _event: on_issue())
    machine_entry.focus_set()
    root.deiconify()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="千牛自动上架 发码工具（仅开发者使用）")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("generate-keys", help="首次使用：生成私钥并输出需内置的公钥").set_defaults(
        func=cmd_generate_keys
    )
    parser_issue = sub.add_parser("issue", help="为客户机器签发激活码")
    parser_issue.add_argument("--machine-code", required=True, help="客户激活页显示的机器码")
    parser_issue.add_argument("--days", type=int, default=365, help="有效天数，默认 365；0 表示永久（退款后无法收回）")
    parser_issue.add_argument("--memo", default="", help="客户备注（≤40 字，显示在设置页）")
    parser_issue.add_argument("--out", default="", help="可选：同时把激活码写入该文件供客户导入")
    parser_issue.add_argument("--no-register", action="store_true", help="跳过授权服务登记（该码将无法远程吊销）")
    parser_issue.set_defaults(func=cmd_issue)
    for name, func, help_text in (
        ("revoke", cmd_revoke, "吊销激活码（退款/违规时使用）"),
        ("unrevoke", cmd_unrevoke, "恢复已吊销的激活码"),
        ("rebind", cmd_rebind, "清空绑定设备，客户换机后可重新激活"),
        ("lookup", cmd_lookup, "查询激活码在服务端的登记与设备情况"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--code", required=True, help="完整激活码，或本机流水中的唯一片段")
        command.set_defaults(func=func)
    sub.add_parser("gui", help="图形界面发码").set_defaults(func=cmd_gui)
    sub.add_parser("selftest", help="自检：RFC 8032 测试向量 + 签发验证闭环").set_defaults(
        func=cmd_selftest
    )
    args = parser.parse_args(argv)
    if args.command is None:
        # 双击 exe / 无参数时直接打开图形界面
        return cmd_gui(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
