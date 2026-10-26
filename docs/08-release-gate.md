# 发布门禁

发布门禁（Release Gate）用于在模型交付前回答一个问题：**这个模型是否比上一版更差，或是否在“作弊”的数据划分上取得了虚高指标？**

实现：`scripts/check_release_gate.py`。UI 入口：WPF 模型页 → “发布门禁”；后端任务：`kind=gate`。

---

## 1. 输入

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `project` | ✅ | Label Once 项目目录 |
| `model` | ✅ | 待发布权重（`.pt`/`.onnx`/`.engine` 等 Ultralytics 可加载格式） |
| `golden` | ✅ | 冻结基准集的 `dataset.yaml` |
| `baseline` | ❌ | 上一版模型；用于逐类 AP50 对比 |
| `quantized` | ❌ | 量化模型（ONNX/INT8/engine），用于掉点检查 |
| `dataset_version` | ❌ | 取类别表的数据集版本；默认激活版本 |
| `map50_min` | ❌ | 整体 mAP50 下限，默认 `0.50` |
| `ap50_drop_max` | ❌ | 逐类 AP50 跌幅上限，默认 `0.03` |
| `quant_drop_max` | ❌ | 量化掉点上限，默认 `0.02` |
| `strict_labels` | ❌ | 基准集混用检测框/多边形时是否判失败 |
| `report_dir` | ❌ | 报告目录，默认 `<项目>/Model` |

CLI 示例：

```powershell
python scripts/check_release_gate.py `
  --project "D:\data\我的项目" `
  --model "D:\data\我的项目\Model\train_20261026.pt" `
  --golden "D:\data\golden\dataset.yaml" `
  --baseline "D:\data\我的项目\Model\train_20261020.pt" `
  --quantized "D:\data\我的项目\Model\model_int8.onnx" `
  --map50-min 0.5 `
  --ap50-drop-max 0.03 `
  --quant-drop-max 0.02
```

---

## 2. 五个检查阶段

### [1/5] 类别顺序核对

逐项比较训练用 `dataset.yaml` 与基准集的 `names` 列表：

- 必须完全一致（名称与顺序）；
- 不一致会导致“逐类 AP50”张冠李戴，门禁直接失败。

这是最常见、也最容易被忽视的失败原因：合并数据集时追加了新类别、或类别重命名后顺序变化。

### [2/5] 基准集标签格式

统计基准集 `labels/val` 中：

- 纯检测框行（5 个 token）；
- 多边形行（>5 个 token）。

如果混用：

- 默认记为 warning；
- `strict_labels=True` 时记为 failure。

原因：Ultralytics 评估时会丢弃多边形行或按检测处理，逐类指标会失真。

### [3/5] 泄漏检查

- 对基准集 val 图片与训练集 train 图片分别计算内容哈希；
- 若同一图片内容同时出现在两边，判失败；
- 并打印重叠文件名（最多 10 个）。

注意：这里比较的是**内容哈希**，不是文件名。改名不能绕过。

### [4/5] 评估模型并比较逐类 AP50

1. 校验模型类别表与基准集一致；
2. 用临时 staging 目录评估新模型；
3. 若提供 baseline：
   - 校验 baseline 类别表是 golden 的前缀（允许旧模型缺少新增类）；
   - 评估 baseline；
   - 计算每个类别的 `drop = old_ap50 - new_ap50`；
   - 任何类别跌幅 > `ap50_drop_max` 判失败；
4. 整体 `mAP50 < map50_min` 判失败；
5. 未提供 baseline 时只给 warning，跳过逐类比较。

新增类别（baseline 没有）不会判失败，但会标记 `新增类别`。

### [5/5] 量化掉点（可选）

若提供 `quantized`：

- 用同一基准集评估量化模型；
- 与浮点模型逐类比较；
- 掉点 > `quant_drop_max` 判失败；
- 若量化模型因算子不支持无法被 Ultralytics 加载，记 warning 而不是 failure。

未提供量化模型时跳过。

---

## 3. 输出

报告写入 `<项目>/Model/`：

```text
Model/
├── release_gate.json   # 完整结构化报告
└── release_gate.csv    # 逐类对比表
```

`release_gate.json` 关键字段：

```json
{
  "golden": ".../golden/dataset.yaml",
  "model": ".../train_20261026.pt",
  "model_sha256": "...",
  "model_size": 12345678,
  "model_mtime_ns": 123456789,
  "dataset_version": "20261026_...",
  "baseline": ".../train_20261020.pt",
  "quantized": ".../model_int8.onnx",
  "class_aligned": true,
  "map50": 0.8231,
  "map50_min": 0.5,
  "ap50_drop_max": 0.03,
  "quant_drop_max": 0.02,
  "leakage": 0,
  "passed": true,
  "failures": [],
  "warnings": [],
  "per_class": [
    {"cls": "目标", "old_ap50": 0.81, "new_ap50": 0.83, "drop": -0.02, "passed": true}
  ],
  "per_class_quantized": [],
  "report": ".../Model/release_gate.json"
}
```

### 报告过期检测

项目快照会读取 `release_gate.json`，并比较：

- `dataset_version` 是否仍等于当前激活版本；
- 模型文件是否仍存在；
- `model_size` 与 `model_mtime_ns` 是否与当前文件一致。

任意一项变化，`release_gate.stale = true`，UI 会提示“报告已过期，请重新跑门禁”。

---

## 4. 从 UI 运行

WPF 模型页 → “发布门禁”会依次询问：

1. 待发布模型；
2. 冻结基准集目录（包含 `dataset.yaml` 或 `manifest.csv`）；
3. 是否对比基线模型（可选）；
4. 是否校验量化模型（可选）；
5. 阈值：mAP50 下限、逐类跌幅、量化掉点。

门禁任务在 worker 内执行，进度以 `progress` 事件推送，日志写入任务目录。结果同时落盘到项目 `Model/`。

---

## 5. 失败排查

| 失败信息 | 含义 | 处理 |
| --- | --- | --- |
| `类别顺序与基准集不一致` | 训练集 names 与 golden 不同 | 统一类别表；不要移动旧类别顺序 |
| `基准集混用了检测框标签与分割多边形标签` | 标签格式不统一 | 统一导出格式，或加 `--strict-labels` 前先修正 |
| `基准集与训练集重叠 N 张` | 数据泄漏 | 用整合把 golden 组固定到 val，或移除重叠样本 |
| `模型类别表与基准集不一致` | 模型输出类别表不同 | 用正确类别表重新训练/导出 |
| `基线模型类别表与基准集不兼容` | baseline 不是 golden 前缀 | 使用同源 baseline，或不做逐类比较 |
| `整体 mAP50 ... 低于下限` | 模型整体退化 | 调整训练/数据，或确认阈值合理 |
| `某类 AP50 跌幅 ... 超过` | 单类退化 | 补样本、检查类别平衡、回滚模型 |
| `量化掉点 ... 超过` | INT8 量化损失过大 | 增加校准数据、改用 FP16、检查量化配置 |

---

## 6. 最佳实践

- **冻结基准集**：golden 一旦用于门禁就不要改；新增数据进入训练集，不进入 golden。
- **先整合后训练**：用黑名单把 golden 组固定在 val，避免训练时泄漏。
- **保留 baseline**：没有 baseline 就无法发现“整体指标没降但某一类崩了”。
- **量化单独验收**：INT8 模型的精度损失必须单独度量，不能只看文件能否导出。
- **报告随模型归档**：`release_gate.json` 与模型一起保存，交付时能追溯阈值与逐类指标。
- **过期就重跑**：数据集版本或模型文件变化后，旧报告不再可信。

---

## 7. 相关文档

- [训练、评估与导出](./07-training-evaluation-export.md)
- [数据集版本与整合](./06-dataset-workflow.md)
- [多数据集整合规范](./DATASET_MERGE.md)
- [测试与验收](./12-testing.md)