# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

面向使用千牛卖家中心处理商品资料的桌面操作人员。用户确认本轮优先改善日常批量操作效率，使任务、商品和异常一眼可见。

## Product Purpose

从本地工作空间或 Excel 清单准备商品资料，校验后自动填入卖家中心并放入仓库。入库不等于立即上架。

## Operating Context

现有产品为 Python 桌面程序，使用 React、TypeScript、Tailwind CSS 界面和内置自动化浏览器。主要流程为连接卖家中心、准备商品清单、执行批次、检查结果与处理异常。工作空间及登录状态支持恢复。

## Capabilities and Constraints

- 保留现有连接、目录扫描、Excel 导入、类别选择、批次默认值、校验、并发执行、暂停/继续、结果导出、记录清除、日志和更新功能。
- 本轮先产出可审阅的设计稿，再依设计稿实施。用户未指定必须保留的视觉风格。
- 现有未提交修改必须保留；不因界面重设计改变上传、重试、入库策略或默认参数。
- 浏览器验证复用现有 Playwright 流程；模拟测试不能替代真实页面验收。
- 不自动生成安装包或增量更新包。

## Brand Commitments

产品沿用“千牛自动上架”名称，使用简体中文，技术路径和 API 名称保留原文。

## Evidence on Hand

现有实现位于 `desktop/ui/src`；业务接口位于 `desktop/server.py` 和 `desktop/jobs.py`。设计稿中的示例商品与数量须标明为演示数据。

## Product Principles

- 先看清当前批次、进度与异常，再决定操作。
- 常用操作就近呈现，高级设置按需展开。
- 操作状态和结果明确，防止误判和重复执行。
- 保留可恢复的工作上下文，减少跨页寻找与重复输入。
