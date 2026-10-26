# 构建、打包与 CI

本文说明如何构建 Qt 版/后端/WPF 成品、PyInstaller 配置要点，以及 GitHub Actions 流水线的结构与本次 CI 修复。

---

## 1. 构建脚本一览

| 脚本 | 作用 |
| --- | --- |
| `scripts/install.ps1` | 安装 Python/Conda 环境、依赖、.NET SDK、模型权重 |
| `desktop/scripts/setup.ps1` | 安装的实际实现 |
| `scripts/build.ps1` | 用 `YoloTrainStudio.spec` 打包 Qt 版到 `dist/YoloTrainStudio` |
| `desktop/scripts/build.ps1` | 打包后端 + 发布 WPF 到 `Release/TrainStudio-WPF` |
| `desktop/scripts/start.ps1` | 编译并启动 WPF（可传项目路径） |
| `desktop/scripts/test.ps1` | Python 测试 + Core 几何测试 |
| `scripts/prepare_models.ps1` | 从配套成品目录复制 `.pt` 权重 |
| `scripts/lock_environment.py` | 重新生成 `requirements.lock.txt` |

---

## 2. Qt 版构建

```powershell
./scripts/build.ps1
```

流程：

1. 调用 `python -m PyInstaller --noconfirm --clean YoloTrainStudio.spec`；
2. 复制 `models/*.pt`、`sam/*.pt` 到 `dist/YoloTrainStudio/`；
3. 复制 `README.md`、`requirements.lock.txt`；
4. 复制整个 `docs/` 到成品目录。

产物入口：`dist/YoloTrainStudio/YoloTrainStudio.exe`（Qt 版）。

---

## 3. WPF 成品构建

```powershell
./desktop/scripts/build.ps1
```

流程：

1. 用 `Backend.spec` 打包 Python 后端到 `dist/backend`；
2. `dotnet publish desktop/LabelOnce.Desktop/LabelOnce.Desktop.csproj -c Release -r win-x64 --self-contained true -p:RestoreLockedMode=true -p:PublishSingleFile=false -o Release/TrainStudio-WPF`；
3. 把 `dist/backend/*` 复制到 `Release/TrainStudio-WPF/backend/`；
4. 复制 `models/*.pt`、`sam/*.pt`；
5. 复制 `desktop/README.md`、`requirements.lock.txt` 以及 `docs/` 下的验收/流程文档。

产物入口：`Release/TrainStudio-WPF/LabelOnce.exe`。

可用 `-SkipBackend` 跳过后端打包（要求 `backend/backend.exe` 已存在）。

> 分发时复制整个 `Release/TrainStudio-WPF/`，保留 `backend/`、`models/`、`sam/` 与运行库；不要只复制 EXE。

---

## 4. PyInstaller 配置

### 4.1 `Backend.spec`（生产后端）

关键点：

- 入口：`backend_launch.py`；
- 隐藏导入：`ultralytics`、`openvino` 子模块，`tensorrt`、`onnxruntime`、`onnxslim`、`torchvision`、`torch.distributed.run`、`studio.bridge`、`studio.worker`；
- 数据/二进制：`collect_data_files('ultralytics')`、`collect_dynamic_libs('tensorrt_libs')`；
- 运行时钩子：`scripts/rth_torch.py`；
- 排除：pytest、notebook、IPython、PySide6、PyQt6、PyQt5、tkinter、tensorflow、jax；
- **强制使用 System32 的 VS2022 CRT**：从 `a.binaries` 移除 `msvcp140.dll`、`msvcp140_1.dll`、`vcruntime140.dll`、`vcruntime140_1.dll`，再显式加入 `C:\Windows\System32` 版本；
- `console=True`，因为 WPF 需要通过 stdin/stdout 管道通信（窗口由 `CREATE_NO_WINDOW` 隐藏）。

CRT 处理的原因：PyInstaller 可能优先收集 conda 环境根目录的旧 CRT（msvcp140 14.16 / vcruntime140_1 14.27），加载 torch 的 `c10.dll` 时会触发 `WinError 1114`（DLL 初始化例程失败）。这与 CI 中 Python 测试失败是同一类根因。

### 4.2 `YoloTrainStudio.spec`（Qt 版）

入口 `launch.py`，`console=False`，包含 Qt GUI 所需的 PyQt5；同样收集 ultralytics/openvino/tensorrt 运行时。产物为 `dist/YoloTrainStudio`。

### 4.3 `scripts/rth_torch.py`

运行时钩子用于修正 torch 的 DLL 搜索路径（尤其是 CUDA/cuDNN 依赖），确保冻结环境能找到随包分发的库。

---

## 5. GitHub Actions 流水线

工作流：`.github/workflows/ci.yml`，名称 `Label Once CI/CD`。

### 5.1 触发条件

- push 到 `main`；
- push 标签 `v*.*.*`；
- pull request 到 `main`；
- 手动 `workflow_dispatch`。

权限：`contents: read`。

### 5.2 作业

| 作业 | Runner | 条件 | 内容 |
| --- | --- | --- | --- |
| `python-tests` | `windows-latest` | 总是 | Python 3.10 + 轻量测试依赖 + `pytest -q` |
| `dotnet-build` | `windows-latest` | 总是 | `dotnet restore/build LabelOnce.sln -c Release` |
| `package-windows` | `windows-latest` | tag 或手动 | 发布 self-contained WPF，压缩并上传 artifact |

`package-windows` 依赖前两个作业；PR 只跑测试与构建，不打正式包。

### 5.3 Python 测试环境

```yaml
- name: Install test dependencies
  run: |
    python -m pip install --upgrade pip
    python -m pip install pytest PyQt5 numpy opencv-python Pillow PyYAML

- name: Run Python tests
  env:
    QT_QPA_PLATFORM: offscreen
  run: python -m pytest -q
```

**不再安装 ultralytics/torch**。原因见下一节。

---

## 6. 本次 CI 修复：torch DLL 初始化失败

### 6.1 现象

`Label Once CI/CD / Python tests (push)` 持续失败，摘要：

```text
2 failed, 86 passed, 1 skipped
FAILED tests/test_training_pipeline.py::test_training_parameters_reach_model_train
FAILED tests/test_training_pipeline.py::test_resume_uses_the_checkpoint_and_keeps_the_original_dataset
OSError: [WinError 1114] A dynamic link library (DLL) initialization routine failed.
Error loading "...\site-packages\torch\lib\c10.dll" or one of its dependencies.
```

失败发生在 `import ultralytics` 时，由 ultralytics 间接导入 torch，torch 在 Windows runner 上加载 `c10.dll` 失败。

### 6.2 根因

- 测试本身不需要真实模型：它们用 `FakeYOLO` 替身记录 `train()` 参数；
- 但测试使用了 `import ultralytics` + `monkeypatch.setattr`，强制加载真实包；
- CI 安装 `ultralytics==8.4.161` 会拉取 torch（当时解析到 2.14.1），其 `c10.dll` 在当前 Windows 环境初始化失败；
- 因此失败与业务逻辑无关，而是“测试不必要地依赖重型 ML 运行时”。

### 6.3 修复

1. `tests/test_training_pipeline.py` 改为通过 `sys.modules` 注入假模块：

```python
def install_fake_ultralytics(monkeypatch):
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=FakeYOLO))
    FakeYOLO.captured = None
```

这样 `Worker.train()` 里的 `from ultralytics import YOLO` 会拿到替身，不会触发 torch 导入。

2. CI 安装步骤移除 `ultralytics==8.4.161`，只安装测试真正需要的轻量依赖。

3. 保留 `Backend.spec` 中的 System32 CRT 强制收集逻辑，解决**成品后端**在用户机器上同样可能遇到的 torch DLL 问题。

### 6.4 验证

在 Python 3.10 环境、**卸载 ultralytics/torch 后**执行：

```text
88 passed, 1 skipped
```

CI 的 Python 测试作业不再依赖 GPU、模型权重或 torch，运行时间也显著缩短。

### 6.5 注意

- 本地开发若需要真实训练/推理，仍按 `scripts/install.ps1` 安装完整依赖；
- 不要为了“让测试导入真实库”而重新把 ultralytics 加回 CI；
- 若未来测试确实需要真实模型，应单独建一个带缓存的 GPU/ML 作业，而不是拖慢主测试作业。

---

## 7. 发布产物检查清单

- [ ] `LabelOnce.exe` 能启动，`backend/backend.exe` 存在；
- [ ] `models/`、`sam/` 含所需权重；
- [ ] `LabelOnce.exe` 目录包含全部运行库（self-contained）；
- [ ] `docs/` 随包分发（Qt 版构建会复制）；
- [ ] 版本号/标签与 `requirements.lock.txt` 一致；
- [ ] 在干净 Windows 机器上做一次启动 + 打开项目 + 保存标注的冒烟测试；
- [ ] TensorRT engine 在目标机器重新导出（如使用）。

---

## 8. 相关文档

- [快速开始](./01-getting-started.md)
- [测试与验收](./12-testing.md)
- [WPF 成品验收](./WPF_ACCEPTANCE.md)
- [故障排查](./13-troubleshooting.md)