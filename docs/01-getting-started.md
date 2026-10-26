# 快速开始

本文覆盖 Label Once 的环境要求、依赖安装、模型权重准备，以及源码/成品两种启动方式。更完整的架构说明见 [架构总览](./02-architecture.md)。

---

## 1. 环境要求

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 x64 | 桌面端为 WPF，后端脚本使用 PowerShell |
| Python | 3.10 x64 | `pyproject.toml` 限定 `>=3.10,<3.11` |
| .NET SDK | 10.0.x | `desktop/global.json` 锁定 10.0.403，`rollForward: latestFeature` |
| GPU | 可选 | NVIDIA GPU + 对应驱动；CPU 可完成标注、抽帧和部分推理 |
| 磁盘 | 建议充足 | 模型权重、视频帧、数据集版本会占用较大空间 |

> 生产依赖以 `requirements.lock.txt` 为准；`requirements.txt` 是高层依赖清单，不含完整传递依赖。

---

## 2. 安装（推荐脚本）

仓库提供了一套从零准备环境的 PowerShell 脚本：

```powershell
# 仓库根目录
./scripts/install.ps1
```

`scripts/install.ps1` 会转调 `desktop/scripts/setup.ps1`，主要步骤：

1. 通过 Conda 创建名为 `labelonce` 的 Python 3.10 环境；
2. 从 PyTorch cu128 源安装 `torch==2.11.0`、`torchvision==0.26.0`；
3. 安装 `requirements.lock.txt` 中的锁定依赖（PyPI + NVIDIA/PyTorch 额外索引）；
4. 执行 `pip check` 验证依赖一致性；
5. 在 `.tools/dotnet` 安装项目专用 .NET SDK，不修改系统 `PATH`；
6. 调用 `scripts/prepare_models.ps1` 复制模型权重。

如果已经有可用的 Python 3.10 环境，也可以手动安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements.lock.txt
python -m pip check
```

### 只跑 Python 测试的最小依赖

测试通过 `sys.modules` 注入假的 `ultralytics` 模块，因此**不需要安装 torch/ultralytics**：

```powershell
python -m pip install pytest PyQt5 numpy opencv-python Pillow PyYAML
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

这也是 CI 使用的依赖集合，详见 [构建、打包与 CI](./11-build-release-ci.md) 和 [测试与验收](./12-testing.md)。

---

## 3. 模型权重

权重不进入 Git。`models/` 与 `sam/` 仅保留 `README.md`，其余 `*.pt` 被 `.gitignore` 忽略。

```powershell
# 从配套成品目录复制（默认 ../Release/TrainStudio）
./scripts/prepare_models.ps1

# 或显式指定来源
./scripts/prepare_models.ps1 -ModelSource "D:\LabelOnce\Release\TrainStudio"
```

脚本会把来源目录下 `models/*.pt` 和 `sam/*.pt` 复制到仓库对应目录。常见权重：

- YOLO 检测/分割权重：`yolo11n.pt`、自定义训练产物；
- SAM/SAM2 权重：用于交互式分割或视频跟踪；
- 训练产生的 `best.pt` 会复制到项目的 `Model/<run>.pt`，不会写入仓库根目录。

> TensorRT `.engine` 与 GPU、驱动和 TensorRT 运行时强绑定；跨机器分发时优先携带 `.pt` 或 ONNX，在目标机器重新导出。

---

## 4. 启动方式

### 4.1 源码启动 PyQt5 界面（旧入口，仍保留）

```powershell
python launch.py
# 等价于
python -m studio.app
```

`launch.py` 除了 GUI，还承担 worker/DDP 子进程入口的分发，详见 [架构总览](./02-architecture.md)。

### 4.2 源码启动 WPF 桌面端（当前主界面）

```powershell
# 编译并启动；可选传入项目目录
./desktop/scripts/start.ps1
./desktop/scripts/start.ps1 -Project "D:\data\我的项目"
```

脚本会执行 `dotnet build desktop/LabelOnce.sln -c Release`，然后启动：

```text
desktop/LabelOnce.Desktop/bin/Release/net10.0-windows/LabelOnce.exe
```

WPF 启动时会通过 `BridgeClient` 拉起 Python 后端：

- 优先使用 `LABELONCE_BACKEND` 指向的 `backend.exe`；
- 否则使用发布目录下的 `backend/backend.exe --bridge`；
- 开发环境下回退到 `python -m studio.bridge`，Python 解释器可用 `LABELONCE_PYTHON` 指定。

### 4.3 运行已构建的成品

```text
Release/TrainStudio-WPF/LabelOnce.exe
```

分发时必须复制**整个目录**，保留 `backend/`、`models/`、`sam/` 和全部运行库；不要只复制 EXE。构建方法见 [构建、打包与 CI](./11-build-release-ci.md)。

---

## 5. 第一个项目

1. 启动桌面端，选择“新建/打开项目”，指定一个空目录或已有项目目录；
2. 在“管理类别”中建立类别名称（顺序即类别 ID，后续只建议追加）；
3. 导入图片或视频；
4. 在标注页绘框或使用 SAM 辅助分割；
5. 按 `F` 确认当前图片（保存不等于复核）；
6. 进入训练页创建数据集版本、配置参数并开始训练；
7. 训练完成后评估、跑发布门禁、导出模型。

完整流程见 [从标注到训练：端到端流程](./ANNOTATION_TO_TRAINING.md)。

---

## 6. 目录速览

```text
Label Once/
├── desktop/            # .NET 10 WPF 桌面端与几何/测试项目
├── studio/             # Python 后端：领域模型、服务、任务、视觉流水线
├── scripts/            # 安装、构建、模型准备、验收与门禁脚本
├── tests/              # Python 测试
├── docs/               # 文档中心（本目录）
├── models/             # 本地 YOLO 权重（忽略提交）
├── sam/                # 本地 SAM/SAM2 权重（忽略提交）
├── train/              # 训练产物目录
├── Release/            # 本地发布产物（忽略提交）
├── launch.py           # Qt GUI / worker / DDP 启动入口
├── backend_launch.py   # 冻结后端 / worker 启动入口
├── Backend.spec        # 后端 PyInstaller 配置
└── YoloTrainStudio.spec# Qt 版 PyInstaller 配置
```

---

## 7. 下一步

- 想了解界面操作与快捷键：[WPF 桌面端](./10-desktop-client.md)
- 想理解后端如何被调用：[桥接协议](./09-bridge-protocol.md)
- 启动失败或测试失败：[故障排查](./13-troubleshooting.md)