# 数据集版本与整合

数据集是把“已复核标注”冻结成可训练、可复现的实验输入。Label Once 的数据集是不可变版本：每次创建/整合都会生成新目录，激活指针单独维护。

实现位置：`studio/dataset.py`、`studio/merge.py`、`studio/review.py`。

---

## 1. 创建数据集版本

入口：

- WPF 训练页 → “数据集”/“增量更新”；
- 后端 `task.start`，`kind=dataset`；
- 或直接调用 `DatasetStore.create()`。

### 1.1 入选条件

`DatasetStore.create()` 只纳入：

- 复核状态不是 `pending` / `rejected` 的图片（`legacy` 和 `confirmed` 可入选）；
- 存在同名 `.txt` 的图片（空文件表示负样本）；
- 类别 ID 在项目类别表范围内。

缺失 `.txt` 的图片会被跳过；它表示“还没标注”，不是负样本。未复核的样本会计入 `excluded_pending`。

### 1.2 划分参数

| 参数 | 默认 | 约束 |
| --- | --- | --- |
| `ratios` | `(0.7, 0.2, 0.1)` | 三项非负、总和为 1 |
| `seed` | `42` | 同一数据/参数下可复现 |
| `incremental` | `False` | 增量更新需保持类别与比例 |

划分算法 `_plan_splits()` 的核心：

1. 按 `group` 聚合样本（视频/导入批次/单图）；
2. 以组为单位分配，**任何组不会跨 train/val/test**；
3. 按类别缺口与目标数量打分，兼顾类别平衡；
4. 小数据集会尽量让非零比例的分集合非空；
5. 记录 `leaked_groups`；普通创建若出现跨集合分组会直接失败。

确定性：同一 `seed`、同一数据、同一比例，重复创建会得到相同的 `name/split` 映射。

### 1.3 增量更新

`incremental=True` 时：

- 必须存在激活版本；
- 类别表与比例必须与旧版本一致，否则要求“重新平衡”；
- 旧样本必须仍存在且图片 SHA256、标签 SHA256 未变化；
- 旧样本沿用原 split，新样本按组补入；
- 若样本集合完全没变，直接返回旧版本，不产生空版本。

### 1.4 版本产物

```text
<项目名>_dataset/versions/<version>/
├── images/train|val|test/
├── labels/train|val|test/
├── dataset.yaml
└── dataset_manifest.json
```

创建过程先写入 `.<version>` 临时目录，全部成功后再原子改名为正式版本；异常会清理临时目录，不会留下半成品。

### 1.5 激活

`DatasetStore.activate(version)`：

1. 校验 `dataset_manifest.json` 存在；
2. 把版本内 `dataset.yaml` 复制为 `<项目名>_dataset/dataset.yaml`；
3. 写入 `active.json = {"version": ...}`。

训练/评估默认读取激活版本；发布门禁也会用激活版本核对类别顺序。

---

## 2. 分组与泄漏

视频帧和同批导入图片是近邻重复。如果按单张随机划分，验证集会出现训练集的“近似副本”，指标虚高。

分组键优先级：

1. `review.json` 中的 `batch`；
2. 文件名 `*_frame_<n>_f<frame>_t<ms>` 的 `video:<前缀>`；
3. `solo:<文件名>`。

因此：

- 同一次导入的所有图片共享一个 `batch`；
- 同一视频抽出的所有帧共享一个 `video` 组；
- 跟踪结果导入的批次共享 `batch`。

`manifest.groups` 记录每个组最终落在哪个 split、样本数与类别；`manifest.leaked_groups` 正常必须为空。

---

## 3. 多数据集整合（merge）

整合用于把多个来源合成一个新的训练版本，入口：

- WPF：训练/数据集页 → “整合数据集”；
- 后端：`dataset.merge.preview`、`task.start(kind=dataset_merge)`；
- Python：`studio.merge.preview()` / `merge()`。

完整规范见 [多数据集整合规范](./DATASET_MERGE.md)。这里给出流程概览。

### 3.1 来源类型

| kind | 说明 |
| --- | --- |
| `project` | 当前项目中已完成的素材 |
| `version` | 当前项目的某个数据集版本 |
| `cross_project` | 其他 Label Once 项目 |
| `external_yolo` | 外部 YOLO 目录（`images/` + `labels/` 或扁平结构） |

外部目录没有标签的图片会作为**空标注负样本**收录。来源始终只读。

### 3.2 计划与预览

`preview()` 与 `merge()` 共用同一条 `_plan()` 路径：

1. 扫描来源（按内容指纹缓存到 `sources.json`）；
2. 类别按名称对齐，只追加新类别，绝不移动旧 ID；
3. 内容去重（默认 `last`，可设 `first`）；
4. 解析黑名单（路径、manifest.csv、dataset.yaml、单图或 SHA256）；
5. 按组统一重划 train/val/test，原有划分全部作废；
6. 产出 blocks（阻断）与 warnings（警告）。

预览不写任何版本；提交时若存在 blocks 会拒绝。

### 3.3 类别别名

首次确认的类别映射会写入 `<项目名>_dataset/classes_alias.json`。后续遇到同名/大小写不同的类别会自动复用，减少重复确认。

### 3.4 去重与冲突

- 图片内容完全相同（SHA256 相同）：按策略保留 first/last；
- 内容相同但标签不同：记为 content clash，按策略选一个并写入报告；
- 文件名 stem 冲突：阻断（BLOCK）；
- 大小写冲突：阻断，要求硬解决；
- 类别 ID 超出来源类别表：阻断。

### 3.5 基准集黑名单

发布门禁使用冻结基准集（golden）。整合时把 golden 的图片哈希加入黑名单：

- 命中样本强制进入 `val`；
- 同组近邻帧也一起固定在 `val`；
- 训练集永远看不到基准集内容。

这是“训练/验证泄漏”的最后一道前置防线；发布门禁还会再检查一次。

### 3.6 输出

整合成功后生成新版本并自动激活：

- `dataset_manifest.json` 额外包含 `merges`（每来源统计）、`dedupe`、`blacklist`；
- 项目 `activity.log` 记录来源数、样本数、类别数、去重数与分布；
- 返回 `version`、`dataset`、`by_split`、`new_classes`、`duplicates`、`content_clashes`、`per_source`。

---

## 4. 版本选择与训练绑定

- 训练任务创建时解析 `dataset_version`，默认取激活版本；
- `task.dataset` 写入该版本的 `dataset.yaml` 绝对路径；
- `task.dataset_version` 写入版本号，训练记录与发布门禁都会引用；
- 切换激活版本不会修改历史训练记录；
- 删除/移动版本目录会导致旧实验无法复现，建议保留完整版本仓。

---

## 5. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| “没有已审核的图片标签” | 全部样本仍是 pending，或没有 `.txt` | 逐张确认/保存空标注 |
| 版本里没有某张图 | 未确认、被拒绝、缺 `.txt` | 检查复核台账与标签文件 |
| 验证集指标异常高 | 同组样本跨集合 | 检查 `leaked_groups`，用整合重新划分 |
| 增量更新失败 | 类别/比例变化或旧样本被改动 | 使用重新平衡或恢复旧文件 |
| 整合被阻断 | 类别表缺失、ID 越界、stem/大小写冲突 | 按报告逐项修复来源 |
| 整合后类别顺序变了 | 旧类别被移动 | 不允许；只能追加新类，检查 `classes_alias.json` |
| 训练找不到数据集 | 没有激活版本 | 先创建/激活版本 |

---

## 6. 相关文档

- [项目目录与数据格式](./03-project-layout-and-formats.md)
- [多数据集整合规范](./DATASET_MERGE.md)
- [训练、评估与导出](./07-training-evaluation-export.md)
- [发布门禁](./08-release-gate.md)