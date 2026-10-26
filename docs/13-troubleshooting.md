# 故障排查

本文按“现象 → 原因 → 处理”组织常见问题。若问题不在列表中，请先收集：

- 操作步骤与截图；
- 项目 `activity.log`；
- 任务目录 `runs/<run>/process.log`、`events.jsonl`、`task.json`；
- `%APPDATA%/YoloTrainStudio/settings.json`；
- Python/驱动/Ultralytics 版本；
- 后端 stderr 日志。

---

## 1. CI / 测试

### 1.1 `WinError 1114` 加载 `torch\lib\c10.dll` 失败

**现象**

```text
OSError: [WinError 1114] A dynamic link library (DLL) initialization routine failed.
Error loading "...\torch\lib\c10.dll" or one of its dependencies.
```

**原因**

- torch 在 Windows 上加载 `c10.dll` 时，其依赖的 CRT/DLL 初始化失败；
- 常见于 PyInstaller 收集了 conda 环境根目录的旧 CRT（`msvcp140` 14.16 / `vcruntime140_1` 14.27）；
- CI 中则是测试不必要地导入真实 ultralytics → torch。

**处理**

- 本仓库测试已改为注入假 `ultralytics`，CI 不再安装 torch；
- 成品后端由 `Backend.spec` 强制使用 `C:\Windows\System32` 的 VS2022 CRT；
- 本地完整环境：安装最新 [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)，或使用 `requirements.lock.txt` 中的 `torch==2.11.0+cu128`；
- 若仍失败，检查是否有多个 Python/conda 环境混用，清理 `torch` 后重装。

### 1.2 `ModuleNotFoundError: ultralytics`

- CI：不应再安装；若测试报此错，说明某个测试仍在 `import ultralytics`，应改为 `sys.modules` 注入；
- 本地：运行 `scripts/install.ps1` 或
  `pip install ultralytics==8.4.161`。

### 1.3 Qt 测试报平台插件错误

```text
could not load the Qt platform plugin "windows"
```

设置：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
```

CI 已在作业级别设置该变量。

### 1.4 测试通过但 CI 仍红

- 确认 workflow 使用的是最新提交；
- 检查是否有 `pytest` 缓存的旧 `.pyc`（清理 `.pytest_cache`、`__pycache__`）；
- 查看失败步骤的完整日志，而不是只看摘要；
- 注意 CI 与本地 Python 位数/版本差异（必须 3.10 x64）。

---

## 2. 后端连接

### 2.1 “未找到 backend/backend.exe”

**原因**：WPF 在成品模式下找不到后端，且向上没有找到 `backend_launch.py`。

**处理**：

- 确认发布目录包含 `backend/backend.exe`；
- 或设置 `LABELONCE_BACKEND` 指向后端；
- 源码模式设置 `LABELONCE_SOURCE` 指向仓库根目录；
- 设置 `LABELONCE_PYTHON` 指向 Python 3.10 解释器。

### 2.2 “业务后端已退出”

- 打开“设置 → 诊断与恢复 → 重启后端”；
- 查看后端 stderr / 任务 `process.log`；
- 若因崩溃退出，检查是否 OOM、CUDA 驱动崩溃、模型文件损坏；
- 未保存编辑仍保留在 UI，重启后重新保存。

### 2.3 请求超时（30 分钟）

- 后端可能仍在执行长任务；
- 查看任务目录 `events.jsonl` 是否仍在增长；
- 不要重复提交同一任务；先 `task.status` 或停止任务；
- 若是桥接进程卡死，强制重启后端。

### 2.4 协议解析错误

- 第三方库把日志写进 stdout；
- 本项目会重绑 logger 并容错脏行；
- 若仍出现，检查是否有自定义 `print`/`StreamHandler(sys.stdout)`；
- 临时可在日志中搜索“忽略无法解析的后端输出”。

---

## 3. 项目与标注

### 3.1 “同名不同扩展名图片会共用标签”

同一 stem 的 `foo.jpg` 与 `foo.png` 会共用 `foo.txt`。处理：

- 重命名/移除其中一张；
- 导入时使用唯一文件名；
- 不要在 `Main/` 中手动放入同名不同扩展名文件。

### 3.2 标注冲突 `AnnotationConflict`

**原因**：`.txt/.mark/.segments.json` 被外部修改，或 revision 已变化。

**处理**：

- 不要直接编辑 sidecar；
- 重新打开图片，确认最新内容；
- 若外部工具必须修改，先备份并删除 `.annotation.json` 让其从旧格式重建（会丢失 revision/对象 ID）；
- 冲突未解决前不要强制覆盖。

### 3.3 保存后复核状态变回 pending

- 几何/标签/图片内容变化会撤销确认，这是设计行为；
- 原样保存不会撤销；
- 重新按 `F` 确认即可。

### 3.4 空图片没有进入数据集

- 空图片必须保存**空 `.txt`** 并确认；
- 只有 `.annotation.json` 而没有 `.txt` 投影时，数据集会跳过；
- 检查 `Main_labels/<stem>.txt` 是否存在（可以是 0 字节）。

### 3.5 类别重排后标注错位

- 使用“管理类别”的显式映射，不要直接改 `classes.txt`；
- 操作前会备份 `labels_backup_<时间戳>/`；
- 若已错位，恢复备份后重新映射。

---

## 4. 数据集与训练

### 4.1 “没有已审核的图片标签”

- 所有样本仍为 pending；
- 或缺 `.txt`；
- 或全部被 rejected。

逐张确认，空图片也要保存空标签并确认。

### 4.2 “增量更新必须保持类别及比例”

- 增量更新不允许改类别表或比例；
- 需要改类别/比例时使用“重新平衡”/新建版本。

### 4.3 “旧样本丢失或变化”

- 旧版本中的图片或标签被修改/删除；
- 恢复文件，或改用重新平衡创建新版本；
- 数据集版本不可变，旧版本仍可读取。

### 4.4 验证集指标异常高

- 同组样本跨 split 导致泄漏；
- 检查 `dataset_manifest.json` 的 `leaked_groups`；
- 使用整合的“统一重划”或确保导入批次/视频分组正确。

### 4.5 训练 OOM

- 降低 `batch`、`imgsz`；
- 关闭 `amp=False`（默认开启 AMP）；
- 减少 `workers`（默认 0）；
- 关闭其他占用显存的程序；
- 用更小的模型。

### 4.6 续训失败

- 只能续训当前项目 `runs/` 下的 `last.pt`；
- 不能用 `best.pt`；
- 检查 `last.pt` 是否存在、是否被移动；
- 续训不传 `project`，产物必须留在原运行目录。

### 4.7 训练取消后没有“完成”

- 取消是协作式的，worker 会抛 `InterruptedError`，桥接层发 `cancelled`；
- 输出与实验记录保留；
- 若进程无响应，使用“强制停止”（杀进程树）。

---

## 5. 视频与 SAM

### 5.1 SAM2 版本不匹配

```text
SAM2 跟踪需要固定的 ultralytics==8.4.161
```

安装锁定版本：

```powershell
python -m pip install ultralytics==8.4.161
```

不要随意升级，内部依赖该版本的 `SAM2VideoPredictor` 结构。

### 5.2 视频时间戳不可靠

- VFR/损坏视频的时间戳可能回退或为 NaN；
- 本项目会拒绝抽帧，避免错帧；
- 用 ffmpeg 重新封装为恒定帧率，或换源。

### 5.3 抽帧无法恢复

- 视频内容变化（SHA256 不同）；
- 抽帧计划（frame_step/interval）不同；
- 清理旧运行目录后重新抽帧。

### 5.4 跟踪自动暂停

- 触发了质量门（面积突变/位置突变/目标过大/丢失）；
- 这是保护机制，不是崩溃；
- 在暂停帧修正目标后“继续”，或结束该目标；
- 可调整 `quality` 阈值，但不建议放宽到无法发现问题。

### 5.5 回填冲突

- 目标图片已复核、被人工修改，或版本指纹变化；
- 查看 `backfill_conflicts.json` 的候选；
- UI 可逐个确认候选，或跳过；
- 回填永远不会覆盖已复核的人工几何。

### 5.6 GPU 显存不足

- 跟踪暂停后确认 `gpu_released=true`，再跑 SAM 单图；
- 降低 `imgsz`（必须是 32 的倍数）；
- 关闭其他 GPU 程序；
- 重启后端释放残留显存。

---

## 6. 导出与发布

### 6.1 缺少导出依赖

```text
缺少 onnx，请运行 scripts/install.ps1 -Exports
```

按提示安装对应组件；ONNX 需要 `onnx/onnxruntime/onnxslim`，OpenVINO 需要 `openvino`，TensorRT 需要 `tensorrt`。

### 6.2 INT8 导出失败

- 必须提供校准数据集 `params.data`；
- 数据集 YAML 必须可读；
- 校准样本不足会导致量化失败或掉点过大。

### 6.3 TensorRT engine 换机不可用

- engine 与 GPU 架构、驱动、TensorRT 版本绑定；
- 在目标机器用 `.pt`/ONNX 重新导出；
- 交付时保留 `.pt` 源权重。

### 6.4 发布门禁失败

见 [发布门禁](./08-release-gate.md) 的失败排查表，常见原因：

- 类别顺序不一致；
- 基准集与训练集重叠；
- mAP50 低于下限；
- 某类 AP50 跌幅过大；
- 量化掉点过大；
- 基准集标签格式混用。

### 6.5 报告显示“已过期”

- 数据集激活版本变化；
- 模型文件大小/mtime 变化；
- 重新跑门禁即可。

---

## 7. 构建与打包

### 7.1 `dotnet` 找不到 SDK

- `desktop/global.json` 需要 10.0.x；
- 使用 `.tools/dotnet/dotnet.exe` 或安装 .NET 10 SDK；
- 检查 `dotnet --list-sdks`。

### 7.2 `RestoreLockedMode` 失败

- `packages.lock.json` 与项目引用不一致；
- 运行 `dotnet restore --force-evaluate` 更新锁文件，或在允许时去掉 `RestoreLockedMode`。

### 7.3 打包后后端启动失败

- 检查 `backend/backend.exe` 是否存在；
- 检查 CRT 是否来自 System32（`Backend.spec`）；
- 在干净机器上复现，查看 stderr；
- 确认 `models/`、`sam/` 随包分发。

### 7.4 只复制 EXE 无法运行

- WPF 是 self-contained，但依赖同目录运行库；
- 后端、模型、配置都在相邻目录；
- 分发整个 `Release/TrainStudio-WPF/`。

---

## 8. 环境与编码

### 8.1 中文路径/乱码

- 项目内部统一 UTF-8；
- 后端启动设置 `PYTHONUTF8=1`，worker 使用 `-X utf8`；
- 批处理/PowerShell 脚本保存为 UTF-8；
- 避免使用未安装的语言包路径。

### 8.2 配置损坏

删除或重命名：

```text
%APPDATA%/YoloTrainStudio/settings.json
%APPDATA%/YoloTrainStudio/wpf.json
```

重启后会生成默认配置。项目内配置损坏时，先备份整个项目再处理。

### 8.3 杀毒软件拦截

- 训练/导出会创建大量临时文件；
- 将项目目录、`%TEMP%`、发布目录加入排除项；
- 避免在同步盘（OneDrive 等）中训练。

---

## 9. 收集诊断信息

提交 Issue 时附上：

```powershell
python --version
python -m pip show ultralytics torch PyQt5
dotnet --info
nvidia-smi
```

以及：

- 复现步骤；
- 完整错误栈；
- 任务目录 `task.json`、`process.log`、`events.jsonl`（注意脱敏路径）；
- 项目 `activity.log`；
- 相关截图/录屏。

---

## 10. 相关文档

- [快速开始](./01-getting-started.md)
- [构建、打包与 CI](./11-build-release-ci.md)
- [测试与验收](./12-testing.md)
- [WPF 桌面端](./10-desktop-client.md)