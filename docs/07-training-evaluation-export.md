# 训练、评估与导出

本文说明训练参数从 UI 到 Ultralytics 的传递路径、续训约束、评估/推理任务，以及模型导出格式。

实现位置：`studio/worker.py`、`studio/config.py`、`studio/service.py`。

---

## 1. 训练参数

### 1.1 默认超参

`studio/config.py` 中的 `ADVANCED`：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `optimizer` | `AdamW` | **固定**，不使用 `auto` |
| `momentum` | `0.9` | AdamW 的 beta1 约定 |
| `weight_decay` | `0.0005` | |
| `warmup_epochs` | `3.0` | |
| `warmup_momentum` | `0.8` | |
| `lrf` | `0.01` | |
| `box` / `cls` / `dfl` | `7.5 / 0.5 / 1.5` | 损失权重 |
| `freeze` | `0` | |
| `max_det` | `300` | |
| `workers` | `0` | Windows 下避免 DataLoader 子进程问题 |
| `patience` | `100` | |
| `amp` | `True` | |
| `seed` | `42` | |
| `nbs` | `64` | 名义 batch size，影响梯度累积与迭代估算 |

`AUGMENTS` 默认：

```python
fliplr=.5, scale=.5, mosaic=1., hsv_h=.015, hsv_s=.7, hsv_v=.4,
flipud=0., degrees=0., mixup=0., translate=.1
```

### 1.2 为什么固定 AdamW？

Ultralytics 的 `optimizer='auto'` 在迭代数超过阈值后会静默切换优化器，并忽略用户设置的学习率/动量，导致：

- UI 中的学习率变成“无效字段”；
- 同一组超参在不同规模数据集上行为不同；
- 实验不可复现。

因此本项目显式固定 `AdamW`，并把 `momentum` 调整为 AdamW 的 `beta1` 语义。

### 1.3 预设优先级

`preset.get` 的合并顺序（后者覆盖前者）：

1. `ADVANCED` + `AUGMENTS` + 基础字段（epochs/batch/lr0/imgsz/device）；
2. `Model/advanced_train_params.json` 的 `params`；
3. `Config/train_preset.json`（旧）或 `Config/train.json` 的 `advanced.params`；
4. 旧预设的 `epochs/batch/lr0/imgsz/device`；
5. 旧字段 `lr` → `lr0`；
6. 旧增强开关 → `augmentation_values()`；
7. `Config/wpf_train_preset.json`（当前 WPF 预设，最高优先级）。

`augmentation_values()` 处理历史遗留的单个 `hsv` 开关，把它展开为 `hsv_h/hsv_s/hsv_v`，避免预设往返时颜色增强被丢弃。

### 1.4 WPF 参数组装

`StudioViewModel.TrainParams()`：

- 以 `advanced` 字典为底；
- 合并 `augments`；
- 覆盖 `epochs`、`batch`、`lr0`、`imgsz`、`device`。

训练前会校验 `imgsz % 32 == 0`。

---

## 2. 训练任务

### 2.1 创建

`task.start(kind='train')` 会：

1. 创建运行目录 `runs/train_<时间戳>_<随机串>/`（续训除外）；
2. 解析数据集版本，写入 `task.dataset` 与 `task.dataset_version`；
3. 写入 `task.json`，由 `ProcessManager` 拉起 worker。

### 2.2 执行

`Worker.train()`：

- 新建训练：`YOLO(model)`，参数包含 `data`、`project=<run>`、`name='train'`、`exist_ok=False`、`plots=True`；
- 续训：`YOLO(last.pt)`，只覆盖 `data` 与 `resume=True`，**不传 `project`**，沿用检查点中的输出目录；
- 注册 `on_fit_epoch_end` 回调：发送 epoch 指标与进度；
- 注册 `on_train_batch_end` 回调：检查取消文件，设置 `trainer.stop=True`；
- 训练完成后把 `best.pt` 复制为 `Model/<run>.pt`；
- 把参数、指标、数据集版本、耗时、状态追加到 `Model/experiments.jsonl`。

取消语义：

- 用户取消后，训练回调设置停止；
- 已产生的输出与实验记录保留；
- worker 抛出 `InterruptedError`，桥接层收到 `cancelled` 事件，不会伪装成成功。

### 2.3 续训

入口：WPF 训练页“续训”，或 `task.start` 传 `resume`。

`_resume_training()`：

- 接受运行目录或 `last.pt` 路径；
- 运行目录会递归查找 `weights/last.pt`，取最后一个；
- 必须是当前项目 `runs/` 下的运行；
- 继承原运行的 `dataset_version`（若请求未显式提供）；
- 把 `task.run` 重定向到原运行目录，保证产物、实验记录、曲线都在原地续写。

**不允许**跨项目续训；**不允许**用 `best.pt` 续训。

### 2.4 训练记录

`experiments.jsonl` 每行一条 JSON，主要字段：

```json
{
  "schema_version": 1,
  "experiment_id": "train_20261026_...",
  "timestamp": "2026-10-26T12:00:00",
  "params": {"epochs": 50, "batch": 16, "lr0": 0.001, "...": "..."},
  "metrics": {"metrics/mAP50(B)": 0.82},
  "dataset": ".../dataset.yaml",
  "dataset_version": "20261026_...",
  "output": ".../runs/train_.../train",
  "best": ".../Model/train_....pt",
  "duration": 1234.5,
  "status": "completed"
}
```

WPF 的训练曲线从 epoch 事件与实验记录读取；发布门禁会引用 `dataset_version` 判断报告是否过期。

---

## 3. 评估（evaluate）

`Worker.evaluate()`：

- `YOLO(model).val(data=dataset.yaml, split='test', conf=..., iou=..., device=..., plots=True, save_txt=True, save_conf=True)`；
- 输出目录为 `<run>/evaluation`；
- 返回整体指标、逐类 precision/recall/mAP50/mAP 与结果目录。

注意：

- 评估固定使用 `test` split；如果没有 test 样本，Ultralytics 可能回退/报错，建议划分时保留 test 或改用发布门禁的基准集；
- 评估与训练一样会绑定数据集版本；
- 评估结果不会自动写入发布门禁报告。

---

## 4. 推理（predict）

`Worker.predict()` 支持三种模式：

| mode | 输入 | 输出 |
| --- | --- | --- |
| `image` | 单张图片 | 绘制结果图 + `detections.json/csv` |
| `batch` | 目录（递归） | 每张结果图 + 汇总检测表 |
| `video` | 视频文件 | MP4 可视化结果 + 检测表 |

流程：

1. 加载 `YOLO(model)`，读取 `model.names` 建立标签类别表；
2. 逐图 `predict(conf, iou, device, verbose=False)`；
3. 检测框转换为归一化 `Box`，来源 `AI`；
4. 结果图写入运行目录；批量模式用 `cv2.imdecode/imencode` 支持中文路径；
5. 汇总 `detections.json` / `detections.csv`（UTF-8 BOM）；
6. 单图失败会记录到 `errors[]`，不会中断整批；视频无法打开或编码器不可用会直接失败；
7. 支持取消检查。

---

## 5. 模型导出（export）

### 5.1 支持格式

| UI 值 | Ultralytics format | 额外依赖 | 说明 |
| --- | --- | --- | --- |
| `onnx` | `onnx` | `onnx`、`onnxruntime`、`onnxslim` | 强制 CPU，适合跨平台 |
| `openvino` | `openvino` | `openvino` | Intel CPU/GPU |
| `engine` | `engine` | `tensorrt` | 与 GPU/驱动/TensorRT 绑定 |
| `torchscript` | `torchscript` | `torch` | TorchScript |

缺少依赖时会提示运行 `scripts/install.ps1 -Exports`（脚本按需安装导出组件）。

### 5.2 参数

WPF 默认导出参数：

```json
{"imgsz": 640, "opset": 18, "dynamic": false, "simplify": true, "batch": 1}
```

UI 还会传：

- `quantize`：32 / 16 / 8；
- `device`：ONNX 强制 `cpu`；TensorRT 或 FP16 使用 `0`；
- INT8 必须提供校准数据集（`data`），否则导出前直接报错；
- TensorRT FP32 会设置 `NVIDIA_TF32_OVERRIDE=0`。

### 5.3 隔离副作用

Ultralytics 会在输入模型旁边写导出文件。`Worker.export()` 会：

1. 把源权重复制到临时目录的 `model.pt`；
2. 在临时目录内导出；
3. 把结果复制回运行目录。

这样不会污染模型原目录，也不会因并发导出互相覆盖。

### 5.4 分发建议

- ONNX 最适合跨机器分发；
- TensorRT engine 必须在目标 GPU/驱动/TensorRT 版本上重新导出；
- 导出的模型应经过 [发布门禁](./08-release-gate.md) 的量化掉点检查（如提供量化模型）；
- 发布目录中保留 `.pt` 作为可再导出源。

---

## 6. 训练数据与模型的绑定

一次可复现实验至少需要：

- 项目类别表（顺序）；
- 数据集版本号与 `dataset.yaml`；
- 训练参数（`experiments.jsonl` 中的 `params`）；
- 模型权重（`Model/<run>.pt` 或运行目录 `weights/`）；
- 代码版本与 Ultralytics/Torch 版本。

发布门禁会把这些信息写入 `Model/release_gate.json`，包括模型 SHA256、大小、mtime、数据集版本、类别对齐结果、阈值与逐类指标。

---

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 学习率不生效 | 曾使用 `optimizer=auto` | 本项目已固定 AdamW；不要改回 auto |
| 续训报“只能续训当前项目” | 检查点不在当前项目 `runs/` | 复制回项目或重新训练 |
| 续训产物散落 | 续训不应传 `project` | 已由 `Worker.train` 保证 |
| 训练 OOM | batch/imgsz 过大 | 降低 batch、imgsz 或使用 AMP |
| 导出 INT8 失败 | 未提供校准数据 | 指定 `params.data` |
| engine 换机不可用 | TensorRT 与机器绑定 | 在目标机器重新导出 |
| 评估没有 test | 数据集比例为 0 或样本太少 | 调整比例/样本数 |

---

## 8. 相关文档

- [数据集版本与整合](./06-dataset-workflow.md)
- [发布门禁](./08-release-gate.md)
- [测试与验收](./12-testing.md)
- [故障排查](./13-troubleshooting.md)