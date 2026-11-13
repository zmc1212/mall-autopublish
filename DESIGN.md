---
name: 千牛自动上架
description: 面向批量商品入库操作的中文桌面工作台设计系统
colors:
  primary: "#18856b"
  primary-hover: "#116d57"
  on-primary: "#ffffff"
  sidebar: "#f5f9f6"
  sidebar-muted: "#607069"
  background: "#f3f6f4"
  foreground: "#163e35"
  muted: "#edf3f0"
  border: "#dfe7e2"
  surface: "#ffffff"
  success: "#059669"
  warning: "#d97706"
  destructive: "#dc2626"
  ghost-text: "#475569"
  active: "#237bc1"
  auxiliary: "#596e62"
  progress-pending: "#9aa7a0"
  progress-attention: "#d58a17"
  attention-background: "#fff9ec"
  attention-border: "#f0dda8"
  attention-foreground: "#71551e"
  selection: "#cfebdf"
  selection-foreground: "#123e32"
typography:
  display:
    fontFamily: "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, PingFang SC, sans-serif"
    fontSize: "36px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, PingFang SC, sans-serif"
    fontSize: "27px"
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, PingFang SC, sans-serif"
    fontSize: "17px"
    fontWeight: 650
  body:
    fontFamily: "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, PingFang SC, sans-serif"
    fontSize: "14px"
    fontWeight: 400
  label:
    fontFamily: "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, PingFang SC, sans-serif"
    fontSize: "12px"
    fontWeight: 500
rounded:
  xs: "5px"
  sm: "6px"
  md: "8px"
  lg: "9px"
  xl: "10px"
  2xl: "12px"
  dialog: "16px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
  3xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "40px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ghost-text}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 8px"
    height: "40px"
  button-danger:
    backgroundColor: "#fef2f2"
    textColor: "{colors.destructive}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    height: "40px"
  input-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
    height: "40px"
  nav-active:
    backgroundColor: "#ddf2e8"
    textColor: "#116951"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "12px 18px"
    height: "54px"
  surface-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
    padding: "16px"

---

# Design System: 千牛自动上架

## Overview

**Creative North Star: "清晰批次工作台"**

当前实现把商品批次当成连续操作台：商品表格是中心，顶部显示工作空间与连接状态，表格上方提供批次统计和主操作，右侧同时显示执行槽、需关注项与最近动态。A 批次工作台的方向把任务、商品和异常放在同一工作视野中，数值和状态由现有 API 驱动。

界面用浅绿侧栏和浅灰绿画布承托白色工作区；深森林绿用于正文和主要动作，细灰绿边框表达层级。圆角、紧凑表格、清晰的状态文字和少量状态色形成专业、清爽、便于日常批量扫描的桌面工具语言。

本规范的事实依据是 `desktop/ui/src/index.css`、`desktop/ui/src/workbench.css`、`desktop/ui/src/theme/button/Button.tsx`、`desktop/ui/src/theme/form/InputText.tsx` 以及 `Sidebar.tsx`、`StatusBar.tsx`、`RunPanel.tsx`、`RunInspector.tsx` 等当前组件。示例数量、商品名和截图中的占位文本不构成业务事实；真实状态必须继续绑定现有接口。

**Key Characteristics:**

- 商品表格是批次工作的中心，统计、筛选和详情操作就近出现。
- 浅绿导航、浅灰绿应用背景与白色工作区形成清晰的层叠关系。
- 森林绿正文和翡翠色主操作承担主要视觉权重。
- 细边框、紧凑行列、圆角表面和分段进度支持快速扫描。
- 入库状态与图片状态分开显示；待核实结果保留 amber 语义，不显示为完成。

## Colors

颜色体系以低饱和的绿灰中性面为底，以森林翡翠作为主要行动色，再用蓝色、amber 和红色表达处理中、待核实与失败状态。

### Primary

- **森林翡翠（`colors.primary`）**：用于主按钮、选中页码、完成状态和进度完成段。
- **深翡翠悬停（`colors.primary-hover`）**：用于主色交互的悬停或当前阶段文字。
- **主色反差（`colors.on-primary`）**：用于翡翠实心操作表面上的文字和图标。

### Neutral

- **应用浅灰绿（`colors.background`）**：应用根画布和面板间的留白底色。
- **侧栏浅绿（`colors.sidebar`）**：固定导航区域的底色。
- **白色工作面（`colors.surface`）**：工作区、表格、输入框和卡片的默认表面。
- **森林正文（`colors.foreground`）**：页面标题、正文重点和主要字段文字。
- **柔和填充（`colors.muted`）**：次级控件悬停、辅助信息块和表单分组背景。
- **细边框（`colors.border`）**：侧栏、顶栏、卡片、表格和分隔线的共同边界。
- **侧栏辅助文字（`colors.sidebar-muted`）**：侧栏说明和低优先级导航信息。

### Status Accents

- **成功绿（`colors.success`）**：连接成功、验证成功和完成状态的语义基准。
- **进行中蓝（`colors.active`）**：处理中、图片识别/核验中和当前 worker 阶段。
- **警示 amber（`colors.warning`）**：待核实、需关注、暂停或停滞提示。
- **失败红（`colors.destructive`）**：执行失败、校验错误和破坏性操作。
- **辅助文字（`colors.auxiliary`）**：白底上的执行槽说明、阶段标签和顶栏次级文字；当前实现使用该对比度更高的辅助色。
- **进度待处理（`colors.progress-pending`）**：四段进度中的待处理段。
- **进度需关注（`colors.progress-attention`）**：四段进度中的需关注段。
- **注意面（`colors.attention-background`、`colors.attention-border`、`colors.attention-foreground`）**：阻塞、停滞和需要人工处理的提示块。
- **选中反馈（`colors.selection`、`colors.selection-foreground`）**：文本选中和局部选择反馈。

**The Split Status Rule.** 入库状态和图片状态始终分开表达；表格不能用一个“完成”标签覆盖两条流程。

**The Amber Uncertainty Rule.** 提交、上传、采纳或图片核验结果待核实时保持 amber/需关注语义，只有真实完成条件满足时才进入完成状态。

## Typography

**Display Font:** `Microsoft YaHei UI`, `Microsoft YaHei`, `Segoe UI`, `PingFang SC`, sans-serif  
**Body Font:** 同一套系统无衬线中文字体栈  
**Label/Mono Font:** 代码、机器码和日志中的技术值继续使用组件指定的 `font-mono`。

**Character:** 字体体系优先保证中文桌面场景下的清晰度和稳定密度。标题使用较重字重与轻微负字距建立层级，表格和状态文字保持紧凑，并对数量、时间和分页使用等宽数字。

### Hierarchy

- **Display（`typography.display`）**：执行工作台主标题，承担当前批次的第一视觉锚点。
- **Headline（`typography.headline`）**：其他面板标题和页面级说明。
- **Title（`typography.title`）**：执行详情、卡片和区块标题。
- **Body（`typography.body`）**：工作区正文、商品名称和说明文字。
- **Label（`typography.label`）**：按钮、筛选器、表头和状态标签。

数字字段使用 `font-variant-numeric: tabular-nums`，保证统计条、时间和分页在更新时保持列宽稳定。辅助文字使用 `colors.auxiliary`；当前白底文字对比度为 5.48。

**The Scan-First Type Rule.** 标题和数量负责快速定位，辅助文字只解释上下文；不要用低对比度长段说明抢占批次状态的视觉权重。

## Layout

应用根节点占满 `100dvh` 并隐藏页面级溢出，整体由固定侧栏、顶栏和可滚动主工作区组成。侧栏宽度为 `clamp(196px,15.25vw,242px)`；顶栏最小高度为 `46px`，工作区面板默认使用 `26px 24px 22px` 的内边距和 `20px` 的纵向间距。

执行工作台使用 `minmax(0,1fr)` 与 `clamp(300px,24.4vw,388px)` 的双列网格。左侧依次放置标题和主操作、批次统计、阻塞提示、筛选搜索、商品表格和分页；右侧放置实际执行槽、需关注项和最近动态。商品表格保持 `min-width:560px`，宽屏按可用高度动态决定每页 1–8 行，避免分页后仍需纵向滚动才能看完这一页；窄屏每页展示 4 或 6 行，由整页承接纵向内容。横向溢出仅在列内容确实超出窗口时出现。

统计区上方的五个快捷计数仍可筛选全部、已完成、执行中、未执行和需关注；连续进度条另外按已完成、执行中、待处理、需关注四段互斥计算，并使用真实通过校验的商品数据。两组信息各自服务于筛选和进度，不把不同口径混成一个数字。

响应式行为以保持可操作性为先：`1300px` 以下收紧侧栏品牌和工作台内边距；`1179px` 以下执行详情移动到商品表格下方，任务卡按两列展示，需关注项和最近动态并排，由整页统一滚动；`760px` 以下侧栏收缩为图标栏、导航文字隐藏、标题允许换行、任务卡和检查器变为单列。右栏移动而不是裁剪表格。

商品清单页将工作空间路径、目录选择和扫描操作排列在同一工具行，扫描类别在其下方自然换行。类别区不设置固定高度或内部滚动；超过 6 类时先展示前 6 类，通过展开/收起访问其余类别。类别名称与商品数量同行，缺少模板与扫描问题保留可见提示。批次默认设置使用轻量折叠行，商品表格占据主要工作面并保留至少 320px 高度；长商品标题最多显示两行。小窗口或展开很多类别时由整页承接纵向滚动，避免在类别选项中嵌套滚动。

连接页说明卡与授权页内容按实际内容高度排列。设置页把草稿状态与保存操作放在标题区，由当前 tab 的内容区承接纵向滚动，调试日志不再嵌套独立滚动框；图片处理概览使用紧凑的三列信息。更新说明和错误中的长路径允许断行。明细弹窗随内容增长至最大高度，表格按需滚动，标题、工具条和分页始终保留在表格滚动区之外；执行明细的操作列固定在右侧，窄窗口也能直接使用。

## Elevation & Depth

系统默认采用平面层叠：白色工作面叠在浅灰绿画布上，由 1px 细边框和轻微色面差异表达层级。常规卡片不依赖阴影；执行选项弹层、对话框和 toast 才使用浮层阴影。动态内容以颜色、边界和状态点分组，避免把装饰性阴影当作信息层级。

### Shadow Vocabulary

- **执行选项浮层**（`box-shadow: 0 12px 34px #163e3524`）：从工作台中部打开的执行范围设置。
- **对话框和 toast**（使用组件现有的 `shadow-2xl` / `shadow-lg`）：仅用于确认、明细、历史和短时反馈浮层。

`step-arrive` 使用 `180ms ease-out`，toast 进入使用 `160ms ease-out`；`prefers-reduced-motion: reduce` 时将动画和过渡压缩为近乎零时长。

**The Flat Surface Rule.** 静止内容优先使用白底和细边框；阴影只说明浮层脱离工作面，不作为普通卡片的默认装饰。

## Shapes

形状语言以轻微圆角和细边界为主。按钮、输入框、导航项和 worker 卡片使用中等圆角；批次统计和表格使用略大的圆角；弹层与通知使用更明显的圆角。状态点是 7px 圆点，进度条为 8px 圆角，worker 阶段 checkpoint 是 20px 圆形。

表格采用 `border-collapse: collapse`、横向稳定滚动和粘性表头；表格行不使用卡片化阴影。状态标签和筛选器可以使用胶囊形，但仍保持短文本和清晰状态色。输入和选择控件均为白底、细边框、圆角表面；焦点由 2px 主色 `focus-visible` outline 和输入的主色边框共同表达。

## Components

### Buttons

- **Shape:** 中等圆角（`rounded-lg` / `8px`），基础最小高度为 `40px`，执行工作台标题操作提升到 `46px`。
- **Primary:** 使用 `colors.primary` 实心背景和 `colors.on-primary` 文字；水平内边距 `16px`，字重 medium，悬停切换到 `colors.primary-hover`。
- **Secondary:** 白底、`colors.border` 细边框和 `colors.foreground` 文字；悬停使用 `colors.muted`。
- **Ghost:** 透明背景、`colors.ghost-text` 文字；悬停使用 `colors.muted`，适合次要的打开目录、执行选项和轻量链接动作。
- **Danger:** 红色浅底、破坏性文字和浅红悬停面；清除执行记录必须继续通过确认对话框。
- **Focus / Disabled:** 全局键盘焦点保留主色 outline；禁用控件显示 not-allowed 光标并降低不透明度。

### Inputs / Fields

- **Style:** `InputText` 为最小高度 `40px`、8px 圆角、1px `colors.border`、白底、水平内边距 `12px`；placeholder 使用 slate 辅助色，光标使用主色。
- **Focus:** 聚焦时边框切换为 `colors.primary`，键盘操作叠加 2px 主色 outline。
- **Select / Checkbox:** 选择控件延续白底和边框；checkbox/radio 的 accent-color 使用主色。
- **Error / Disabled:** 输入错误使用 destructive 或 amber 文字提示；禁用字段保持现有 opacity 与不可操作光标。

### Cards / Containers

- **Corner Style:** 工作台统计面板使用 10px；worker 卡片和注意提示使用 8px；通用面板和页面卡片通常使用 10–12px；对话框明细可使用 16px。
- **Background:** 默认 `colors.surface`，外层工作区使用 `colors.background`。
- **Shadow Strategy:** 参照 Elevation & Depth；普通卡片不加阴影，浮层才抬升。
- **Border:** 使用 `colors.border` 细边框，分区之间用同色顶/底边界。
- **Internal Padding:** 常见卡片为 `16px`；工作台右侧 inspector 使用 `23px 21px` 基础内边距，窄屏收紧。

### Navigation

- **Sidebar:** `colors.sidebar` 背景、右侧细边框、可收缩宽度；品牌图标使用主色，品牌标题保持单行。
- **Default:** 导航项最小高度 `54px`、8px 圆角、左右 `18px` 内边距，文字使用深灰绿。
- **Hover / Active:** hover 使用浅绿面；active 使用浅翡翠面、深翡翠文字和 2px 左侧主色标记。
- **Topbar:** 白底、底边框、工作空间路径在左，浏览器和卖家中心连接状态在右；连接未知或未登录时使用 amber 操作提示。

### Batch Summary & Status

- **Summary:** 统计面板是白底、1px 边框的连续区域；五个计数按钮可筛选，数字使用 tabular figures。
- **Segmented Progress:** 进度条高度 `8px`，段间以白色 `2px` 分隔；已完成、执行中、待处理、需关注四段互斥，分别使用主色、蓝色、灰色和 amber。段宽由真实行计数计算，不使用固定示例比例。
- **Table Rows:** 商品行同时显示入库状态和图片状态，各自使用带 7px 圆点的 `row-state`。成功、进行中、警示和失败色分别对应当前状态 tone；选中行使用浅翡翠面。

### Worker Checkpoints

- **Card:** 每个真实 `active_workers` 记录显示执行槽、商品、当前阶段和时间；没有商品标识的空槽不伪装为活动任务。
- **Stages:** 固定四步为“资料 / 入库 / 补图核验 / 完成”。已完成阶段显示翡翠圆形 checkpoint 和 `Check` 图标；当前未完成阶段显示蓝色边框与蓝色圆点；未到阶段保持空心边框。
- **Scroll Hint:** worker 超过 2 个时显示“共 N 个任务，上下滚动查看”；卡片自然展开，宽屏由右栏统一滚动，窄屏由整页统一滚动，worker 列表不再嵌套滚动框。

### Attention & Live Events

- **Attention Note:** 阻塞、停滞和首个需关注商品使用注意面、细边框和 amber 文本；提供连接店铺、查看需关注商品或排障工具等就近动作。
- **Live Events:** 最近动态预览最后 4 条记录，使用时间列、事件文本和左侧状态点；通过“查看全部”进入调试页查看完整日志。普通事件为辅助文字，warn/error 分别切换 amber/红色文本和状态点。预览区不设置独立滚动框。
- **Empty State:** 空状态保留图标、短标题、说明和一个下一步按钮，继续引导到商品清单或清空筛选。

## Do's and Don'ts

### Do:

- **Do** 使用现有 `@theme` 颜色、`Button` variant 和 `InputText` 作为新增工作区控件的基础。
- **Do** 让商品表格、统计、筛选、执行槽和最近动态共享真实接口状态，数字和文案随数据更新。
- **Do** 保持入库与图片状态分开，并让待核实结果停留在 amber/需关注语义。
- **Do** 使用真实 `active_workers` 渲染 worker checkpoint；任务多于两个时保留滚动提示。
- **Do** 保留 `focus-visible`、稳定滚动 gutter、tabular numbers 和 reduced-motion 行为。

### Don't:

- **Don't** 把 mock 或截图中的商品名、数量、进度和 ETA 当成业务事实，也不要据此宣称真实淘宝页面验收完成。
- **Don't** 把“仅放入仓库”做成自动上架开关，也不要改变现有填充、提交、图片补充与核验顺序。
- **Don't** 把提交、上传、采纳或核验的未知结果标为完成；未知状态必须保持 amber 或需关注。
- **Don't** 在窄桌面把执行详情固定在右侧导致表格被裁切；应按现有断点移动到表格下方。
- **Don't** 给普通白色工作面添加渐变或常驻装饰阴影；保持当前以色面和细边框表达层级的语言。
