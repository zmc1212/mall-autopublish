# 主视频上传功能实施计划

## 需求
图片包内有主视频时,自动上传到发布页"商品视频"区。识别规则:
1. 优先:文件名含"主视频"的视频文件(多个时按文件名排序取第一个)
2. 兜底:包内任意视频文件,按文件名排序取第一个(只上传一个,已确认)

## 改动点

### 1. `商品解析.py` — 识别主视频
- 新增 `VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".3gp", ".mkv", ".webm"}`(第 22 行 `IMAGE_EXTS` 旁)
- `scan_image_pack`(第 137-190 行):额外收集包内视频文件,按上述优先级选出主视频;返回 dict 新增 `"main_video": Path | None`。视频不参与现有图片分类,"未分类兜底"逻辑不变
- `resolve_product`(第 300-331 行):product dict 新增 `"main_video": pack.get("main_video")`

### 2. `workspace.py` — 扫描数据(仅数据,不改 UI)
- `_scan_pack`(第 198-211 行)产出加 `"video_count"` 字段,便于日志/测试观察。`_pack_has_media` 与"没有可识别图片"判定不变(纯视频文件夹仍视为无效包)

### 3. `web_fill/pipeline.py` — 编排新步骤
- `product_to_payload`(第 106-151 行):加 `"main_video": _abs(...)`
- 新增 `video_step(session, payload, steps)`:
  - `run_script(session, "main_video.js", {files: [main_video], names, phase: "open"}, timeout≈300)`(视频大、转码慢,超时放宽)
  - 结果校验:`already`(页面已有视频)/`uploaded` 视为成功;其余 raise(标"暂停"保留现场,不自动重复上传——遵循 AGENTS.md)
- `fill_new_product`(第 1713-1883 行):在 3:4 主图之后、详情图之前插入 `video` 步骤;完成后 `completed.add("video")` + `_save_checkpoint`;`pending_media` 元组(第 1753-1756 行)加 `("main_video", "video")`;probe 输出 keys(第 1736-1738 行)加 `"videos"`
- `decide_skips`(第 700-750 行):payload 有 main_video 且 `state.videos >= 1` → `skips.add("video")`(保守:结合 checkpoint completed 含 "video" 才跳过,防止误判页面自带内容)
- `page_looks_in_progress` / `page_conflicts` 的内容计数集合加 `videos`

### 4. `web_fill/scripts/probe_state.js` — 页面探测
- 新增 `videos` 计数:候选容器 `[id^="sell-field-"][id*="ideo"]`,兜底按"商品视频"标题文本向上爬定位;统计容器内 `<video>` 元素或已上传视频缩略图(排除"上传视频"虚线空框)。定位不到时返回 0

### 5. `web_fill/scripts/main_video.js` — 新上传脚本(核心)
仿 `main_images.js` 结构,复用 `_helpers.inc.js` 现有辅助,单 phase 主流程:
1. `dismissKnow()` → 探测商品视频区是否已有视频(幂等,resume 安全),有则返回 `{already: true}`
2. 定位并点击"上传视频"按钮:候选 `sell-field-*video*` 容器内找按钮,兜底"商品视频"标题向上爬找 `innerText==="上传视频"`(复用 `openMainPicker` 第 199-222 行的模式)
3. 等待上传入口:素材库/视频库 iframe(`sucaiFrame` 正则已兼容 material/picture-space)→ 复用 `finishLocalUpload`/`retryUntilUploaded`(setInputFiles+回执等待);若为页面原生 file input → 直接 `setInputFiles`
4. 等待写入完成:回执关闭 + 容器内出现视频缩略图/`<video>`(轮询放宽至 ~120s),返回 JSON 结果
- 不走 content-addressed 媒体缓存(视频大、无跨商品库内复用需求),直接用原始路径
- 真实 DOM 字段 id 未知,选择器全部做多候选+文本兜底;真实页面验收时按实际 DOM 微调

### 6. 测试(`test_validation.py` / `test_web_fill.py`,沿用现有 FakeSession/mock 模式)
- `scan_image_pack`:"主视频.mp4"优先于其他视频 / 无主视频命名时兜底取排序第一个 / 无视频返回 None / 不影响现有图片分类
- `product_to_payload` 透传 `main_video` 绝对路径
- `decide_skips` video 跳过规则
- `fill_new_product` 含 main_video 时步骤序列含 `video` 步骤;无视频时不产生该步骤
- 注意:模拟测试通过不代表真实页面验收通过(AGENTS.md)

### 7. 文档
- `开发进展.md` 追加主视频识别与上传规则记录

## 真实页面验收(需您配合)
testdata 中"东米2505萌宠小狗…"包已含 `主视频.mp4`,实现并模拟测试通过后,用已授权千牛会话对该商品跑一次真实填写验收视频上传;遇滑块/人工验证按规则保存现场暂停。真实页面验收完成前,页面行为结论为"无法判断"。