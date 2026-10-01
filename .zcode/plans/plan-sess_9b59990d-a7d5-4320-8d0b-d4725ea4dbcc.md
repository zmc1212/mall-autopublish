# 导出日志功能

## 目标
自动化入库在其他电脑上出问题时,一键把所有诊断日志打包成 zip 并打开所在文件夹,直接发送给开发者分析。

## 后端

### 1. 新模块 `desktop/log_export.py`
`export_logs_zip() -> dict`,用标准库 `zipfile` 打包,输出到 `<appdata>\log-exports\日志导出-<YYYYMMDD-HHMMSS>.zip`,返回 `{"path", "folder", "files", "size"}`。

打包内容(全部经 `desktop/paths.py` 的路径函数定位,自动跟随 QIANNIU_APPDATA 等环境变量):
- `paths.logs_dir()` 整个目录递归 → zip 内 `logs/` 前缀:desktop.log(+.1)、crash.log、self-test.log、server.log、api.port、uvicorn.log、`playwright/` 下所有 raw.txt / web_fill_*.json / web_fill_progress.json / web_fill_upload_security.json / spec_row_image_recovery.json / `.playwright-cli` 的 console-*.log 与 page-*.yml
- `job_session.json`(appdata 根)→ zip 根
- `settings.json`(appdata 根)→ zip 根(仅含浏览器路径/端口等配置,无凭据)
- 结果目录(`paths.load_settings().results_dir`)按修改时间最近的 5 份 `*.结果-*.json` + 对应 `.xlsx` → zip 内 `results/` 前缀

排除与防护:
- 跳过任何名为 `media-upload-cache` 的目录(上传图片缓存,体积大、无诊断价值)
- 单文件超过 10MB 跳过(记入 manifest)
- 逐文件 try/except:单个文件被占用/读取失败不中断导出,失败清单写入 manifest
- 不碰 `chrome-profile/`、`webview-profile/`(体积大且含登录态)

`manifest.txt` 写入 zip 根:导出时间、系统/Python 版本、是否 frozen、各来源目录实际路径、包含文件清单(相对路径+字节数)、跳过清单、以及 job_session.json 里的当前 blocker 文本(暂停原因,无则写"无")。

### 2. `desktop/server.py` 新路由
仿照 `/api/template`(server.py:220)的模式,在 `/api/job/history` 附近新增:
```python
@app.post("/api/logs/export")
async def export_logs():
    return await run_in_threadpool(export_logs_zip)
```
异常走现有 `_fail()`。

## 前端(desktop/ui/src)

### 3. `api.ts`
`api` 对象新增 `exportLogs: () => request<{path; folder; files; size}>("/api/logs/export", {method: "POST"}, 60000)`(打包可能耗时,超时放宽到 60 秒)。

### 4. `SettingsPanel.tsx`
"最近运行日志"卡片头部(现 107-115 行)右侧、条数统计旁加"导出日志"小按钮(Download 图标,pending 时转圈,复用 `pending.has("settings.exportLogs")`),样式与深色卡片协调(仿现有过滤按钮的 ghost 风格)。新增 `onExportLogs` prop。

### 5. `App.tsx`
给 SettingsPanel 传入:
```tsx
onExportLogs={() =>
  runAction("settings.exportLogs", async () => {
    const result = await api.exportLogs();
    pushToast("success", `日志已导出(${result.files} 个文件),文件夹已打开`);
    await nativeOpen(result.folder);
  })
}
```
用 `nativeOpen`(pywebview 桥 `os.startfile`)打开 zip 所在文件夹,浏览器开发模式自动走 window.open 兜底。

## 测试

### 6. `test_desktop.py` 新增用例
沿用现有 API 测试模式(QIANNIU_APPDATA 指向临时目录 + configure_environ),测试类加一个用例:
- 预置假的 `logs/desktop.log`、`logs/playwright/web_fill_x.raw.txt`、`job_session.json`、`results/清单.结果-*.json` 和一个 `media-upload-cache/` 下的大图、一个 >10MB 文件
- `POST /api/logs/export` → 200,断言返回 path/folder/files
- 用 `zipfile` 打开 zip:包含 manifest.txt、logs/desktop.log、job_session.json、results/*.结果-*.json;不含 media-upload-cache 与超限文件

## 构建与验收

7. `cd desktop/ui && npm run build`(改 src 后必须重建 dist 才生效)
8. 运行 `python -m unittest test_desktop.py` 相关用例确认通过
9. UI 验收:复用 `.zcode/tmp/ui_snapshot.py` 的 mock API + Playwright 模式,mock `/api/logs/export`,截图确认"设置与排障"页按钮渲染正常、点击后 toast 与打开文件夹逻辑生效

## 明确不做
- 不做"另存为"对话框(固定文件夹 + 自动打开更省事;后续需要再加 pywebview save 桥)
- 不打包 chrome-profile、webview-profile、上传图片缓存
- 项目根 `logs/` 的 git 遗留旧日志不在本功能范围