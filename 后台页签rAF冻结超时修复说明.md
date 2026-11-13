# 后台页签 rAF 冻结超时修复说明（v1.2.2）

## 现象

并发入库时商品反复出现如下告警并自动重试，重试往往同样失败：

```
TimeoutError: locator.scrollIntoViewIfNeeded: Timeout 7993ms exceeded.
Call log: - attempting scroll into view action - waiting for element to be stable
```

2026-10-03 晚间批次中，worker-2 的同一商品在 21:12 / 21:39 / 21:56 / 22:04 连续四轮同因失败；worker-1/worker-3 也出现"SKU 模板已上传但结果未核实：页面操作超时"。单条慢、整批卡，`click` / `fill` 等操作在同类条件下同样会中招。

## 根因

Playwright（含项目内置的 playwright-core 1.62.1）在执行 `scrollIntoViewIfNeeded`、`click`、`fill` 等动作前会先做元素"稳定"检查（`InjectedScript._checkElementIsStable`）：**连续读取两次包围盒且完全一致才放行，而这两次读取由 `requestAnimationFrame` 驱动**。

Chromium 对后台页签（同窗口内非激活页签）会停止/深度节流 rAF。在真实 9222 浏览器上实测（2026-10-03）：

| 页签状态 | rAF 频率（1.5 秒采样） |
| --- | --- |
| 前台页签 | ≈91 次（60fps） |
| 后台不久（约 20 秒内） | ≈72 次，随后骤降 |
| 后台较久 | **0–3 次（冻结/约 0.8fps）** |

页签进入后台约 20–30 秒后 rAF 冻结（有宽限期）。并发入库时多个 worker 共用一个浏览器窗口，各自的 `tab-select`（内部是 `page.bringToFront()`）互相把别人的页面挤到后台；脚本中途被挤后，后续所有依赖 stable 检查的操作要么每次多拖 2.4 秒以上，要么直接烧满超时——并发越高越是必现。单条模式下页签被素材库/补图页签等抢占时同理（即此前记录过的"后台页签点击必超时"问题）。

两个此前未落实的关键事实：

1. `visibilityState` 因 Playwright 焦点仿真仍显示 `visible`，不能用它判断冻结；
2. 千牛自动化 Chrome 启动参数已含 `--disable-background-timer-throttling`、`--disable-renderer-backgrounding`、`--disable-backgrounding-occluded-windows`，**定时器在后台页签照常触发**，被停的只有 rAF。

## 修复

### 1. 内置 playwright-core 补丁：stable 检查改用 setTimeout 调度

`tools/patch_background_tab_raf.py`（幂等，可重复执行）把注入脚本 `_checkElementIsStable` 的两处 `this.utils.builtins.requestAnimationFrame(raf);` 替换为 `this.utils.builtins.setTimeout(raf, 16);`。语义不变：仍是两次间隔约 16ms 的相同包围盒读数；差别只是采样源从 rAF 换成定时器。

已应用到：

- `desktop/runtime/playwright-core/lib/coreBundle.js`（随打包进入安装目录）
- `.work/node_modules/playwright-core/lib/coreBundle.js`（开发环境实际使用的回退副本；**重装 node_modules 后需重新执行补丁工具**）
- `.work/desktop-runtime/playwright-core/lib/coreBundle.js`（浏览器验收夹具）

注意：升级 playwright-core 版本后如替换失败，工具会显式报错并要求人工核对，不会静默跳过。

### 2. `web_fill/scripts/probe_state.js` 的 `waitForFunction` 加 `polling: 250`

`page.waitForFunction` 默认也用 rAF 轮询，后台页签下会白等满 15 秒超时；改为 250ms 定时轮询。后续新增脚本如需 `waitForFunction`，一律显式传数字 `polling`。

### 3. 不采用 bringToFront 方案的原因

每次命令前把 worker 页签拉到前台只能修复脚本边界的冻结；并发时另一个 worker 的 `tab-select` 仍会在脚本运行中途把页面挤到后台，操作照样超时，还会导致窗口频繁弹到前台。改用定时器调度后，页签在后台也能正常操作，无需抢前台。

## 验证（2026-10-03，真实 9222 浏览器）

在自建的一次性空白页签上等待其进入后台并冻结（采样确认 ticks ≤ 3）后，分别用原始调度与补丁调度执行 `scrollIntoViewIfNeeded` + `click`：

| 运行时 | 结果 |
| --- | --- |
| 原始（rAF 调度） | OK 但耗时 **3933ms**（rAF 深度节流时 stable 检查需等两帧）；页签完全冻结时即生产日志中的 7993ms 超时 |
| 补丁（setTimeout 调度） | OK，**124ms** |

回归覆盖：

- 新增 `web_fill/scripts/background_tab.browser.test.cjs`：镜像生产路径（自起 Chrome + `connectOverCDP` attach），等待页签 rAF 真正冻结后断言操作在 2 秒内完成；环境无法复现冻结时自动跳过。
- 既有 10 个 `.browser.test.cjs` 浏览器套件全部通过（47 项，含补丁后运行时）。
- 全量非浏览器回归 **478 passed, 1 skipped**（`test_live_*.py` 仍按约定单独授权）。

真实入库验收待办：并发 ≥2 批次跑通后确认不再出现 `scrollIntoViewIfNeeded` 超时告警。
