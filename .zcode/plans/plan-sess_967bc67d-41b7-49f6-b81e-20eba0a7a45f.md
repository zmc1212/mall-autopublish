## 问题根因(已确认)

「商品明细」里的历史记录来自后端三层叠加,不是前端缓存:
1. **重扫是"合并"不是"镜像"**:`workspace.py:401-471 _merge_rows` 对文件夹已删除/被替换的行只标"资料缺失"(`_mark_missing`, workspace.py:390)永不清除,替换文件夹还会产生"新行+旧行"并存;该行为被 `test_workspace.py:120-129` 固化。
2. **「校验」不重扫**:`/api/workbook/validate`(server.py:156-163)只重读 Excel,文件夹变化完全不可见。
3. **会话黏住旧数据**:`job_session.json` 经 `merge_execution`(job_session.py:216-251)把旧的淘宝商品ID/执行状态按行号兜底回贴,且启动恢复会原样还原旧行。

## 目标工作流设计

**清单 = 当前工作空间文件系统的镜像;执行历史 = 独立归档(按商品标识+内容指纹),不随行删除。**

- 重扫/校验 → 清单始终等于当前文件夹:新增行、更新行、**移除消失文件夹的行**。
- 被移除行的执行状态(淘宝商品ID、链接、flow 字段)归档到 `execution_history`;文件夹重新出现时自动回贴,防止重复上架。
- 同一文件夹内容被换成新商品时(指纹不一致),不回贴旧执行状态,避免漏上架——同时修复了现有"仅按行号回贴"的潜在错贴 bug。

## 修改点

**1. workspace.py — 重扫即镜像**
- `_merge_rows`:删除 `_mark_missing` 保留逻辑,文件夹不存在的行直接移除;保留"未勾选类别移除""空标识移除";图片包路径指向工作空间之外的行视为手工维护,保留不动。
- 摘要返回 `removed`(被移除的商品标识列表)取代 `missing`;`_mark_missing` 删除,`_clear_missing` 保留(旧表中资料缺失行在文件夹恢复时还原为待处理)。

**2. 千牛自动上架.py — 内容指纹**
- `validate_workbook`(约 :485-514)对每行图片包计算指纹(排序后的图片相对路径+文件大小 md5),附加到校验结果;文件夹不存在时指纹为空。

**3. job_session.py — 执行历史档案**
- session 新增 `execution_history`:product_id → {taobao_item_id、view/edit_url、flow 字段、execution、notice、title、pack_fingerprint、updated_at}。
- `remember_workbook`、`patch_execution`、`patch_flow_state` 写行时同步 upsert 历史;旧会话无此键用 setdefault 兼容。
- `merge_execution`:保留 (row, product_id) 精确匹配;新增按 product_id 查历史回贴(文件夹重新出现的场景);**指纹不一致或当前指纹缺失 → 不回贴**;删除"仅按行号兜底"回贴(job_session.py:229-237)。

**4. desktop/jobs.py + server.py — 摘要与校验行为**
- `open_workspace`(jobs.py:482-507):日志/快照改用 removed,追加"移除 N 款";`sync` 摘要 = {added, removed, created}。
- `/api/workbook/validate` 改为先重扫文件系统(sync_workbook)再校验,端点路径不变;`/api/workbook/import`(导入外部 Excel)保持原语义;启动恢复路径中的校验不额外触发重扫。

**5. 前端 desktop/ui/src**
- App.tsx:重扫/校验后 notice 显示「新增 X / 移除 Y」(取返回的 sync 摘要);types.ts 同步 sync 类型。
- WorkbookPanel 商品明细无需结构改动,旧行随数据消失;前端无"资料缺失"引用需清理。

**6. 测试**
- 改 `test_workspace.py::test_missing_folder_marked_not_deleted` → 文件夹删除后行被移除且 removed 正确;新增:文件夹恢复后行重现、外部路径行保留、未勾选类别行为不变。
- 新增 job_session 单测:历史回贴、指纹不一致不回贴、行号兜底已移除。
- 更新 test_desktop.py / test_web.py 中涉及"资料缺失"的断言;新增「校验触发重扫」断言。

## 已知限制(写入交付说明)
- 升级后第一次重扫会清掉现存全部"资料缺失"行(即期望效果)。
- 文件夹改名/换名的商品视为新商品,历史不回贴(标识变化,防止误跳过)。
- 执行历史本期仅持久化存储,不做 UI 管理入口。

## 验证
- 运行 test_workspace.py、test_desktop.py、test_web.py 及相关单测全绿。
- 真实验收(手动):删除/替换工作空间商品文件夹 → 点「校验」→ 商品明细旧行消失、提示"移除 N 款";恢复文件夹 → 执行状态(淘宝商品ID)自动回贴。