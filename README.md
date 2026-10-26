<div align="center">

<img src="desktop/LabelOnce.Desktop/logo.png" width="128" alt="Label Once 图标">

# You Only Label Once 你只需标一次

**一体化的 Windows 本地 AI 视频跟踪标注训练平台**

图像标注 · 视频跟踪 · SAM 辅助分割 · 训练评估 · 发布门禁 · 模型导出

[![平台](https://img.shields.io/badge/平台-Windows%2010%2F11-2563eb?logo=windows&logoColor=white)](#环境要求)
[![桌面端](https://img.shields.io/badge/桌面端-.NET%2010%20WPF-512bd4?logo=dotnet&logoColor=white)](#技术架构)
[![后端](https://img.shields.io/badge/后端-Python%203.10-3776ab?logo=python&logoColor=white)](#环境要求)
[![数据格式](https://img.shields.io/badge/数据格式-YOLO-22c55e)](#核心能力)
[![许可证](https://img.shields.io/badge/许可证-AGPL--3.0-blue?logo=gnu)](./LICENSE)
[![构建状态](https://github.com/ZG0704666/Label-Once/actions/workflows/ci.yml/badge.svg)](https://github.com/ZG0704666/Label-Once/actions/workflows/ci.yml)
[![开源协作](https://img.shields.io/badge/GitHub-Issues%20%7C%20Releases-181717?logo=github&logoColor=white)](#参与贡献)

[快速开始](#快速开始) · [文档中心](./docs/README.md) · [核心能力](#核心能力) · [技术架构](#技术架构) · [开发与构建](#开发与构建) · [参与贡献](#参与贡献)

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
- AI 辅助预标注与 SAM 工作流
- YOLO 兼容数据集组织与处理
- 训练、评估与导出闭环
- 本地部署，适合离线或受控环境

---

## 文档中心

完整文档位于 [`docs/`](./docs/README.md)，按角色和任务组织：

| 文档 | 内容 |
| --- | --- |
| [快速开始](./docs/01-getting-started.md) | 环境、依赖、模型权重、源码/成品启动 |
| [架构总览](./docs/02-architecture.md) | WPF、Python 后端、worker 与文件通信 |
| [项目目录与数据格式](./docs/03-project-layout-and-formats.md) | 项目目录、标注 sidecar、复核台账、数据集版本 |
| [图像标注与复核](./docs/04-annotation-workflow.md) | 导入、绘框、SAM、轮廓、保存与复核语义 |
| [视频抽帧与 SAM2 跟踪](./docs/05-video-workflow.md) | 时间戳抽帧、暂停纠偏、质量门、关键帧回填 |
| [数据集版本与整合](./docs/06-dataset-workflow.md) | 复核门槛、分组划分、版本激活、多来源合并 |
| [训练、评估与导出](./docs/07-training-evaluation-export.md) | 训练参数、续训、评估、推理、ONNX/OpenVINO/TensorRT |
| [发布门禁](./docs/08-release-gate.md) | 类别顺序、泄漏、mAP 下限、逐类跌幅、量化掉点 |
| [桥接协议](./docs/09-bridge-protocol.md) | JSONL v1 请求/响应/事件、方法表、错误语义 |
| [WPF 桌面端](./docs/10-desktop-client.md) | 页面、快捷键、坐标变换、后端连接 |
| [构建、打包与 CI](./docs/11-build-release-ci.md) | PyInstaller、WPF 发布、CI 作业与 torch DLL 修复 |
| [测试与验收](./docs/12-testing.md) | Python/.NET 测试矩阵、验收脚本 |
| [故障排查](./docs/13-troubleshooting.md) | CI、torch、后端、Qt、SAM2、导出等常见问题 |
| [术语表](./docs/14-glossary.md) | 项目内高频概念与缩写 |

端到端流程、数据集整合规范、渐进式验收和 WPF 成品验收也都在 [`docs/`](./docs/README.md) 中。

---

## 核心能力

### 1. 图像与视频标注

- 图片批量导入与项目管理
- 视频抽帧、关键帧处理及后续复审
- 框选、分割、目标编辑与目标状态管理
- 适配项目级标签、类别与数据版本管理

### 2. AI 辅助标注

- 集成 SAM 类能力用于候选分割与目标辅助生成
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
├── docs/               # 文档中心（入门、流程、协议、构建、验收）
├── models/             # 本地模型权重目录（本地保留，不建议提交）
├── sam/                # SAM 权重目录（本地保留，不建议提交）
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

### 1. 准备环境

```powershell
# 创建完整 Python 环境、安装 .NET SDK 并复制模型权重
./scripts/install.ps1
```

### 2. 运行源码

WPF 桌面端（当前主界面）：

```powershell
./desktop/scripts/start.ps1
```

旧版 PyQt5 界面：

```powershell
python -m studio.app
```

或直接使用项目中的启动入口：

```powershell
python launch.py
```

### 3. 运行发布版

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
- 本地权重与数据集版本管理

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

本项目采用 [GNU Affero General Public License v3.0（AGPL-3.0）](./LICENSE) 开源。使用、修改或再分发本项目代码时，请遵守 AGPL-3.0 的条款，并在通过网络提供修改版本服务时履行相应的源代码提供义务。

本项目中使用的第三方模型、运行时和依赖组件仍受各自许可证约束。仓库中的代码与工程结构用于本地开发、研究与自发式部署，不应将大模型权重或第三方版权资产无序纳入版本控制。

---

## 📊 项目状态

[![GitHub stars](https://img.shields.io/github/stars/ZG0704666/Label-Once?style=social)](https://github.com/ZG0704666/Label-Once/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ZG0704666/Label-Once?style=social)](https://github.com/ZG0704666/Label-Once/network/members)
[![GitHub issues](https://img.shields.io/github/issues/ZG0704666/Label-Once)](https://github.com/ZG0704666/Label-Once/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/ZG0704666/Label-Once)](https://github.com/ZG0704666/Label-Once/commits/main)

---

<div align="center">

**如果这个项目对你有帮助，请给我们一个 ⭐ Star！**

Made with ❤️ by [ZG0704666](https://github.com/ZG0704666)

[返回顶部](#you-only-label-once-你只需标一次)

</div>
