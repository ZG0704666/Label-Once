# Label Once · WPF

Windows x64 本地标注、训练与模型工作台。新界面使用 .NET 10 WPF、WPF UI 4.3.0 和 CommunityToolkit.Mvvm 8.4.2，Python 后端通过 UTF-8 JSONL 常驻连接。旧 Qt 入口保留。

## 运行成品

双击本目录的 `LabelOnce.exe`（源码交付中的位置为 `Release/TrainStudio-WPF/LabelOnce.exe`）。无需安装 Python、Conda 或 .NET。分发时复制整个文件夹，保留 `backend`、`models`、`sam` 和所有运行库。可以把项目目录作为命令行第一个参数。

打开旧项目即可使用；首次保存时增加带版本的 `.annotation.json` 原图像素标注文档，继续生成兼容检测 TXT、`.mark`、`.segments.json`。请连同图片和全部 sidecar 一起备份。应用设置继续位于 `%APPDATA%/YoloTrainStudio`，WPF 材质偏好单独存于 `wpf.json`。

## 使用

- 左栏切换素材、标注、视频、训练、模型和设置。标注页的“项目”菜单提供打开、导入、数据集导出与停止任务；“高级设置”进入可滚动的模型设置页。
- 图片切换完整居中；同视频切帧保留视角。`R` 恢复适配，滚轮在鼠标处缩放，中键或空格拖动平移。
- `W` 绘框，`Esc` 选择，八个控制点调整大小；Delete、Ctrl+C/V、Ctrl+Z/Y；方向键微调。A/D 按住切换，松开停止；F 单次确认并进入下一张。
- 标注保存成功后才切图。保存失败时编辑保留，可重试；后台异常退出可在设置中重启后端。
- “管理类别”先编辑名称，再明确指定旧类别到新类别的编号映射；-1 移除旧类别标注，写入前备份原标签。
- 右栏可调宽，窗口小于 1000 DIP 自动折叠；“侧栏”手动打开，“专注”扩大画布。
- 默认深色 Acrylic；Windows 11 透明效果关闭、高对比度或系统不支持时使用不透明深色。图片画布始终不透明。
- 图片导入后进入新批次并选择手工、SAM 或 YOLO。Q 添加前景点、E 添加背景点，SAM 框和 ROI 是独立工具；“新目标”开始下一组提示，“清除本次分割”恢复本次开始前的轮廓。
- P 绘制多边形，双击完成；选择轮廓后拖动顶点，双击边插点，Delete 删除选中顶点（至少保留三个），Ctrl+Z/Y 撤销重做。
- 视频打开后配置抽帧，默认 0.5 秒；按真实时间戳顺序解码，完成后自动导入图片批次。在抽帧图片上标好目标后点击“从当前帧跟踪”，连续解码原视频，结果回填已有图片。暂停确认后允许修正，继续时提交多边形 mask；目标 ID 保持稳定。逐帧草稿与暂停关键帧持久化在项目内。
- 保存不等于复核；F 明确完成或确认无目标。修改几何会撤销完成状态。分割导出只包含已复核图片，检测框缺少轮廓会阻止导出；孔洞填充、多区域拆分必须明确选择。检测数据集和模型导出入口保持独立。

## 开发与构建

在 `Source/Label Once` 下执行：

```powershell
./desktop/scripts/setup.ps1
./desktop/scripts/start.ps1
./desktop/scripts/test.ps1
./desktop/scripts/build.ps1
```

开发环境名 `labelonce`，Python 3.10 x64，Torch 2.11.0+cu128 / torchvision 0.26.0。项目专用 SDK 在根目录 `.tools/dotnet`，`global.json` 锁定 10.0.401，NuGet 使用 `packages.lock.json`。脚本不修改系统 PATH。

输出 `Release/TrainStudio-WPF`。Python 后端用 PyInstaller 打包，WPF self-contained win-x64；WPF 用隐藏进程和重定向管道启动后端。Qt 回退成品 `Release/TrainStudio`，源码 `launch.py`。

## 验证与限制

`LabelOnce.Core.Tests` 是独立几何断言程序；`LabelOnce.Desktop.Tests` 启动真实 WPF 窗口；`scripts/check_progressive_gpu.py` 验证 SAM 多提示、ROI、视频抽帧、SAM2 mask 纠偏和回填。最新改动与证据见 `PROGRESSIVE_WORKFLOWS.md`（源码 `docs/PROGRESSIVE_WORKFLOWS.md`）。合成数据验收不代表模型准确率。

发布后端的完整隔离验证：

```powershell
python ./desktop/scripts/acceptance_frozen.py '../../Release/TrainStudio-WPF' ./acceptance/wpf/fixtures ./acceptance/wpf/frozen
./desktop/scripts/test-desktop.ps1 -Project './acceptance/wpf/frozen/中文 空格成品项目' -Fixtures ./acceptance/wpf/frozen/inputs
```

实窗脚本会移动鼠标、发送按键并修改指定测试项目，运行时请使用专用验收项目并暂时停止操作鼠标键盘。它通过发布版后端运行，子进程 PATH 仅包含 Windows 系统目录。

TensorRT engine 与 GPU、驱动和运行时绑定；跨机器分发模型时建议携带 `.pt` 或 ONNX，并在目标机器重新导出 engine。
