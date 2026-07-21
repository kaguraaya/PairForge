# PairForge

> 题意先立，双图后成。

PairForge 是一个在 Windows 本地运行的双图题库生图工作台。它负责把 DOCX、DOC 或 Markdown 题库解析为独立题目，按范围批量调用图片模型，并严格维持“同题图一 → 同题图二”的依赖关系。

项目主页：<https://github.com/kaguraaya/PairForge>

当前版本：`0.2.0`

## 为什么需要 PairForge

普通批量生图脚本通常只关心“同时发出很多提示词”。双图题库还需要处理更严格的生产逻辑：

1. 每道题必须先生成自己的第一张图。
2. 第一张图只有确定唯一候选后，才能成为同一道题第二张图的参考图。
3. 第二张图不能引用其他题目的图片，也不能因为并发顺序变化而串题。
4. 多候选结果需要人工选择；只有一张候选时应自动选择并继续。
5. API 限流、暂停或程序退出后，未完成工作必须能够恢复。

PairForge 把这些约束写进任务状态机、数据库和调度器，而不是只依靠前端页面顺序。

## 主要功能

- 导入题库后先预览结构，不会立即消耗生图额度。
- 支持按题号范围选择，也可使用双端滑块和常用范围快捷按钮。
- 开始前显示题目数量、图一/图二候选上限、最大图片额度和参考费用。
- 本地并发可设置为 1–12 路；同题图二仍然必须等待本题图一确定。
- 图一、图二可以分别设置追加到每道题原提示词末尾的通用提示词。
- 支持主 API Key 与任意数量备用 Key，并保持不同服务、模型之间完全隔离。
- 支持仅生成一张候选图；服务实际只返回一张时也会自动选择。
- HTTP 429 会优先尝试备用 Key；没有可用备用 Key 时按照 `Retry-After` 或指数退避自动续跑。
- 支持生成途中安全暂停、继续生成和程序异常退出恢复。
- 工作台顶部显示总进度、并发占用、排队、限流等待、待选图、失败和上次中断数量。
- 支持亮色与暗夜主题，并记住本机选择。
- 成品图片平铺导出，不为每道题建立单独文件夹。
- “关于”页面提供版本、仓库链接、数据目录、缓存用量和安全清缓存入口。

## 支持的模型

内置适配：

- Seedream 5.0 Lite（火山方舟）
- Qwen-Image 2.0 / Qwen-Image 2.0 Pro（阿里云百炼）
- Wan2.7 Image / Wan2.7 Image Pro（阿里云百炼）

另外可以添加 OpenAI 风格 JSON 图片接口的自定义服务。不同模型的尺寸格式、候选图语义和专属字段由各自适配器处理，不会把某家厂商的参数发送给另一家。

价格、限流和模型能力可能调整，正式生成前请以厂商控制台和官方文档为准。

## 快速使用

### 1. 放置程序

将 `PairForge.exe` 放在一个普通可写文件夹中，例如：

```text
D:\AI-Tools\PairForge\PairForge.exe
```

首次启动会在 EXE 同级创建：

```text
PairForge_Data\
├─ workbench.sqlite3       # 项目、题目、任务和恢复状态
├─ cache\                  # 可安全清理的导入预览与转换缓存
└─ projects\               # 候选图、成品和项目工作区
```

移动软件时，请把 `PairForge.exe` 和 `PairForge_Data` 一起移动。不要把 EXE 放入 `Program Files` 等普通用户不可写目录。

### 2. 导入题库

进入“导入”，选择题库文件。软件只解析并展示题数、结构错误和警告；点击“确认导入”后仍然不会自动生图。

推荐从公开模板开始：

**[下载 PairForge DOCX 题库模板](templates/PairForge题库模板.docx)**

模板只包含两道占位题，不含原始私人题库内容。复制完整题目区块、修改三位题号和右侧字段即可继续扩展。

### 3. 配置模型与 Key

进入“设置”：

1. 选择内置模型或自定义服务。
2. 选择官方比例快捷项或填写模型允许的尺寸。
3. 保存模型服务。
4. 添加主 Key 和备用 Key；数值越小优先级越高。
5. 按需设置图一、图二候选默认值和两套通用提示词。

API Key 不写入 SQLite、导出文件或日志。选择“记住”时使用 Windows 凭据管理器，否则只保留到本次程序退出。

### 4. 选择范围并生成

进入“工作台”，点击“选择范围并生成”：

1. 拖动滑块或精确选择起止题目。
2. 设置候选图数量、单图模式和本地并发。
3. 先计算最大额度和参考费用。
4. 检查 Key 基础状态后确认开始。

若图一返回多张候选，任务会停在图一选择处；选定后才创建本题图二。若图二返回多张候选，再选择最终图二。只有图一和图二都确定后，该题才算完成。

### 5. 暂停、恢复与限流

- 点击顶部“暂停生成”后，软件不再发出新请求；已经发出的请求仍会保存结果，避免浪费可能已经计费的图片。
- 点击“继续生成”会从未完成阶段续跑。
- 429 冷却任务会显示倒计时，到期自动恢复。
- 程序退出时已排队任务和冷却时间会持久化。
- 退出瞬间仍在厂商侧执行的请求会标为“上次中断”并暂停，防止盲目重发造成双重扣费；回到工作台后点击继续即可建立新请求。

### 6. 导出

“成品”页只导出已完成配对。图片集中在同一个 `final_images` 文件夹：

```text
001__示例答案__01.png
001__示例答案__02.png
002__占位答案__01.png
002__占位答案__02.png
```

CSV 与 JSON 清单位于 `final_images` 上一级，上传图片时不会混入清单文件。

## 支持的题库格式

### DOCX（推荐）

每道题使用：

- 标题：`001｜题目名称`，可在末尾加 `★优先盲测`
- 一个 8 行 2 列字段表格，左列字段名必须保持为：
  - `基本信息`
  - `图1生图提示词`
  - `图1题面提示`
  - `图2生图提示词`
  - `图2题面填空`
  - `答案`
  - `数字声调拼音`
  - `谜底拆解`
- 可选的 `制作检查：...` 段落

题号应使用三位连续编号。`答案字数`必须与答案实际字符数以及图二填空线数量一致。

### DOC

旧版 `.doc` 会先调用本机 LibreOffice 转换为 `.docx`。若系统找不到 `soffice`，请先安装 LibreOffice，或在 Word/WPS 中另存为 `.docx` 后再导入。

### Markdown

扩展名支持 `.md` 和 `.markdown`，UTF-8 编码。最小结构示例：

```markdown
## 001｜题目名称 ★优先盲测

- 类型：作品名
- 难度：★★☆☆☆
- 答案字数：4
- 出处：请填写

### 图1生图提示词
填写图一完整提示词。

### 图1题面提示
填写图一提示。

### 图2生图提示词
说明如何引用同题图一并产生变化。

### 图2题面填空
这是 ＿ ＿ ＿ ＿

### 答案
示例答案

### 数字声调拼音
shi4 li4 da2 an4

### 谜底拆解
填写双图如何共同指向答案。
```

## 缓存与数据安全

“关于 → 清除临时缓存”只删除 `PairForge_Data\cache` 内可以重新生成的导入预览和转换文件，不会删除：

- `workbench.sqlite3`
- 项目与题目状态
- 候选图和已选图片
- 429 冷却与暂停恢复状态
- 导出成品
- Windows 凭据管理器中的 Key

如需自定义数据目录，可在启动前设置环境变量 `WORKBENCH_DATA_DIR`。

## 开发者指南

### 环境要求

- Windows 10/11
- Python 3.12+
- Node.js 20+
- pnpm 10+
- 可选：LibreOffice（仅导入旧 `.doc` 和 DOCX 本地渲染检查需要）

### 安装

```powershell
git clone https://github.com/kaguraaya/PairForge.git
cd PairForge

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
pnpm --dir frontend install --frozen-lockfile
```

### 本地开发

终端一：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

终端二：

```powershell
pnpm --dir frontend dev
```

开发版默认数据也位于仓库根目录 `PairForge_Data`。测试通过显式临时目录运行，不会调用真实付费生图服务。

### 测试与代码检查

```powershell
.\.venv\Scripts\python.exe -m ruff check backend\app backend\tests
.\.venv\Scripts\python.exe -m pytest -q
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

如需用真实模板做额外解析回归：

```powershell
$env:REFERENCE_DOCX='D:\path\to\question-bank.docx'
.\.venv\Scripts\python.exe -m pytest backend\tests\importers\test_reference_docx.py -q
```

### 构建 Windows 单文件程序

```powershell
.\scripts\build-windows.ps1
```

产物位于：

```text
release\PairForge.exe
```

构建脚本同时把 `README.md` 和公开 DOCX 模板复制到 `release`。不要提交 `release`、`build`、`frontend/dist`、`.venv`、`node_modules` 或 `PairForge_Data`。

## 源码目录

```text
PairForge\
├─ backend\              # FastAPI、SQLite、调度器、模型适配器与测试
├─ frontend\             # Vue 3 + Element Plus 界面与前端测试
├─ launcher\             # Windows 单文件启动器
├─ scripts\              # 开发启动与 PyInstaller 构建脚本
├─ templates\            # 可公开导入的脱敏题库模板
├─ pyproject.toml
├─ README.md
└─ .gitignore
```

## 安全说明

- 服务只监听随机的 `127.0.0.1` 端口。
- API Key 不通过接口回显，不写入数据库和导出清单。
- 内置提供商限制到对应官方 HTTPS 域名；自定义服务要求 HTTPS。
- 图片 URL 下载会拒绝本地和私有网络地址。
- 上传 DOCX 有压缩包条目数、原始大小和解压后大小限制。
- 清缓存 API 的删除范围固定在 `PairForge_Data\cache`，不会扩展到数据根目录或项目目录。
