# WPF 成品验收

本文说明如何验证“打包后的 WPF + 冻结后端”在接近用户环境的条件下可用。它覆盖两类验收：

1. **真实窗口验收**：启动 WPF，模拟鼠标/键盘，检查交互；
2. **冻结后端验收**：只通过 `backend.exe` 的 JSONL 协议跑完整业务流程。

两者都在隔离环境（仅 System32 PATH、独立 APPDATA、临时工作目录）中运行，避免本机 Python/Conda 掩盖打包问题。

---

## 1. 前置条件

```powershell
./desktop/scripts/build.ps1
```

确认：

- `Release/TrainStudio-WPF/LabelOnce.exe` 存在；
- `Release/TrainStudio-WPF/backend/backend.exe` 存在；
- `Release/TrainStudio-WPF/models/`、`sam/` 有权重；
- 测试机有可用 GPU（跟踪/训练/SAM 需要）；
- 准备专用验收项目，**不要使用真实业务项目**。

验收输入通常放在：

```text
acceptance/wpf/frozen/
├── inputs/
│   ├── fixture_00.jpg
│   ├── fixture_04.jpg          # 带 EXIF Orientation=6
│   ├── landscape.mp4           # 320x180
│   └── portrait.mp4            # 180x320
└── 中文 空格成品项目/
```

---

## 2. 真实窗口验收

```powershell
./desktop/scripts/test-desktop.ps1 `
  -Project "./acceptance/wpf/frozen/中文 空格成品项目" `
  -Fixtures "./acceptance/wpf/frozen/inputs" `
  -Output "./acceptance/wpf/frozen/screenshots"
```

脚本行为：

1. 发布 `LabelOnce.Desktop.Tests` 到 `.tools/desktop-harness`；
2. 清理 `CONDA/PYTHON/DOTNET/LABELONCE` 环境变量；
3. 只保留 `System32` 的 PATH；
4. 设置 `LABELONCE_BACKEND` 指向发布版后端；
5. 设置独立 `APPDATA`；
6. 启动测试程序，传入输出目录、项目、fixtures；
7. 保存 `desktop-tests.log` 与截图；
8. 非零退出码即失败。

### 2.1 自动化场景

`LabelOnce.Desktop.Tests` 覆盖：

- 启动、等待后端连接、打开项目；
- 页面导航；
- 画布绘框、选择、移动、缩放；
- 快捷键：`W`、`Esc`、`F`、`A/D`、`Delete`、`Ctrl+Z/Y`、方向键；
- 多边形绘制/顶点插入；
- SAM 结果应用/丢弃；
- 过滤后的批次导航（搜索/问题筛选仍能上一张/下一张）；
- 视频页打开、逐帧、草稿、起始帧；
- 跟踪暂停/纠偏/提交；
- 截图与错误文件。

部分场景通过 `--review-navigation`、`--polygon-contract` 等参数运行，具体以 `desktop/LabelOnce.Desktop.Tests/Program.cs` 为准。

### 2.2 注意事项

- 测试会**移动真实鼠标、发送按键**；运行时不要操作鼠标键盘；
- 测试会修改指定项目，必须使用专用验收项目；
- 失败时查看 `desktop-tests.log`、`desktop-error.txt` 与截图；
- 若窗口被其他窗口遮挡，坐标点击可能失效，保持测试窗口置前。

---

## 3. 冻结后端验收

```powershell
python desktop/scripts/acceptance_frozen.py `
  "Release/TrainStudio-WPF" `
  "acceptance/wpf/frozen/inputs" `
  "acceptance/wpf/frozen/backend"
```

参数：发布目录、fixtures 目录、输出目录。

脚本会：

1. 构造干净环境（仅 System32 PATH，独立 APPDATA，临时 cwd）；
2. 启动 `backend/backend.exe --bridge`；
3. `hello` 校验模型路径都位于发布目录；
4. 打开 `中文 空格成品项目`；
5. 导入 fixtures；
6. 逐张 `annotation.save(confirm=True)`；
7. 加载 `fixture_04.jpg` 并断言 `orientation=6`；
8. 创建数据集；
9. 训练 1 epoch（`imgsz=64`，GPU）；
10. 推理、评估；
11. 导出 ONNX/OpenVINO/TorchScript/TensorRT；
12. SAM 分割（EXIF 图片）；
13. 横屏/竖屏视频打开、取帧、抽帧、导入；
14. 跟踪并**暂停/提交/恢复**；
15. 重新打开项目，断言图片仍在；
16. 写 `frozen-report.json`，`pass` 表示所有任务无 error。

支持 `--continue-after-exports` 断点续跑：复用已有 `frozen-report.json`，跳过已完成的训练/导出，只继续后续步骤。

输出：

```text
acceptance/wpf/frozen/backend/
├── frozen-report.json
├── backend-stderr.log
├── appdata/
├── inputs/
├── 中文 空格成品项目/
└── ...
```

### 3.1 断言重点

- 模型路径必须来自发布目录（防止误用本机模型）；
- 中文/空格项目路径可用；
- EXIF 方向正确；
- 训练/推理/评估/导出全链路可跑；
- 多格式导出文件存在；
- SAM、抽帧、视频导入、跟踪暂停/恢复可用；
- 重新打开项目后数据仍在。

---

## 4. 冻结后端渐进式验收

```powershell
python desktop/scripts/acceptance_frozen_progressive.py `
  "Release/TrainStudio-WPF" `
  "acceptance/wpf/frozen/inputs/fixture_04.jpg" `
  "acceptance/wpf/frozen/inputs/portrait.mp4" `
  "acceptance/wpf/frozen/progressive"
```

聚焦：

- 多提示 SAM + ROI；
- 抽帧/导入；
- SAM2 跟踪 + 暂停 + 纠偏；
- 回填与重放。

输出 `report.json`、`stderr.log`。适合在完整验收前快速定位打包环境问题。

---

## 5. TensorRT 探测

```powershell
python desktop/scripts/probe_frozen_engine.py `
  "Release/TrainStudio-WPF" `
  "acceptance/wpf/frozen/engine"
```

用于确认发布包内的 TensorRT 运行时能加载 engine，并输出设备/版本信息。若目标机器没有 TensorRT 或 GPU 架构不同，engine 需要重新导出。

---

## 6. 手工验收清单

自动化无法覆盖视觉/体验问题，发布前建议人工检查：

- [ ] 首次启动无报错，窗口尺寸/材质正常；
- [ ] 打开中文/空格路径项目；
- [ ] 导入图片/目录，重复导入提示合理；
- [ ] 绘框、移动、缩放、撤销/重做；
- [ ] EXIF 旋转图片显示与标注位置一致；
- [ ] SAM 正/负点、框、ROI、新目标、清除；
- [ ] 保存后切图，冲突提示可理解；
- [ ] `F` 确认后状态变为已复核；
- [ ] 空图片保存空标签并确认；
- [ ] 类别新增/重排有备份；
- [ ] 数据集创建、激活、增量更新；
- [ ] 训练进度/曲线/取消/续训；
- [ ] 评估、推理、导出；
- [ ] 发布门禁通过/失败提示清晰；
- [ ] 视频抽帧、跟踪、暂停、纠偏、回填；
- [ ] 关闭/重启后项目状态恢复；
- [ ] 高 DPI/小窗口布局不遮挡；
- [ ] 日志目录可定位。

---

## 7. 验收产物归档

建议把以下内容随发布记录保存：

```text
acceptance/wpf/frozen/
├── backend/frozen-report.json
├── backend/backend-stderr.log
├── progressive/report.json
├── screenshots/desktop-tests.log
├── screenshots/*.png
└── engine/probe.json
```

并记录：

- 发布版本/提交；
- Windows 版本、GPU/驱动、TensorRT 版本；
- 模型与数据集版本；
- 验收时间与执行人；
- 未通过项与豁免理由。

---

## 8. 常见失败

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 后端找不到模型 | `models/` 未复制 | 重新构建/复制 |
| `hello.models` 指向本机路径 | 环境变量泄漏 | 确认脚本清理 `LABELONCE_*` |
| 训练 OOM | 显存不足 | 降低 batch/imgsz，关闭其他程序 |
| TensorRT 导出失败 | 缺 TensorRT/驱动不匹配 | 安装依赖或在目标机重导 |
| 跟踪无法暂停 | 任务结束太快/控制时序 | 增大视频或调整暂停帧 |
| 窗口点击无效 | 窗口被遮挡/DPI 缩放 | 置前、使用 100% 缩放测试 |
| 中文路径失败 | 编码环境 | 确认 `PYTHONUTF8=1`、系统区域设置 |

---

## 9. 相关文档

- [WPF 桌面端](./10-desktop-client.md)
- [渐进式工作流与 GPU 验证](./PROGRESSIVE_WORKFLOWS.md)
- [构建、打包与 CI](./11-build-release-ci.md)
- [测试与验收](./12-testing.md)