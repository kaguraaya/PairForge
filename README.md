# PairForge

> 面向双图题库的 Windows 本地批量生图工作台。

PairForge 将 DOCX、DOC 或 Markdown 题库解析为独立题目，按指定范围并发生成图片，并严格保证每道题都遵循：

```text
本题图一生成 → 选定本题图一 → 以该图为参考生成本题图二 → 完成配对
```

题目之间不会混用参考图。生成被暂停、遇到 HTTP 429 或程序意外退出后，任务可以从已保存状态继续。

当前版本：`0.3.0`

## 当前适配状态

| 模型 | 状态 | 说明 |
| --- | --- | --- |
| Seedream 5.0 Lite | **重点特化** | 已适配文生图、参考图生图、组图/单图、尺寸规则、错误分类、429 恢复，以及普通按量与 Agent Plan 两种接口 |
| Seedream 4.5 / 4.0 | 测试适配 | 已接入基础调用，建议先用少量题目试跑 |
| Qwen-Image 2.0 / Pro | 测试适配 | 已接入阿里云百炼接口，仍需覆盖更多账号与地域配置 |
| Wan2.7 Image / Pro | 测试适配 | 已接入阿里云百炼接口，仍需覆盖更多真实任务 |
| OpenAI 风格自定义图片接口 | 实验性 | 由用户填写地址、模型 ID、候选上限与尺寸 |

目前只有 **Seedream 5.0 Lite** 作为主要生产目标进行了完整特化。其余模型虽然已有独立适配器和自动化测试，但不同厂商账号、地域、模型版本可能存在差异，请勿未经小批量验证直接运行整套题库。

## 功能

- 导入后先检查题库结构，不会立即调用生图 API。
- 使用双端滑块、题号选择器或快捷按钮选择生成范围。
- 开始前显示题目数、候选图上限、最大图片额度和参考费用。
- 支持 1–12 路并发，同时保持每道题内部的图一、图二依赖顺序。
- 图一与图二可分别设置通用提示词，自动追加在文档提示词末尾。
- 支持主 API Key 和任意数量备用 Key。
- 可强制只生成一张候选图；实际只返回一张时自动选定并继续。
- HTTP 429 时优先切换备用 Key，否则按 `Retry-After` 或退避时间自动恢复。
- 支持手动暂停、继续，以及程序重启后的任务恢复。
- 工作台顶部显示批次总进度、并发、排队、限流等待和失败状态。
- 亮色、暗夜模式完整适配。
- 成品图片集中平铺导出，不为每道题创建单独文件夹。
- API Key 可保存到 Windows 凭据管理器，不写入项目数据库和导出文件。

## 快速开始

### 1. 运行程序

将 `PairForge.exe` 放在普通可写目录中，例如：

```text
D:\AI-Tools\PairForge\PairForge.exe
```

双击运行后，软件会打开本地网页。不要将程序放入普通用户无法写入的 `Program Files` 等目录。

### 2. 导入题库

进入“导入”，选择 `.docx`、`.doc`、`.md` 或 `.markdown` 文件。确认预览无严重错误后再导入。

[下载 PairForge DOCX 题库模板](templates/PairForge题库模板.docx)

模板仅含两道占位题，不包含原始私人题库内容。

### 3. 配置模型与 API Key

进入“设置”：

1. 选择模型。
2. 火山方舟用户选择“普通按量 API”或“Agent Plan 套餐 API”。
3. 选择画面比例或填写合法尺寸。
4. 保存服务并添加主 Key、备用 Key。
5. 设置候选图数量与图一/图二通用提示词。

### 4. 选择范围并生成

进入“工作台”，点击“选择范围并生成”：

1. 拖动范围滑块或精确选择起止题目。
2. 选择单候选或多候选模式。
3. 设定并发数。
4. 核对最大额度后开始。

图一出现多个候选时，必须先选定一张，系统才会创建同一道题的图二任务。只有一张候选时会自动选定。

## 火山方舟调用通道

Seedream 设置中提供两种互斥通道：

| 选项 | 实际接口 | 适用情况 |
| --- | --- | --- |
| 普通按量 API | `/api/v3/images/generations` | 未订阅 Agent Plan，或希望使用普通按量计费 |
| Agent Plan 套餐 API | `/api/plan/v3/images/generations` | 已订阅 Agent Plan，希望消耗套餐 AFP 额度 |

Agent Plan 用户必须同时使用套餐控制台生成的**专属 API Key**。火山方舟控制台明确提示：如果套餐用户调用普通 `/api/v3` 图片接口，会产生套餐外按量费用。

- [Agent Plan 图片生成 API 参考](https://www.volcengine.com/docs/82379/1666945?lang=zh)
- [普通图片生成 API 参考](https://api.volcengine.com/api-docs/view?action=ImageGenerations&serviceCode=ark&version=2024-01-01)

旧版 PairForge 配置升级后默认保持“普通按量 API”，不会在没有提示的情况下改变计费通道。请在正式生成前到设置页确认一次。

## 图片保存在哪里

首次运行会在 EXE 同级创建 `PairForge_Data`：

```text
PairForge.exe
PairForge_Data\
├─ workbench.sqlite3
├─ cache\
└─ projects\
   └─ <项目ID>\
      ├─ assets\
      │  ├─ q1_candidates\      # 图一候选图，生成后立即保存
      │  ├─ q2_candidates\      # 图二候选图，生成后立即保存
      │  └─ rejected\
      └─ exports\
         └─ <导出时间>\
            ├─ final_images\    # 可直接上传的平铺成品图片
            ├─ manifest.csv
            └─ manifest.json
```

工作台顶部会显示当前项目的**候选图片精确路径**，可点击“打开图片文件夹”。“关于”页面也可以打开总数据目录和项目图片目录。

需要上传最终成品时，请进入“成品”页执行导出，然后使用最新导出批次里的 `final_images`。文件名示例：

```text
001__示例答案__01.png
001__示例答案__02.png
002__占位答案__01.png
002__占位答案__02.png
```

移动软件时，请把 `PairForge.exe` 与同级 `PairForge_Data` 一起移动。

## 题库格式

### DOCX（推荐）

每道题由标题和一个 8 行 2 列表格组成。标题格式为 `001｜题目名称`，表格左列字段依次为：

- 基本信息
- 图1生图提示词
- 图1题面提示
- 图2生图提示词
- 图2题面填空
- 答案
- 数字声调拼音
- 谜底拆解

题号使用连续三位编号。答案字数、答案内容和图二填空线数量应保持一致。

### DOC

旧版 `.doc` 需要本机安装 LibreOffice 才能自动转换。也可以先在 Word/WPS 中另存为 `.docx`。

### Markdown

支持 UTF-8 编码的 `.md` 和 `.markdown`。最小示例：

```markdown
## 001｜题目名称 ★优先盲测
- 类型：作品名
- 难度：★★★
- 答案字数：4

### 图1生图提示词
填写第一张图的完整提示词。

### 图1题面提示
填写图一提示。

### 图2生图提示词
说明如何引用同题图一并产生变化。

### 图2题面填空
这是____

### 答案
示例答案

### 数字声调拼音
shi4 li4 da2 an4

### 谜底拆解
填写双图如何共同指向答案。
```

## 暂停、恢复与 429

- “暂停生成”停止发出新请求；已经发送的请求仍会接收并保存结果。
- “继续生成”从未完成阶段续跑。
- 429 任务会进入冷却并显示倒计时，到期后自动继续。
- 排队状态、冷却时间和已完成结果保存在 SQLite 中。
- 程序异常退出时，正在厂商侧执行但结果未知的请求会标为“上次中断”，避免盲目重发造成重复计费。

## 缓存清理

“关于 → 清除临时缓存”只删除 `PairForge_Data\cache` 中可重新生成的导入预览和格式转换文件，不会删除：

- 项目、题目和任务状态
- 候选图与已选图片
- 导出成品
- 429 冷却与暂停恢复状态
- Windows 凭据管理器中的 API Key

## 本地开发

### 环境

- Windows 10/11
- Python 3.12+
- Node.js 20+
- pnpm 10+
- 可选：LibreOffice（导入旧 `.doc`）

### 安装依赖

```powershell
git clone <repository-url>
cd PairForge

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
pnpm --dir frontend install --frozen-lockfile
```

### 启动开发环境

后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

前端：

```powershell
pnpm --dir frontend dev
```

### 测试

```powershell
.\.venv\Scripts\python.exe -m ruff check backend\app backend\tests
.\.venv\Scripts\python.exe -m pytest -q
pnpm --dir frontend test
pnpm --dir frontend build
```

测试使用本地临时目录和模拟提供商，不会调用真实付费生图接口。

### 构建 Windows 单文件程序

```powershell
.\scripts\build-windows.ps1
```

产物位于：

```text
release\PairForge.exe
```

## 源码结构

```text
PairForge\
├─ backend\       # FastAPI、SQLite、任务调度、模型适配与测试
├─ frontend\      # Vue 3 界面与前端测试
├─ launcher\      # Windows 单文件启动器
├─ scripts\       # 开发与构建脚本
├─ templates\     # 脱敏题库模板
├─ pyproject.toml
└─ README.md
```

`release`、`build`、`frontend/dist`、`.venv`、`node_modules`、缓存和 `PairForge_Data` 不应提交到 Git。

## 安全说明

- 服务只监听随机的 `127.0.0.1` 本地端口。
- API Key 不通过接口回显，不写入 SQLite 或导出清单。
- 内置提供商只允许对应官方 HTTPS 域名。
- 图片下载会拒绝本机地址和私有网络地址。
- 清缓存接口固定限制在 PairForge 缓存目录。
- “打开文件夹”接口只能访问 PairForge 数据、候选图和导出目录。
