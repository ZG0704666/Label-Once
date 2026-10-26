# Label Once 文档中心

Label Once（You Only Label Once）是一个面向 Windows 本地部署的 AI 视频跟踪标注与训练平台。它把图像/视频标注、SAM 辅助分割、数据集版本管理、训练评估、发布门禁和模型导出收拢在同一个本地工作区中。

本目录是项目的**文档中心**。根目录 [README.md](../README.md) 负责项目介绍和快速入口，这里负责把实现细节、操作流程、协议、构建与测试讲清楚。

> 文档基于仓库源码与 [DeepWiki](https://deepwiki.com/ZG0704666/Label-Once) 的仓库导读整理；涉及行为以当前源码为准。发现文档与代码不一致时，请优先相信代码，并提交文档修正。

---

## 我该从哪里开始？

| 你的目标 | 建议阅读顺序 |
| --- | --- |
| 第一次运行项目 | [快速开始](./01-getting-started.md) → [桌面端使用](./10-desktop-client.md) |
| 理解整体设计 | [架构总览](./02-architecture.md) → [桥接协议](./09-bridge-protocol.md) |
| 完成一次标注到训练 | [标注工作流](./04-annotation-workflow.md) → [数据集工作流](./06-dataset-workflow.md) → [训练、评估与导出](./07-training-evaluation-export.md) |
| 做视频跟踪 | [视频工作流](./05-video-workflow.md) → [渐进式工作流](./PROGRESSIVE_WORKFLOWS.md) |
| 合并多个数据集 | [数据集工作流](./06-dataset-workflow.md) → [多数据集整合规范](./DATASET_MERGE.md) |
| 发布模型前把关 | [发布门禁](./08-release-gate.md) |
| 改代码 / 修 CI | [构建、打包与 CI](./11-build-release-ci.md) → [测试与验收](./12-testing.md) |
| 遇到报错 | [故障排查](./13-troubleshooting.md) |

---

## 文档地图

### 入门与总体设计

- [01 · 快速开始](./01-getting-started.md)：环境要求、安装脚本、模型权重、源码/成品启动方式。
- [02 · 架构总览](./02-architecture.md)：WPF 桌面端、Python 后端、worker 子进程与文件通信。
- [03 · 项目目录与数据格式](./03-project-layout-and-formats.md)：项目目录、标注 sidecar、复核台账、数据集版本与全局配置。

### 核心工作流

- [04 · 图像标注与复核](./04-annotation-workflow.md)：导入、绘框、SAM 分割、轮廓编辑、保存与复核语义。
- [05 · 视频抽帧与 SAM2 跟踪](./05-video-workflow.md)：时间戳抽帧、暂停纠偏、质量门、关键帧回填与结果导入。
- [06 · 数据集版本与整合](./06-dataset-workflow.md)：复核门槛、分组划分、版本激活、多来源合并。
- [07 · 训练、评估与导出](./07-training-evaluation-export.md)：训练参数、续训、评估、推理、ONNX/OpenVINO/TensorRT 导出。
- [08 · 发布门禁](./08-release-gate.md)：类别顺序、基准集泄漏、mAP 下限、逐类跌幅与量化掉点。

### 接口与客户端

- [09 · JSONL 桥接协议与任务事件](./09-bridge-protocol.md)：请求/响应/事件格式、方法表、错误语义、stdout 卫生。
- [10 · WPF 桌面端](./10-desktop-client.md)：页面结构、快捷键、坐标变换、BridgeClient 与恢复策略。

### 工程与质量

- [11 · 构建、打包与 CI](./11-build-release-ci.md)：PyInstaller、WPF 发布、CI 作业与产物。
- [12 · 测试与验收](./12-testing.md)：Python 测试矩阵、.NET 测试、验收脚本与运行方式。
- [13 · 故障排查](./13-troubleshooting.md)：CI、torch DLL、后端连接、Qt、SAM2、导出等常见问题。
- [14 · 术语表](./14-glossary.md)：项目内高频概念与缩写。

### 专题与验收文档

- [从标注到训练：端到端流程](./ANNOTATION_TO_TRAINING.md)
- [多数据集整合规范](./DATASET_MERGE.md)
- [渐进式工作流与 GPU 验证](./PROGRESSIVE_WORKFLOWS.md)
- [WPF 成品验收](./WPF_ACCEPTANCE.md)
- [参与贡献](./contributing.md)

---

## 文档约定

- **路径**：除特别说明外，命令均在仓库根目录执行；Windows 路径使用反斜杠。
- **版本坐标**：Python 3.10 x64、.NET 10（`net10.0-windows`）、Ultralytics `8.4.161`、Torch `2.11.0+cu128`（见 `requirements.lock.txt`）。
- **数据单位**：标注在内存和 UI 中使用 `[0, 1]` 归一化坐标；`.annotation.json` 持久化为原图像素坐标；YOLO `.txt` 使用归一化中心点/宽高。
- **“保存”与“复核”**：保存只写入标注；复核（confirm）才把样本纳入数据集。两者不要混用。
- **不可变产物**：数据集版本、训练运行目录和发布门禁报告都按“新增而非覆盖”的方式管理，便于回溯。

---

## 维护文档

新增或修改功能时，请同步检查：

1. 受影响的文档页面是否需要更新；
2. 文档中的命令、路径、接口名是否仍与代码一致；
3. 新增接口是否已加入 [桥接协议方法表](./09-bridge-protocol.md)；
4. 新增测试是否已加入 [测试矩阵](./12-testing.md)；
5. 构建脚本引用的文档（`ANNOTATION_TO_TRAINING.md`、`DATASET_MERGE.md`、`PROGRESSIVE_WORKFLOWS.md`、`WPF_ACCEPTANCE.md`）是否仍然存在。