# 多数据集整合规范

整合（merge）把多个来源合成一个新的、不可变的训练数据集版本。它的目标不是“把文件堆在一起”，而是同时保证：

- 类别顺序不被破坏（只追加）；
- 图片内容不重复；
- 同一视频/批次不跨 train/val/test；
- 冻结基准集不进入训练集；
- 预览与提交使用同一套计划，结果可解释。

实现：`studio/merge.py`。相关流程见 [数据集版本与整合](./06-dataset-workflow.md)。

---

## 1. 来源类型

| `kind` | 说明 | 扫描规则 |
| --- | --- | --- |
| `project` | 当前项目中已完成的素材 | 排除 pending/rejected，缺标签跳过 |
| `version` | 当前项目的某个数据集版本 | 读取版本 manifest，必须图片/标签齐全 |
| `cross_project` | 其他 Label Once 项目 | 读取对方激活版本或指定版本，来源只读 |
| `external_yolo` | 外部 YOLO 目录 | 支持 `images/` + `labels/` 或扁平结构；无标签图片作为空标注负样本 |

外部目录结构示例：

```text
external/
├── dataset.yaml          # 可选，提供 names
├── classes.txt           # 或这个
├── images/
│   ├── train/...
│   └── val/...
└── labels/
    ├── train/...
    └── val/...
```

也支持：

```text
external/
├── train/images/*.jpg
├── train/labels/*.txt
├── val/images/*.jpg
└── val/labels/*.txt
```

或扁平：

```text
external/
├── a.jpg
├── a.txt
└── b.jpg                 # 没有 b.txt → 负样本
```

外部目录的哈希会按“路径 + 大小 + mtime”缓存到 `<项目>_dataset/sources.json`，目录内容不变时预览不会重复全量哈希。

---

## 2. 规格（spec）

```json
{
  "sources": [
    {"kind": "project"},
    {"kind": "version", "version": "20261020_101500_ab12cd34"},
    {"kind": "cross_project", "path": "D:\\data\\另一个项目", "version": "20261018_..."},
    {"kind": "external_yolo", "path": "D:\\data\\公开数据集"}
  ],
  "ratios": [0.7, 0.2, 0.1],
  "seed": 42,
  "dedup": "last",
  "keep_segment": true,
  "accept_new_classes": false,
  "resolutions": {
    "Person": "person",
    "person ": "person"
  },
  "blacklist": [
    "D:\\data\\golden\\dataset.yaml",
    "D:\\data\\golden\\manifest.csv",
    "3f2a...64位sha256..."
  ]
}
```

| 字段 | 默认 | 约束 |
| --- | --- | --- |
| `sources` | 必填 | 至少一个；`version` 缺省用激活版本；`cross_project` 缺省用对方激活版本 |
| `ratios` | `[0.7,0.2,0.1]` | 三个非负数，总和为 1；train+val 不能同时为 0 |
| `seed` | `42` | 整数 |
| `dedup` | `last` | `first` / `last`，决定同名冲突/同图不同标签时保留谁 |
| `keep_segment` | `true` | `false` 时丢弃多边形行，只保留检测框行 |
| `accept_new_classes` | `false` | `false` 时新增类别会产生 `NEW_CLASSES` 阻断，需预览确认后显式置 true |
| `resolutions` | `{}` | 显式解决类别名大小写/别名歧义 |
| `blacklist` | `[]` | 路径（目录/CSV/yaml/单图）或 64 位 SHA256 |

`preview()` 与 `merge()` 都先调用 `_normalize_spec()`，因此校验规则完全一致。

---

## 3. 计划阶段（preview）

`preview()` 执行 `_plan()` 但不写版本。步骤：

### 3.1 扫描

- 当前项目：只看 `confirmed`/`legacy`，缺标签跳过；
- 版本：读取 `dataset_manifest.json`，按 split 定位图片/标签；缺文件直接报错；
- 跨项目：只读，不修改对方；
- 外部目录：识别 train/val/test 子目录，读取 `dataset.yaml`/`classes.txt` 的 names。

### 3.2 类别对齐（只追加）

规则优先级：

1. 名称完全匹配现有类别 → `exact`；
2. `resolutions` 显式指定 → `resolution`；
3. `classes_alias.json` 中记住的别名 → `alias`；
4. 大小写不敏感唯一匹配 → `alias`；
5. 否则追加为新类 → `new`。

约束：

- 既有类别 ID **永不移动**；
- 新类按首次出现顺序追加到末尾；
- 同一名称存在多种大小写变体且未显式解决 → `CLASS_UNRESOLVED` 阻断；
- 有样本但来源没有类别表 → `CLASS_TABLE_MISSING` 阻断；
- 类别 ID 超出该来源类别表 → `ID_OUT_OF_RANGE` 阻断；
- 有新类且 `accept_new_classes=false` → `NEW_CLASSES` 阻断（提示先预览确认）。

### 3.3 内容去重

以图片 SHA256 为权威键：

- 同名同图同标签 → 重复，跳过；
- 同名不同内容 → `STEM_CLASH` 阻断（落盘会覆盖）；
- 同图不同名同标签 → 重复，跳过（否则同一图可能分到不同 split）；
- 同图不同名不同标签 → 内容冲突，按 `dedup` 保留 first/last，并记 `HASH_DUP_CONTENT_CLASH` warning。

### 3.4 基准集黑名单

黑名单解析支持：

- `manifest.csv`（列名 `sha256`/`image_sha256`/`hash`）；
- `dataset.yaml`（按 train/val 路径扫描图片）；
- 纯图片目录；
- 单张图片；
- 直接给 SHA256。

命中样本：

- 强制进入 `val`；
- 同组近邻帧一起进入 `val`；
- 产生 `GOLDEN_PIN` 或 `GOLDEN_GROUP` warning。

这保证训练集看不到基准集内容。

### 3.5 统一重划

- **所有来源原有 split 一律作废**；
- 按 `ratios + seed + 分组` 重新划分；
- 分组同 [数据集工作流](./06-dataset-workflow.md)：`batch:` / `video:` / `solo:`；
- 黑名单固定项优先，不参与随机分配；
- 若固定后仍出现跨集合分组 → `CROSS_SPLIT_GROUP` warning；
- 比例非零但集合为空 → `EMPTY_SPLIT` warning。

### 3.6 报告

预览返回：

```json
{
  "total": 1200,
  "names": ["person", "car"],
  "new_classes": ["bike"],
  "class_rows": [{"source": "external_yolo:...", "name": "Person", "target": 0, "canon": "person", "status": "alias"}],
  "dedupe": {"duplicates": 8, "content_clashes": [], "content_clash_count": 0},
  "blacklist": {"hits": 20, "pinned_samples": 26, "blacklist_size": 100},
  "conflicts": {"blocks": [], "warnings": []},
  "estimate": {"total": 1200, "by_split": {"train": 840, "val": 240, "test": 120}},
  "per_source": [
    {"source": "project", "kind": "project", "samples": 800, "contributed": 790, "deduped": 10, "empty_labels": 3, "by_split": {"train": 550, "val": 160, "test": 80}, "skipped": 0}
  ]
}
```

UI 会展示 blocks/warnings、类别映射表和每来源贡献数；用户确认新增类别后才允许提交。

---

## 4. 提交阶段（merge）

`merge()`：

1. `project.assert_unique_stems()`；
2. 重新执行 `_plan()`（与预览同路径）；
3. 有 blocks 直接拒绝，不写任何文件；
4. 新类先追加到项目 `classes.txt`（只追加）；
5. 创建 `versions/.<version>` 临时目录；
6. 按 split 复制图片；
7. 写标签并按 `remaps` 重映射类别 ID；`keep_segment=false` 时丢弃多边形行；
8. 写 `dataset_manifest.json` 与 `dataset.yaml`；
9. 原子改名 `.version` → `version`；
10. `activate(version)`；
11. 更新 `classes_alias.json`；
12. 写 `activity.log`；
13. 异常时删除临时目录，不留下半成品。

输出：

```json
{
  "version": "20261026_...",
  "dataset": ".../versions/.../dataset.yaml",
  "total": 1200,
  "by_split": {"train": 840, "val": 240, "test": 120},
  "new_classes": ["bike"],
  "duplicates": 8,
  "content_clashes": [],
  "class_rows": [...],
  "per_source": [...]
}
```

---

## 5. 冲突代码

### 阻断（blocks）

| code | 含义 | 解决 |
| --- | --- | --- |
| `CLASS_TABLE_MISSING` | 来源有样本但无类别表 | 提供 `dataset.yaml`(names) 或 `classes.txt` |
| `ID_OUT_OF_RANGE` | 标签类别 ID 超出类别表 | 修复来源标签/类别表 |
| `NEW_CLASSES` | 将新增类别但未确认 | 预览后设置 `accept_new_classes=true` |
| `CLASS_UNRESOLVED` | 同名多大小写变体无法自动对齐 | 在 `resolutions` 显式指定 |
| `STEM_CLASH` | 同名不同内容，落盘会覆盖 | 重命名其中一方 |

### 警告（warnings）

| code | 含义 | 影响 |
| --- | --- | --- |
| `HASH_DUP_CONTENT_CLASH` | 同图不同标签 | 按 dedup 策略保留一份 |
| `GOLDEN_PIN` | 基准集命中并固定 val | 正常 |
| `GOLDEN_GROUP` | 同组近邻帧一起固定 val | 正常，验证集变大 |
| `CROSS_SPLIT_GROUP` | 固定项导致分组跨集合 | 检查黑名单/分组 |
| `EMPTY_SPLIT` | 某个非零比例集合为空 | 增加样本或调整比例 |

---

## 6. 调用方式

### Python

```python
from studio.domain import Project
from studio.dataset import DatasetStore
from studio.merge import preview, merge

store = DatasetStore(Project(r"D:\data\我的项目"))
spec = {
    "sources": [{"kind": "project"}, {"kind": "external_yolo", "path": r"D:\data\公开集"}],
    "ratios": [0.7, 0.2, 0.1],
    "seed": 42,
    "dedup": "last",
    "accept_new_classes": True,
    "blacklist": [r"D:\data\golden\dataset.yaml"],
}

report = preview(store, spec)       # 只读
result = merge(store, spec)         # 写新版本并激活
```

### 后端任务

```json
{"kind": "dataset_merge", "project": "...", "spec": {...}}
```

任务事件会推送 `progress` 与最终 `result`；日志写入运行目录。

### WPF

训练/数据集页 → “整合数据集”：

1. 添加来源（当前项目 / 版本 / 其他项目 / 外部目录）；
2. 调整比例/种子/去重策略；
3. 选择基准集黑名单；
4. 预览，查看类别映射与阻断/警告；
5. 确认新增类别后提交。

---

## 7. 设计约束与注意事项

- **来源只读**：整合不会修改外部目录、其他项目或已有版本；
- **版本不可变**：每次整合生成新版本，旧版本保持可读；
- **类别只追加**：不要通过整合“重排”类别；需要重排时先用“管理类别”并备份；
- **不继承原 split**：统一重划是刻意的，避免不同来源的划分口径冲突；
- **同名策略**：`dedup` 只影响同图不同标签/同名冲突的取舍，不会让同名不同内容通过；
- **空标签**：外部无标签图片会作为负样本写入空 `.txt`，这是有意行为；
- **多边形**：`keep_segment=false` 会丢弃多边形行，可能把分割数据降级为检测数据，提交前确认；
- **别名记忆**：`classes_alias.json` 会在下次自动复用映射，减少重复确认；
- **预览即承诺**：预览与提交走同一计划，但来源在此期间变化会导致结果不同；提交前尽量冻结来源。

---

## 8. 相关文档

- [数据集版本与整合](./06-dataset-workflow.md)
- [项目目录与数据格式](./03-project-layout-and-formats.md)
- [发布门禁](./08-release-gate.md)
- [术语表](./14-glossary.md)