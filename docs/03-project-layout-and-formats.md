# 项目目录与数据格式

本文说明 Label Once 如何在磁盘上组织项目、标注、复核记录、数据集版本和全局配置。理解这些格式后，可以直接用脚本检查/备份项目，也能解释 UI 中的状态为什么变化。

---

## 1. 项目目录

一个“项目”就是一个普通目录。`project.open` / 新建项目时，`Project` 会自动创建标准子目录：

```text
我的项目/
├── Main/                    # 图片与视频抽出的帧（.jpg/.png/.bmp/.gif/.webp）
├── Main_labels/             # 与图片同 stem 的标注 sidecar
│   ├── classes.txt          # 类别表，一行一个名称，顺序即类别 ID
│   ├── <stem>.txt           # YOLO 检测框（归一化 cx cy w h）
│   ├── <stem>.mark          # 每个框的来源（人工/AI），一行一个
│   ├── <stem>.segments.json # 与 txt 对应的多边形投影
│   ├── <stem>.annotation.json # 权威标注文档（schema 2，像素坐标）
│   └── <stem>.sync.json     # 投影同步日志（临时/恢复用）
├── Model/                   # 项目内模型权重、experiments.jsonl、release_gate.json
├── Config/                  # 项目级配置与台账
│   ├── review.json          # 复核台账
│   ├── workspace.json       # UI 工作区状态
│   ├── train_preset.json    # 旧版训练预设
│   ├── wpf_train_preset.json# WPF 训练预设
│   └── video_drafts/        # 逐帧视频草稿
├── runs/                    # 每次任务的运行目录
├── <项目名>_dataset/        # 数据集版本仓
│   ├── versions/<version>/  # 不可变版本（images/labels/dataset.yaml/manifest）
│   ├── dataset.yaml         # 当前激活版本的副本（原子指针）
│   ├── active.json          # {"version": "..."}
│   ├── classes_alias.json   # 合并时的类别别名记忆
│   └── sources.json         # 外部来源扫描缓存
├── .trash/                  # 被移除的图片及 sidecar（可恢复）
└── activity.log             # 追加式操作日志
```

### 1.1 图片与标签的配对规则

- 标签按 **stem（不含扩展名）** 与图片配对，例如 `foo.jpg` ↔ `Main_labels/foo.txt`。
- 同一项目不允许不同扩展名的同名图片（`assert_unique_stems`），否则会共用标签。
- 支持扩展名：`.jpg`、`.jpeg`、`.png`、`.bmp`、`.gif`、`.webp`。
- 标签文件存在但内容为空 = **明确的负样本**（已确认无目标）；文件不存在 = 尚未标注。

---

## 2. 标注 sidecar

### 2.1 `.annotation.json`（权威文档，schema 2）

```json
{
  "schema": 2,
  "image_id": "b0e1...",
  "size": [1920, 1080],
  "revision": 7,
  "objects": [
    {
      "cls": 0,
      "x1": 120.0, "y1": 80.0, "x2": 640.0, "y2": 500.0,
      "origin": "人工",
      "score": null,
      "polygons": [[[120,80],[640,80],[640,500]]],
      "raw_polygons": [[[120,80],[640,80],[640,500]]],
      "holes": null,
      "object_id": "9f2c...",
      "target_id": 0,
      "roi": [0, 0, 1920, 1080],
      "geometry_revision": 3
    }
  ],
  "projections": {
    ".txt": "0 0.1979 0.2685 0.2708 0.3889\n",
    ".mark": "人工\n",
    ".segments.json": "{...}"
  }
}
```

- **坐标**：`objects` 中保存原图像素坐标；读取时按 `size` 转回归一化 `[0,1]` 供 UI/算法使用。
- **`revision`**：文档级版本，每次有效保存 +1；`annotation.save` 可携带 `expected_revision` 做乐观并发控制。
- **`geometry_revision`**：单个对象几何变化计数；几何未变时保持不变，复核状态不会因“原样保存”被撤销。
- **`object_id`**：跨保存稳定的对象 ID；视频跟踪的终身目标 ID 另由 `target_id` 表示。
- **投影**：`.txt`、`.mark`、`.segments.json` 是由权威文档生成的兼容文件。读取时若投影被外部修改，会抛出 `AnnotationConflict`，要求用户解决冲突。

### 2.2 原子写入与同步日志

`save_json` / `atomic_write` 的流程：

1. 在目标目录创建 `.<name>` 临时文件；
2. 写入 UTF-8、`\n` 换行；
3. `flush` + `os.fsync`；
4. `os.replace` 原子替换；
5. 清理临时文件。

保存标注时：

1. 先写 `.sync.json`（记录新 revision）；
2. 再原子写 `.annotation.json`；
3. 最后写 `.txt/.mark/.segments.json` 投影并删除 journal。

若中途失败，`read()` 会依据 journal 修复投影；若 journal 与文档 revision 不一致，则丢弃旧投影，避免把旧数据当成新数据。

### 2.3 兼容旧格式

没有 `.annotation.json` 时，`Labels.load()` 直接解析 `.txt` + `.mark` + `.segments.json`：

- `.txt` 每行 `cls cx cy w h`，允许 `#` 注释；
- `.mark` 每行对应一个框的来源，缺省视为“人工”；
- `.segments.json` 带 `label_sha256`，只有与当前 `.txt` 哈希一致时才应用多边形。

旧项目第一次保存会自动升级为 `.annotation.json`，并继续生成兼容 sidecar。

---

## 3. 复核台账 `Config/review.json`

```json
{
  "schema": 2,
  "images": {
    "frame_000001_f12_t480.jpg": {
      "status": "confirmed",
      "batch": "video_ab12cd34ef56",
      "source": "D:\\videos\\demo.mp4",
      "run": "D:\\project\\runs\\tracking_...",
      "frame": 12,
      "import_complete": true,
      "image_sha256": "...",
      "label_sha256": "...",
      "geometry_sha256": "...",
      "reviewer": "local",
      "reviewed_at": "2026-10-26T12:00:00",
      "reject_reason": null
    }
  }
}
```

状态语义：

| 状态 | 含义 |
| --- | --- |
| `legacy` | 台账中没有记录（旧项目/手工放入的图片） |
| `pending` | 有记录但未确认，或确认后文件/几何发生变化 |
| `confirmed` | 图片、标签、几何哈希都与确认时一致 |
| `rejected` | 明确拒绝，附原因；不会进入数据集 |

`ReviewStore.status()` 每次都会校验图片存在、`.txt` 存在、`label_sha256`、`image_sha256` 和 `geometry_sha256`；任何一项变化都会退回 `pending`。因此**修改几何会撤销复核**，而原样保存不会。

`batch` 是分组划分的关键：同一次导入/同一次视频跟踪结果的样本共享 `batch`，必须落在同一个 train/val/test 集合。

---

## 4. 数据集版本目录

```text
<项目名>_dataset/
├── versions/
│   └── 20261026_120000_ab12cd34/
│       ├── images/train|val|test/
│       ├── labels/train|val|test/
│       ├── dataset.yaml
│       └── dataset_manifest.json
├── dataset.yaml
├── active.json
├── classes_alias.json
└── sources.json
```

### 4.1 `dataset.yaml`

```yaml
path: D:/project/我的项目_dataset/versions/20261026_120000_ab12cd34
train: images/train
val: images/val
test: images/test
names:
  0: 目标
  1: 背景物
```

`DatasetStore.activate()` 会把该文件复制到 `<项目名>_dataset/dataset.yaml`，并写 `active.json`。训练/评估默认使用激活版本；也可以显式传 `dataset_version`。

### 4.2 `dataset_manifest.json`

关键字段：

- `schema_version`、`version`、`parent`：版本谱系；
- `names`：类别顺序（发布门禁会核对）；
- `ratios`、`seed`：划分参数；
- `images[]`：`name`、`sha256`、`label_sha256`、`classes`、`group`、`split`；
- `groups{}`：每个分组的 split、样本数、类别；
- `leaked_groups[]`：跨集合分组（正常应为空）；
- `excluded_pending`：因未复核被排除的数量；
- 合并版本还包含 `merges`、`dedupe`、`blacklist`。

### 4.3 分组键

`sample_group()` 的优先级：

1. 复核台账中的 `batch` → `batch:<batch>`；
2. 文件名匹配 `^(.*)_frame_\d+_f\d+_t\d+$` → `video:<视频名>`；
3. 其他 → `solo:<文件名>`。

视频帧和同批导入的图片是近邻重复，必须整组进入同一个 split，避免验证集泄漏。详见 [数据集工作流](./06-dataset-workflow.md)。

---

## 5. 项目级配置

| 文件 | 内容 |
| --- | --- |
| `Config/workspace.json` | 当前页、筛选、选中项等 UI 状态 |
| `Config/train_preset.json` | 旧版训练预设（可被兼容读取） |
| `Config/wpf_train_preset.json` | WPF 训练预设（优先） |
| `Config/video_drafts/<sha>.json` | 同一视频的逐帧草稿，按视频绝对路径哈希隔离 |
| `Model/experiments.jsonl` | 每次训练的审计记录（参数、指标、数据集、产物） |
| `Model/release_gate.json` | 最近一次发布门禁报告 |
| `Model/release_gate.csv` | 逐类 AP50 对比表 |

---

## 6. 全局配置

全局设置位于：

```text
%APPDATA%/YoloTrainStudio/
├── settings.json   # brand、recent 项目、sam_imgsz 等
└── wpf.json        # WPF 材质/首页偏好
```

`studio/config.py` 还定义了：

- `APP_ROOT`：冻结时为可执行文件目录，源码时为仓库根目录；
- `model_paths(sam=False)`：扫描 `APP_ROOT/models`、`APP_ROOT/../models`（SAM 则扫描 `sam`）；
- `ADVANCED` / `AUGMENTS`：默认训练超参与增强参数（优化器固定 `AdamW`）。

---

## 7. 备份与迁移

建议完整备份项目目录，至少包括：

- `Main/` 与 `Main_labels/`（图片 + 全部 sidecar）；
- `Config/review.json`（复核状态）；
- `<项目名>_dataset/`（数据集版本与激活指针）；
- `Model/experiments.jsonl`、`Model/*.pt`、`Model/release_gate.json`；
- `runs/`（需要复现训练/跟踪时）。

迁移后不要只复制图片：缺少 `.annotation.json` 会退回旧格式解析，缺少复核台账会让样本回到 `legacy/pending`，缺少 `active.json` 会让训练找不到数据集版本。

---

## 8. 相关文档

- [图像标注与复核](./04-annotation-workflow.md)
- [数据集版本与整合](./06-dataset-workflow.md)
- [多数据集整合规范](./DATASET_MERGE.md)
- [故障排查](./13-troubleshooting.md)