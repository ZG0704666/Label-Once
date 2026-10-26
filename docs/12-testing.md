# 测试与验收

Label Once 的验证分为四层：

1. Python 单元/集成测试（`tests/`）；
2. .NET 几何测试（`LabelOnce.Core.Tests`）；
3. WPF 真实窗口验收（`LabelOnce.Desktop.Tests`）；
4. 人工/脚本验收（`scripts/check_*.py`、`desktop/scripts/acceptance_*.py`）。

---

## 1. Python 测试

### 1.1 运行

```powershell
python -m pip install pytest PyQt5 numpy opencv-python Pillow PyYAML
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

当前结果：**88 passed, 1 skipped**（不需要真实模型/GPU/torch）。

CI 使用同一套最小依赖，详见 [构建、打包与 CI](./11-build-release-ci.md)。

### 1.2 测试文件与覆盖范围

| 文件 | 覆盖内容 |
| --- | --- |
| `test_domain.py` | Labels/Project 往返、旧格式、类别重排、mask 边界、成对重命名、数据集确定性/增量、质量门 |
| `test_bridge.py` | JSONL 协议、UTF-8、错误帧、EXIF 保存/确认、失败不确认、过期项目、无 Qt 依赖、worker 错误/取消、单任务、强制停止、坏事件 |
| `test_gui.py` | Qt 窗口、标注、导航、视频页、SAM 结果过滤 |
| `test_workspace.py` | 工作区导入/映射/待复审、任务恢复/完成/失败 |
| `test_prelabel.py` | 零检测替换会清空旧标签 |
| `test_review_workflow.py` | 导入→复核→训练、非法导入、手动抽帧、画布目标/历史/只读、真实用户输出导入、旧预览 |
| `test_training_pipeline.py` | 分组划分、确定性、导入批次同组、增强参数、预设往返、AdamW 固定、训练参数传递、续训 |
| `test_segmentation_workflow.py` | 像素往返/复核/分割导出、投影修复/外部冲突、回填保护、未变保存、拓扑门禁、ROI、时间戳抽帧/取消、帧间隔预设、VFR |
| `test_video_pipeline.py` | 抽帧端到端、取消事件、stderr 日志、视频导入批次、重导入恢复、待复审报告、复核 schema v2 |
| `test_merge.py` | 新类确认、外部 ID 重映射、统一重划、比例约束、缺标签负样本、黑名单 yaml、stem 冲突、内容去重、golden 固定 val、大小写冲突、分割保留、跨项目只读、pending/rejected 排除、别名记忆、同名同内容去重 |
| `test_release_gate.py` | names 兼容、标签格式、类别对齐、基线前缀、泄漏、mAP 下限、缺基线 warning |
| `test_navigation_segments.py` | 轮廓持久化、按住的键释放/焦点、视频导航草稿/起始帧、F 只确认画布且不重复 |
| `test_interactive_workflow.py` | 追加类别保留 ID、暂停令牌/GPU 释放、finish_review 令牌、草稿隔离、轮廓简化、关键帧关联歧义 |
| `test_task_manager_compatibility.py` | Qt TaskManager 完成语义、取消标记、日志尾随 |

### 1.3 假模型注入

训练测试不加载真实 Ultralytics：

```python
class FakeYOLO:
    captured = None
    def __init__(self, path): ...
    def add_callback(self, event, callback): pass
    def train(self, **params):
        FakeYOLO.captured = params
        ...
```

通过 `monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=FakeYOLO))` 注入，因此：

- 不需要 torch；
- 不会触发 torch DLL 初始化问题；
- 仍能验证参数是否真正到达 `train()`。

`test_prelabel.py` 也使用同样的 `sys.modules` 注入方式。

### 1.4 常见失败

| 失败 | 原因 | 处理 |
| --- | --- | --- |
| `ModuleNotFoundError: PyQt5` | 缺测试依赖 | 安装 PyQt5 |
| `could not load the Qt platform plugin "windows"` | 无显示环境 | 设置 `QT_QPA_PLATFORM=offscreen` |
| `WinError 1114 ... c10.dll` | 测试仍在导入真实 ultralytics/torch | 确认测试使用假模块；更新到包含修复的版本 |
| 临时目录中文路径失败 | 系统编码/权限 | 使用 UTF-8、避免受控目录 |
| 测试残留进程 | 上次取消未清理 | 检查任务目录 `cancel`，必要时 `taskkill` |

---

## 2. .NET 几何测试

```powershell
dotnet run --project desktop/LabelOnce.Core.Tests -c Release
```

`LabelOnce.Core.Tests` 是一个控制台断言程序，覆盖：

- Viewport fit/zoom/pan/resize；
- EXIF 方向 1–8 的坐标往返；
- 图片/视频切换时的视角重置规则；
- Annotation 的 `SetBounds`、ROI 裁剪、多边形随框缩放；
- AnnotationHistory 的撤销/重做/100 步上限/新编辑清空 redo；
- 目标 ID 与多边形的历史一致性。

`desktop/scripts/test.ps1` 会先跑 Python 测试，再跑该几何测试。

---

## 3. WPF 真实窗口验收

`LabelOnce.Desktop.Tests` 会启动真实 WPF 窗口，模拟鼠标/键盘，验证：

- 页面切换与画布渲染；
- 打开项目、导入、绘框、保存；
- 快捷键（W/Esc/F/A/D/Delete/Ctrl+Z 等）；
- SAM 结果应用/丢弃；
- 视频暂停/纠偏/提交；
- 截图输出与错误捕获。

运行：

```powershell
./desktop/scripts/test-desktop.ps1 `
  -Project "./acceptance/wpf/frozen/中文 空格成品项目" `
  -Fixtures "./acceptance/wpf/frozen/inputs" `
  -Output "./acceptance/wpf/frozen/screenshots"
```

脚本会：

- 发布 `LabelOnce.Desktop.Tests` 到 `.tools/desktop-harness`；
- 只保留系统 `PATH`，隔离本机 Python/Conda；
- 设置 `LABELONCE_BACKEND` 指向发布版后端；
- 使用独立的 `APPDATA`；
- 保存 `desktop-tests.log` 与截图。

**注意**：它会移动真实鼠标、发送按键并修改指定项目。请使用专用验收项目，运行时不要操作鼠标键盘。

详见 [WPF 成品验收](./WPF_ACCEPTANCE.md)。

---

## 4. 脚本验收

| 脚本 | 用途 |
| --- | --- |
| `scripts/acceptance.py` | 后端端到端验收 |
| `scripts/check_workflow.py` | 标注/训练工作流冒烟 |
| `scripts/check_workspace.py` / `check_workspace_layout.py` | 工作区与布局 |
| `scripts/check_release_gate.py` | 发布门禁（也可作为验收） |
| `scripts/check_sam.py` | SAM 单图分割 |
| `scripts/check_interactive_pause.py` | 交互暂停/恢复 |
| `scripts/check_progressive_gpu.py` | SAM 多提示、ROI、抽帧、SAM2 纠偏/回填（GPU 验证） |
| `scripts/check_navigation_segments.py` | 导航与轮廓 |
| `scripts/check_f_shortcut.py` | F 快捷键 |
| `scripts/check_cancel.py` | 取消语义 |
| `scripts/check_layout.py` | UI 布局 |
| `scripts/check_frozen*.py` | 冻结后端/工作流/引擎探测 |
| `desktop/scripts/acceptance_backend.py` | 裸后端验收 |
| `desktop/scripts/acceptance_frozen.py` | 发布目录隔离验收 |
| `desktop/scripts/acceptance_frozen_progressive.py` | 发布目录渐进式验收 |
| `desktop/scripts/probe_frozen_engine.py` | TensorRT engine 探测 |

这些脚本通常需要真实模型/GPU/视频，属于“发布前人工验收”，不在 CI 默认路径中。

---

## 5. CI 与本地测试的差异

| 项目 | CI | 本地完整环境 |
| --- | --- | --- |
| Python | 3.10 | 3.10 |
| 测试依赖 | pytest/PyQt5/numpy/opencv/Pillow/PyYAML | 同左 + torch/ultralytics 等 |
| ultralytics | 不安装 | 安装（真实训练/导出需要） |
| GPU | 无 | 可选 |
| 模型权重 | 无 | 需要 |
| Qt | offscreen | 正常窗口 |
| .NET | 10.0.x | 10.0.x |

CI 只验证“代码逻辑与协议”，不验证“模型精度/GPU 性能”。模型质量必须通过 [发布门禁](./08-release-gate.md) 和人工验收。

---

## 6. 新增测试的建议

- **纯逻辑**放 `tests/`，尽量不导入重型库；
- 需要模型时优先用假对象/`sys.modules` 注入；
- 需要 GPU 的验收单独放脚本，不塞进 CI 主作业；
- 涉及文件格式的改动，至少覆盖：旧格式读取、往返保存、冲突/中断恢复；
- 涉及数据划分的改动，必须覆盖“同组不跨集合”和“确定性”；
- 涉及协议的改动，在 `test_bridge.py` 加请求/响应/错误帧断言；
- 新增文档时同步更新本文与 [文档中心](./README.md)。

---

## 7. 相关文档

- [构建、打包与 CI](./11-build-release-ci.md)
- [WPF 成品验收](./WPF_ACCEPTANCE.md)
- [渐进式工作流与 GPU 验证](./PROGRESSIVE_WORKFLOWS.md)
- [故障排查](./13-troubleshooting.md)