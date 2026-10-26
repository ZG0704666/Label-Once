<div align="center">

<img src="desktop/LabelOnce.Desktop/logo.png" width="128" alt="Label Once 图标">

# You Only Label Once 你只需标一次

**一体化的 Windows 本地 AI 视频跟踪标注训练平台**

图像标注 · 视频跟踪 · SAM 辅助分割 · 训练评估 · 发布门禁 · 模型导出

[![平台](https://img.shields.io/badge/平台-Windows%2010%2F11-2563eb?logo=windows&logoColor=white)](#环境要求)
[![桌面端](https://img.shields.io/badge/桌面端-.NET%2010%20WPF-512bd4?logo=dotnet&logoColor=white)](#技术架构)
[![后端](https://img.shields.io/badge/后端-Python%203.10-3776ab?logo=python&logoColor=white)](#环境要求)
[![数据格式](https://img.shields.io/badge/数据格式-YOLO-22c55e)](#核心能力)
[![构建状态](https://img.shields.io/badge/构建-可发布-16a34a)](#开发与构建)
[![开源协作](https://img.shields.io/badge/GitHub-Issues%20%7C%20Releases-181717?logo=github&logoColor=white)](#参与贡献)

[快速开始](#快速开始) · [核心能力](#核心能力) · [技术架构](#技术架构) · [开发与构建](#开发与构建) · [参与贡献](#参与贡献)

</div>

---

Label Once 是一个面向 Windows 本地部署的 AI 标注与数据训练工作台，聚焦图像/视频数据集的标注、筛选、训练、评估与模型导出。

它采用“桌面端 UI + Python 后端”的双层架构：

- WPF 桌面端负责交互、画布操作和工作流入口
- Python 后端负责数据管理、模型任务、训练/评估编排和 SAM / YOLO 相关逻辑

该项目适合用于本地标注团队、实验室数据处理以及小规模 AI 标注闭环流程。

---

## 项目简介

Label Once 旨在将数据标注、数据集清洗、训练准备、模型推理与导出流程整合在一个本地工作区中，减少对第三方平台的依赖，并保持对本地数据和模型资产的完全控制。

核心目标包括：

- 图像与视频目标标注
- AI 辅助预标注与 SAM / SAM2 工作流
- YOLO 兼容数据集组织与处理
- 训练、评估与导出闭环
- 本地部署，适合离线或受控环境

---

## 核心能力

### 1. 图像与视频标注

- 图片批量导入与项目管理
- 视频抽帧、关键帧处理及后续复审
- 框选、分割、目标编辑与目标状态管理
- 适配项目级标签、类别与数据版本管理

### 2. AI 辅助标注

- 集成 SAM / SAM2 类能力用于候选分割与目标辅助生成
- 支持人工校正、目标修正和后续复审
- 结合 YOLO 训练数据结构进行标签规范输出

### 3. 训练与评估工作流

- 训练任务与数据版本绑定
- 评估、推理和模型导出入口统一
- 支持本地权重、参数配置与工程化日志跟踪

### 4. 本地化部署

- Windows 优先，适合桌面端本地执行
- 大模型权重与生成产物保持在本地，不强制托管到 Git
- 便于在实验环境、内网环境或离线场景中使用

---

## 技术架构

```text
Label Once
├── desktop/            # WPF 桌面端，负责交互与 UI
├── studio/             # Python 后端，负责标注、训练、评估与数据处理
├── scripts/            # 构建、环境准备、验证脚本
├── tests/              # 自动化测试与回归验证
├── models/             # 本地模型权重目录（本地保留，不建议提交）
├── sam/                # SAM / SAM2 权重目录（本地保留，不建议提交）
├── train/              # 训练产物与权重输出目录
├── requirements.txt    # Python 依赖清单
├── requirements.lock.txt
├── pyproject.toml      # Python 项目元数据
├── README.md           # 项目说明
├── .gitignore          # Git 忽略规则
├── launch.py           # Python 启动入口
├── backend_launch.py   # 后端启动入口
└── Release/            # 本地发布目录（构建产物）
```

---

## 目录说明

### `desktop/`

- .NET WPF 应用
- 提供标注界面、工作流入口和本地桌面交互
- 主要产品入口位于：`desktop/LabelOnce.Desktop`

### `studio/`

- Python 处理逻辑核心
- 包含标注、工作区、对象跟踪、分割、训练编排等模块
- 负责连接前端 UI 与底层模型/数据流程

### `scripts/`

- 环境初始化脚本
- 构建脚本
- 验证脚本
- 模型准备脚本

### `models/` 与 `sam/`

本目录用于存放本地大模型权重文件。这类文件通常体积较大，通常不适合提交到 GitHub。仓库中已配套 `.gitignore` 规则进行过滤。

### `train/`

- 存放训练输出、检查点与运行时工件
- 不建议将大规模训练产物直接提交到仓库

---

## 环境要求

### Windows

- Windows 10 / 11
- Python 3.10 x64
- .NET SDK 10（项目已声明对应要求）
- 可选：NVIDIA GPU（用于加速训练与推理）

### 依赖说明

项目依赖项可通过以下方式安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如需固定版本环境，可使用：

```powershell
pip install -r requirements.lock.txt
```

---

## 快速开始

### 1. 运行源码

```powershell
python -m studio.app
```

或直接使用项目中的启动入口：

```powershell
python launch.py
```

### 2. 运行发布版

已构建的本地 Release 可直接运行：

```text
Release/TrainStudio-WPF/LabelOnce.exe
```

在本地开发中，推荐使用桌面端发布产物来验证 UI 与后端联动。

---

## 开发与构建

### 需要的工具

- Python 3.10
- .NET SDK 10
- WPF 相关运行时
- 可选的 CUDA 环境（如需 GPU 训练/推理）

### 构建说明

项目中的桌面端构建逻辑位于 `desktop/`，可以通过命令行发布 App：

```powershell
dotnet publish .\desktop\LabelOnce.Desktop\LabelOnce.Desktop.csproj -c Release -r win-x64 --self-contained true -o .\Release\TrainStudio-WPF
```

发布产物会生成 win-x64 可执行文件和运行时依赖，适合本地测试和交付。

---

## 版本与发布说明

项目已实现：

- 本地桌面应用入口
- 图像/视频标注流程
- SAM 辅助分割能力
- 模型训练与评估工作流
- 本地权重与数据集管理

发布目录中，核心可执行文件为：

```text
Release/TrainStudio-WPF/LabelOnce.exe
```

该目录应保留完整运行依赖，不建议只复制 EXE 文件单独分发。

---

## Git 提交建议

为了保持仓库整洁并便于在 GitHub 发布，建议遵循以下规则：

- 提交代码源文件
- 不提交大模型权重
- 不提交构建产物
- 不提交缓存目录和临时日志
- 不提交本地标注副产物与训练中间结果

当前仓库已配置 `.gitignore`，重点忽略：

- `models/*.pt`, `models/*.onnx`, `models/*.engine`
- `sam/*.pt`, `sam/*.pth`, `sam/*.onnx`
- `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- `build/`, `dist/`, `bin/`, `obj/`
- `runs/`, `outputs/`, `logs/`
- 本地标注文件：`*.annotation.json`, `*.segments.json`, `*.mark`

---

## 适用场景

Label Once 适合以下场景：

- 目标检测数据集标注
- 分割任务前期标注与修正
- 视频追踪与抽帧标注
- 本地实验场景的训练脚本与评估脚本
- 需要强本地控制的 AI 标注工作流

---

## GitHub 项目特性

将项目发布到 GitHub 后，建议启用以下能力：

| GitHub 能力 | 用途 |
|---|---|
| **Releases** | 发布 `LabelOnce.exe` 的完整压缩包和版本说明 |
| **Issues** | 收集 Bug、功能建议和环境兼容性问题 |
| **Discussions** | 讨论标注工作流、模型配置和使用经验 |
| **Projects** | 跟踪版本规划、开发任务和验收进度 |
| **Actions** | 自动执行 Python 测试、.NET 构建和发布检查 |
| **Topics** | 建议添加 `annotation`、`yolo`、`sam`、`computer-vision`、`wpf`、`python` |

### 推荐的 GitHub 首页内容

- 在仓库 About 中填写项目简介和官方网站/文档地址
- 添加 `computer-vision`、`dataset-labeling`、`yolo` 等 Topics
- 使用 Releases 发布可运行的 Windows x64 安装包或压缩包
- 不在仓库中提交模型权重、用户数据集和训练输出
- 使用 Issue 模板区分 Bug、功能请求和部署问题

当前仓库已经准备好基础的 README 和 `.gitignore`。GitHub Actions、Issue 模板和 Release 上传需要在仓库初始化并上传后再配置。

---

## 路线图

- [x] WPF 桌面端基础工作区
- [x] 图像与视频标注流程
- [x] YOLO 标签与数据集处理
- [x] SAM / SAM2 辅助能力
- [x] 训练、评估与模型导出入口
- [x] Windows x64 本地发布
- [ ] GitHub Actions 自动测试与构建
- [ ] GitHub Release 自动打包
- [ ] 完善中英文文档与演示截图

---

## 截图与演示

当前仓库已包含应用图标，位于 `desktop/LabelOnce.Desktop/logo.png`。后续可以在此处补充实际运行截图或演示 GIF，例如：

```text
docs/
├── screenshots/
│   ├── workspace.png
│   ├── annotation.png
│   └── training.png
└── demo.gif
```

建议截图中隐藏本地数据集路径、API Key、个人信息和未发布模型文件。

---

## 参与贡献

欢迎通过以下方式参与：

1. 提交 Issue，报告可复现的问题或提出功能建议。
2. Fork 项目并创建独立分支。
3. 保持修改范围清晰，补充必要的测试或文档。
4. 提交 Pull Request，并说明验证方式和兼容环境。

提交前请确认：

- 没有包含模型权重、数据集或敏感信息
- 没有包含 `Release/`、`dist/`、`build/` 等生成目录
- 没有包含 Python 缓存、日志和训练中间文件
- README、脚本和配置中的项目名称统一为 `Label Once`

---

## 许可证与说明

该项目中使用的第三方模型、运行时和依赖组件仍受各自许可证约束。仓库中的代码与工程结构用于本地开发、研究与自发式部署，不应将大模型权重或第三方版权资产无序纳入版本控制。

---

## 维护建议

- 保持项目命名统一为 `Label Once`
- 将模型文件与运行产物放在本地目录，不纳入 Git
- 优先保留源码、脚本、配置和测试用例
- 在提交前确认是否含有生成文件或大型二进制

---

## 结语

Label Once 致力于构建一个简洁、可扩展、可本地化运行的数据标注与训练平台。它既适合单机开发与实验，也可以作为基础框架继续演进为更加完整的标注工作流平台。

如果你准备把本项目发布到 GitHub，建议优先保留：

- 源代码
- 文档
- 构建脚本
- 测试
- `.gitignore`

而将所有大模型、训练产物和本地运行缓存视为非提交项。
