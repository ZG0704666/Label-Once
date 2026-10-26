# WPF 桌面端

WPF 桌面端是当前主界面，位于 `desktop/`。它负责画布交互、页面导航、快捷键和调用 Python 后端；重任务全部交给后端执行。

技术栈：

- .NET 10（`net10.0-windows`）
- WPF-UI 4.3.0
- CommunityToolkit.Mvvm 8.4.2
- `LabelOnce.Core`：纯 .NET 几何/历史核心，可独立测试

---

## 1. 项目结构

```text
desktop/
├── LabelOnce.sln
├── global.json                 # SDK 10.0.403
├── Directory.Build.props
├── LabelOnce.Core/
│   ├── Annotation.cs           # Annotation、AnnotationHistory
│   └── Viewport.cs             # 原始像素/EXIF/视口坐标变换
├── LabelOnce.Desktop/
│   ├── App.xaml / App.xaml.cs
│   ├── MainWindow.xaml(.cs)
│   ├── ViewModels/StudioViewModel.cs
│   ├── Controls/AnnotationCanvas.cs
│   ├── Controls/TrainingCurve.cs
│   ├── Services/BridgeClient.cs
│   ├── Services/DatasetMergeDialog.cs
│   ├── Services/UserDialogs.cs
│   └── Styles.xaml
├── LabelOnce.Core.Tests/       # 控制台几何断言
└── LabelOnce.Desktop.Tests/    # 真实窗口验收程序
```

---

## 2. 页面与导航

左栏页面：

| 页面 | 作用 |
| --- | --- |
| 首页 | 最近项目、新建/打开、导入、视频入口 |
| 素材库 | 图片列表、筛选、批次、复核状态 |
| 标注 | 画布、类别、SAM、轮廓、复核 |
| 视频 | 打开视频、抽帧、跟踪、暂停纠偏 |
| 训练 | 数据集版本、参数、预设、训练/续训、整合 |
| 模型 | 评估、推理、导出、发布门禁 |
| 设置 | 品牌/Logo、SAM 尺寸、材质、后端诊断与恢复 |

右栏可调宽；窗口宽度小于 1000 DIP 时自动折叠。“侧栏”可手动打开，“专注”扩大画布。

---

## 3. 快捷键

| 快捷键 | 行为 |
| --- | --- |
| `W` | 绘框 |
| `Esc` | 选择模式 |
| `R` | 适配视图 |
| 滚轮 | 以鼠标为中心缩放 |
| 中键拖动 / 空格拖动 | 平移 |
| `Delete` | 删除选中框/顶点 |
| `Ctrl+C` / `Ctrl+V` | 复制/粘贴 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销/重做 |
| 方向键 | 微调 |
| `A` / `D`（按住） | 连续上一张/下一张，松开停止 |
| `F` | 保存 + 确认 + 下一张 |
| `P` | 多边形绘制，双击完成 |
| 双击轮廓边 | 插入顶点 |
| `Q` | 添加 SAM 前景点 |
| `E` | 添加 SAM 背景点 |

`F` 只在画布获得焦点时生效，避免在输入框中误触；长按不会重复确认。

---

## 4. 坐标系统

`LabelOnce.Core.Viewport` 负责三层坐标：

```text
原始像素 (raw) --EXIF Orient--> 显示像素 (display) --Scale/Offset--> 视口 DIP (screen)
```

- `Orient/Unorient` 支持 EXIF 方向 1–8；
- `ToScreen/ToRaw/ToNormalized` 在层间转换；
- 标注始终以**原始像素/归一化坐标**保存，不随视图缩放/旋转改变；
- `Load(..., video: true)` 在同一视频切换帧时保留视角，换图/换尺寸/换方向时重新 fit；
- `Resize()` 只在 fit 模式下重新适配，手动缩放/平移不会被窗口变化重置。

`AnnotationHistory`：

- 保存最近 100 个状态；
- 新编辑会清空 redo；
- `Step(-1/+1)` 返回深拷贝，避免编辑污染历史。

---

## 5. 保存与切图

- 只有保存成功后才切换图片；
- 保存失败时编辑保留，可重试；
- 后端 revision 冲突时提示用户重新打开/解决冲突，不覆盖；
- `AnnotationChanged()` 会标记 dirty 并同步对象列表；
- `Save(confirm: true)` 用于 `F` 键，先保存再确认；
- 切图前会 flush 视频草稿（视频模式）。

---

## 6. 后端连接（BridgeClient）

启动顺序：

1. 若 `LABELONCE_BACKEND` 指向的文件存在 → 直接启动它，参数 `--bridge`；
2. 否则查找发布目录 `backend/backend.exe`；
3. 否则从 `AppContext.BaseDirectory` 向上查找 `backend_launch.py`，进入源码模式：
   - Python 解释器：`LABELONCE_PYTHON` 或 `~/anaconda3/envs/labelonce/python.exe`；
   - 参数：`-X utf8 -m studio.bridge`；
4. 设置 `PYTHONUTF8=1`、`YOLO_AUTOINSTALL=False`；
5. 重定向 stdin/stdout/stderr，隐藏窗口。

请求/响应/事件格式见 [桥接协议](./09-bridge-protocol.md)。

健壮性：

- 脏 stdout 行降级为日志；
- 版本不是 1 的帧忽略；
- 后端退出时所有 pending 请求失败，并提示“设置 → 诊断与恢复 → 重启后端”；
- 重启后端会重新 `project.open`，未保存编辑仍保留在 UI。

---

## 7. 类别管理

“管理类别”流程：

1. 先编辑名称列表；
2. 再显式指定旧类别 → 新类别编号映射；
3. `-1` 表示移除该旧类别的所有标注；
4. `classes.save` 会先完整校验，再备份 `Main_labels` 到 `labels_backup_<时间戳>/`，然后重排标签与写入新类别表。

这样即使映射错误，也能从备份恢复。

---

## 8. 训练与模型页

训练页：

- 选择数据集版本；
- 配置 epochs/batch/lr/imgsz/device；
- “高级设置”编辑 `ADVANCED` 参数；
- “数据增强”编辑 `AUGMENTS`；
- 预设保存/加载/恢复默认；
- 开始训练、续训、停止；
- 数据集整合（多来源）。

模型页：

- 评估、推理（图片/目录/视频）；
- 导出 ONNX/OpenVINO/TensorRT/TorchScript；
- 发布门禁；
- 打开运行目录。

训练曲线由 `TrainingCurve` 控件绘制，数据来自 epoch 事件与 `experiments.jsonl`。

---

## 9. 主题与可用性

- 默认深色 Acrylic；
- Windows 11 透明效果关闭、高对比度或系统不支持时回退不透明深色；
- 图片画布始终不透明，避免颜色判断受背景影响；
- 侧栏、右栏可调宽；
- 所有破坏性操作（删除、覆盖、强制停止）都有确认对话框。

---

## 10. 旧 Qt 界面

`studio/app.py` 是保留的 PyQt5 界面，与 WPF 共享 `StudioService`/`ProcessManager` 协议。启动：

```powershell
python launch.py
```

Qt 版适合无 .NET 环境或快速调试后端；功能入口以 WPF 为准。

---

## 11. 构建与测试

```powershell
./desktop/scripts/start.ps1    # 编译并启动
./desktop/scripts/test.ps1     # Python + Core 几何测试
```

真实窗口验收：

```powershell
./desktop/scripts/test-desktop.ps1 `
  -Project "./acceptance/wpf/frozen/中文 空格成品项目" `
  -Fixtures "./acceptance/wpf/frozen/inputs"
```

它会移动鼠标、发送按键并修改指定测试项目，请使用专用验收项目，并在运行时暂停手动操作。

详见 [WPF 成品验收](./WPF_ACCEPTANCE.md) 和 [构建、打包与 CI](./11-build-release-ci.md)。

---

## 12. 相关文档

- [桥接协议](./09-bridge-protocol.md)
- [图像标注与复核](./04-annotation-workflow.md)
- [视频抽帧与 SAM2 跟踪](./05-video-workflow.md)
- [故障排查](./13-troubleshooting.md)