# 千牛商品自动录入工具

当前版本完成了 Excel 模板、字段说明、本地校验，以及基于已登录 Chrome 的网页填写。默认 `dry-run`，不会点击“提交宝贝信息”。

## 文件

- `outputs/千牛商品清单模板.xlsx`：商品清单模板，包含 `商品清单`、`字段说明`、`处理日志`。
- `千牛自动上架.py`：读取模板并校验；`--submit` 时连接千牛窗口填写。
- `千牛网页执行.py`：调用项目里已有的 Playwright CLI（与 Codex 同一套），连接 `9222` 已登录 Chrome，只走新建发布页，固定放入仓库。
- `启动持久化千牛.cmd`：独立启动已登录 Chrome，并打开 `9222` 调试端口。

## 使用

先启动已登录窗口（只需一次，之后复用同一 profile）：

```powershell
.\启动持久化千牛.cmd
```

本地校验：

```powershell
python 千牛自动上架.py outputs/千牛商品清单模板.xlsx
```

检查浏览器登录态，不填写商品：

```powershell
python 千牛网页执行.py --probe
```

填写真实商品（仍不点击提交）：

```powershell
python 千牛自动上架.py 你的真实商品.xlsx --submit --limit 1
```

确认页面已选“放入仓库”后，才允许真正提交：

```powershell
python 千牛自动上架.py 你的真实商品.xlsx --submit --confirm-submit --limit 1
```

结果默认另存为带时间戳的 Excel 和 JSON，不修改输入文件。退出码：0 校验/填写通过、1 数据或执行失败、2 读取/保存失败。`--confirm-submit` 只会点击“提交宝贝信息”，不会选择立刻上架。模板里的示例行会被拒绝执行。

安装依赖：`python -m pip install -r requirements.txt`。运行测试：`python -m unittest -v test_validation test_web`。

网页操作使用 Node Playwright CLI（`.work/node_modules/playwright-core`），不安装 Python `playwright` 包。当前没有控制面板，也还没有仓库回查验收。多规格 SKU 表会暂停给人工核对。浏览器连接状态见 `开发进展.md`。
