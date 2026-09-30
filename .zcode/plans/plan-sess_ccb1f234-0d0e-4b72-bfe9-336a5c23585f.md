# 规格图改"入库后分批上传"方案

## 现状与差距

当前 `publish_page/both` 策略下，规格图在**入库提交前**于同一发布页一次性全部上传（`pipeline.py:1952-1956` → `spec_images_gate`），SKU≥13 走逐行上传（`_spec_row_image_step`），SKU<13 走批量弹窗（`spec_images.js`）。滑块出现即 `PAUSE` 暂停整个入库。

可复用的现成积木：
- `_repair_existing_spec_images`（pipeline.py:2061-2104）：按商品 ID `tab_new("...publish.htm?itemId=...")` 进编辑页 → `probe_state`/`upload_status` 安全校验 → `_spec_column_state` 读服务器规格列缺失行 → 补图 → `_finish_publish` 保存 → 复核。
- `spec_image_stage=submit_pending` 防误重提守卫（pipeline.py:2073-2076）、`item_id_from_result != item_id` 结果不明守卫（2089-2090）。
- 滑块 PAUSE → 桌面端弹浏览器 → 人工处理 → 继续后按已有商品续跑（有 ID 永不重复建品）。

## 目标流程

1. **建品阶段（入库）**：对所有策略一律跳过规格图，其余步骤照旧 → 提交入库拿到 `taobao_item_id`。
2. **分批补图循环**（入库成功后立即执行；续跑/复检同一入口）：
   - 每批：新开编辑页 → probe_state + 安全校验（滑块则 PAUSE 保留现场）→ `_spec_column_state` 读服务器缺失行 → 取**前 N 行**（N=每批数量，0=全部一次）→ 只处理这 N 行（≥13 逐行路径 Python 侧按行限制；<13 路径 JS 新增 `onlyRows` 作用域）→ 复核这 N 行已写入 → `probe_errors` 必填校验 → `_finish_publish` 保存（提交前置 `spec_image_stage=submit_pending`，成功后回置 `uploading`）→ 校验商品 ID 未变 → **关闭当前编辑页标签（退出）** → 下一批。
   - 全部批次完成 → 既有最终复核（重开服务器页比对规格列）→ `spec_image_stage=complete`。
   - 缺失行每批从服务器重算，天然支持断点续传；已上传到图片空间的文件不会重复上传（open 阶段按素材库缺失判断）。
3. **暂停语义不变**：滑块/结果不明仍 PAUSE + 保留现场，人工处理后继续；守卫语义不变，只是批间成功保存会把 `spec_image_stage` 回置为 `uploading`，避免"上一批其实已成功但下批被守卫误拦"。

## 文件改动

**web_fill/pipeline.py**
- `run_batch`：新参数 `spec_upload_batch_size=0`；建品恒 `skip_spec_images=True`（2253-2256 处简化，legacy 设置保留兼容）；三处调用点（2256 both 续跑 / 2305 publish 续跑 / 2404-2412 新建成功后）改为带批次的补图，新建后那次由"仅核验"(confirm_submit=False) 改为"补图+保存"(True)；新增批间进度回调（更新 item + `_emit_flow` + `_remember_item`，notice 显示"规格图批次 x/y，已保存 z/总行"）。
- `_repair_existing_spec_images`：加 `spec_batch_size` 参数与批次循环（含守卫、批间关标签、进度步骤写入 `_write_progress`）。
- `spec_images_gate`/`_spec_row_image_step`/`_image_step`/`spec_images_unbound`：加 `only_rows`（0 基行号）作用域——文件列表、绑定范围、审计比对（`missing` 过滤到本批行）、未绑定判定均只看本批行；≥13 逐行绑定进度按"批前已完成+offset"累计上报。

**web_fill/scripts/spec_images.js**（<13 路径）
- 支持 `onlyRows`：绑定循环只处理这些行；`saved` 校验改为"本批行均已写入"（其余行数与总数校验保留）；抽屉稳定判定用 `minFilledCount`（含之前批次已绑定数）替代全量行数。`spec_row_images.js` 不动。

**设置贯通（仅勾选"商品规格图（原方式）"时生效/显示）**
- `desktop/ui/src/types.ts`：`AppSettings.spec_upload_batch_size: number`；`App.tsx` 默认 2。
- `desktop/ui/src/components/SettingsPanel.tsx`：在"商品规格图（原方式）"勾选项下方条件渲染数值输入"每批上传规格图数量（0 表示全部一次上传）"，沿用 limit 的文本暂存+校验模式，纳入保存按钮校验。
- `desktop/server.py`：`SettingsIn` 加字段（`ge=0, le=99`），GET /api/status 回显、PUT 校验赋值。
- `desktop/paths.py`：`Settings` 默认 2、`normalized()` 钳制、`load_settings()` 兼容旧文件（缺省 2，不升 settings_version）。
- `desktop/jobs.py`：`run_batch(..., spec_upload_batch_size=settings.spec_upload_batch_size)`。
- 打包（app.py/app.spec/installer.iss）无需改动。

## 测试与验收

- `test_web_fill.py`（仿 FakeSession 模式）：建品阶段跳过规格图；批次循环次数/每批一次保存/批间重开编辑页；`only_rows` 的 payload 与文件作用域；`submit_pending` 守卫仍拦截；保存结果不明 PAUSE；0=不分批等价旧行为。
- `test_desktop.py`：设置默认 2、持久化、PUT 非法值拒绝。
- **真实页面验收**（按项目规则，模拟测试不能替代）：用已授权 Playwright 会话以每批=2 跑真实商品，分别记录搜索主图、销售规格图和非图片字段差异；观察滑块出现频率与批次大小的关系，结论未验证前不默认宣称"减少滑块"。
- 更新 README.md / 开发进展.md。

## 默认值

`spec_upload_batch_size` 默认 **2**（按你的提议），0 = 编辑页内全部一次上传（用于对照测试旧行为）；UI 仅在勾选"商品规格图（原方式）"时显示。