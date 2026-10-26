# 视频抽帧与 SAM2 跟踪

Label Once 的视频流程分为两条互相衔接的路径：

1. **抽帧**：按时间戳或固定帧间隔从视频导出图片，形成可人工标注的批次；
2. **跟踪**：在已标注的起始帧上初始化目标，用 SAM2 沿视频连续跟踪，暂停纠偏后把结果回填到抽帧图片或导出新批次。

相关实现：`studio/video_sampling.py`、`studio/tracking.py`、`studio/tracking_backfill.py`、`studio/review.py`。

---

## 1. 抽帧（extract）

### 1.1 参数

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `frame_step` | 5 / 10 / 15 / 20 / 30 | 每 N 帧取一帧；UI 默认 10 |
| `interval` | 正数秒 | 旧版按时间间隔抽帧；与 `frame_step` 二选一 |
| `video` | 路径 | 源视频 |
| `run` | 目录 | 任务输出目录 |

`frame_step` 必须是整数值且在允许集合内；`interval` 必须有限且为正。

### 1.2 时间戳索引

抽帧不是简单按帧号取模，而是按 `CAP_PROP_POS_MSEC` 的真实时间戳：

- 第一帧时间戳作为基准；
- 相对时间必须严格递增；出现回退/NaN/负数会报错，避免 VFR 视频抽错帧；
- `frame_step` 模式按解码帧号 `index % step == 0`；
- `interval` 模式按相对时间 `>= target * interval`。

输出命名包含帧号与毫秒时间戳：

```text
video_images/frame_000000_f0_t0.jpg
video_images/frame_000001_f10_t400.jpg
```

### 1.3 帧清单 `frame_manifest.json`

```json
{
  "schema": 2,
  "state": "complete",
  "video": "D:\\videos\\demo.mp4",
  "video_sha256": "...",
  "frame_step": 10,
  "outputs": [
    {
      "image": "...\\frame_000000_f0_t0.jpg",
      "frame": 0,
      "timestamp": 0.0,
      "sample_id": "<video_sha256>:0",
      "width": 1920,
      "height": 1080
    }
  ],
  "decoded_frames": 1200,
  "count": 120
}
```

状态机：

```text
analyzing -> complete
          -> cancelled   (用户取消)
          -> failed      (异常)
```

**完整性边界**：只有 `state=complete` 的清单才允许后续导入。取消/失败/未完成的抽帧结果不能导入，避免半成品污染项目。

### 1.4 取消与恢复

- 取消通过 `cancel` 文件协作式触发，先写清单状态再退出；
- 恢复时必须保持同一视频 SHA256 与同一抽帧计划（`frame_step` 或 `interval`），否则拒绝复用输出；
- 已写出的帧会记录在清单中，恢复时从断点继续；
- 抽帧完成后，WPF 可自动把 `video_images/` 作为一个新批次导入项目，样本状态为 `pending`。

### 1.5 手动抽帧 vs 跟踪导出

- `extract` 只产出图片，不产出标签；
- 之后在图片上人工标注，再通过“从当前帧跟踪”把人工目标作为跟踪起点；
- 跟踪结果可以：
  - 回填到已导入的抽帧图片（`sample_run` 模式）；
  - 或导出新的 `video_images/` + `video_images_labels/` 批次，再通过 `import_video` 导入。

---

## 2. SAM2 视频跟踪（tracking）

### 2.1 依赖与约束

- 固定 `ultralytics==8.4.161`；版本不符会直接报错，因为内部使用了该版本的 `SAM2VideoPredictor` 结构与 mask 维度约定；
- 模型权重来自 `sam/` 或项目 `Model/`；
- 目标数量 1–32，目标 ID 必须在 `[0,32)`；
- 起始帧必须在视频范围内；
- 同一时间只运行一个任务。

### 2.2 初始化

任务输入包含：

- `video`、`model`、`classes`、`device`、`imgsz`；
- `targets[]`：每个目标的 `id`、`cls`、`box`（归一化）、可选 `polygons`/`holes`/`object_id`；
- `start_frame`；
- `frame_step` 或 `interval`（控制导出/回填节奏）；
- 可选 `sample_run`（回填已有抽帧批次）；
- 可选 `quality`（覆盖默认质量阈值）。

有 `sample_run` 时，会先校验该抽帧清单已完成且视频 SHA256 一致，然后建立“帧号 → 项目图片名”的映射。

### 2.3 质量门（quality gate）

每帧跟踪结果都会与上一帧比较，默认阈值在 `studio/tracking.py` 的 `QUALITY`：

| 指标 | 默认值 | 触发原因 |
| --- | --- | --- |
| 目标面积比 | `0.45 ~ 1.8` | 面积突变 |
| IoU | `>= 0.02` | 与中心距离联合判断位置突变 |
| 中心距离 / sqrt(旧面积) | `<= 1.25` | 位置突变 |
| 目标面积 / 画面面积 | `<= 0.85` | 目标占画面过大 |

任一目标触发失败，跟踪会**自动暂停**并释放 GPU，等待人工处理；不会静默跳过坏帧。

### 2.4 暂停、纠偏与恢复

暂停确认后：

- 释放模型与显存（`release_gpu`）；
- 读取精确的暂停帧并生成 `preview_pause_<frame>.jpg`；
- 写入 `pause_token` 和 `gpu_released=true`；
- 只有携带正确 `pause_token` 的控制命令才允许提交。

控制命令通过 `control.json` 传递（同一时间只允许一条未处理命令）：

| action | 作用 |
| --- | --- |
| `pause` | 暂停跟踪 |
| `resume` | 用当前目标重新初始化并继续 |
| `correct` | 修改某个目标的框 |
| `add` | 新增目标（受 32 个终身 ID 限制） |
| `end` | 结束某个目标 |
| `seek` | 仅在无活动目标时向前定位 |
| `commit` | 提交当前暂停帧的目标修正 |
| `finish_review` | 提交并结束跟踪 |

提交时会：

- 校验类别映射未变化；
- 校验暂停帧、目标 ID、坐标范围；
- 保存 `keyframe_<frame>.json`；
- 若该帧已有输出，同步更新标签；
- 回填模式下同步更新项目图片；
- 重新初始化 SAM2 继续跟踪。

### 2.5 关键帧与回填

- 人工关键帧保存在 `planned_keyframes.json` 与 `keyframe_<frame>.json`，恢复时优先应用；
- 连续跟踪到关键帧时，应用人工几何并重新初始化，不会制造“自己和自己冲突”；
- 回填模式只更新**本任务候选输出**；以下情况会写入 `backfill_conflicts.json` 而不是覆盖：
  - 图片已复核；
  - 几何已被人工修改；
  - 当前指纹与任务开始时记录的版本不一致；
- 人工关键帧关联目标时，优先用 `target_id`；无法唯一确定时拒绝回填，要求用户保持目标 ID 一致。

### 2.6 输出

```text
runs/tracking_<时间戳>_<随机串>/
├── frame_manifest.json       # 清单、目标状态、输出、关键帧、暂停信息
├── planned_keyframes.json    # 计划应用的人工关键帧
├── keyframe_<frame>.json     # 已提交的关键帧
├── preview_*.jpg             # 跟踪预览
├── preview_pause_*.jpg       # 暂停帧
├── video_images/             # 导出的图片（非回填模式）
├── video_images_labels/      # 对应标签
├── backfill_versions.json    # 回填指纹
└── backfill_conflicts.json   # 回填冲突候选
```

非回填模式下，只有满足采样步长的帧才会导出；导出前会清理“已写盘但未登记”的残留文件，避免恢复时被同名文件卡死。

### 2.7 恢复

`task.restore` 可以重新打开当前项目内的跟踪/抽帧任务目录：

- 校验任务类型与项目归属；
- 校验视频、模型、采样计划、清单 schema、Ultralytics 版本、输入尺寸；
- 清理未登记的残留输出；
- 从最后一个 segment/checkpoint 继续。

不允许跨项目恢复。

---

## 3. 导入视频结果（import_video）

`task.start(kind='import_video')` 会调用 `studio.review.import_video`，把跟踪/抽帧任务目录导入项目：

1. 只接受 `kind` 为 `tracking` 或 `extract` 的任务；
2. 手动抽帧（`extract`）要求清单 schema ≥ 2 且 `state=complete`；
3. 跟踪结果要求存在 `video_images_labels/classes.txt`；
4. 只导入清单 `outputs` 中登记的帧；
5. 类别按名称对齐到项目类别表，新类名追加；
6. 批次 ID 为 `video_<任务路径哈希前 12 位>`；
7. 已完整导入的样本会复用，不会覆盖人工修改；
8. 目标文件冲突时拒绝，不覆盖；
9. 先登记计划，再逐张复制并更新 `import_complete`，中断后可安全恢复；
10. 导入后的样本状态为 `pending`，仍需人工复核。

---

## 4. 视频草稿

WPF 视频逐帧编辑的草稿保存在：

```text
Config/video_drafts/<视频绝对路径 SHA256>.json
```

按视频路径隔离，避免同名视频互相覆盖；结构为：

```json
{
  "schema": 1,
  "video": "D:\\videos\\demo.mp4",
  "frames": {
    "0": [{"cls": 0, "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.6}]
  }
}
```

草稿只是编辑状态，不等于正式标签；确认后仍通过 `annotation.save` 写入项目。

---

## 5. 性能与资源建议

- 跟踪会持续占用 GPU；暂停后确认 `gpu_released=true` 再进行 SAM 单图分割，避免模型互相抢占显存；
- 长视频建议先用较大 `frame_step` 试跑，确认跟踪质量后再加密；
- 抽帧和跟踪输出会显著增加磁盘占用，定期清理废弃的 `runs/`；
- `imgsz` 必须是 32 的倍数（默认 1024）；
- TensorRT 导出与机器绑定，视频跟踪建议使用 `.pt` 权重。

---

## 6. 相关文档

- [渐进式工作流与 GPU 验证](./PROGRESSIVE_WORKFLOWS.md)
- [图像标注与复核](./04-annotation-workflow.md)
- [数据集版本与整合](./06-dataset-workflow.md)
- [故障排查](./13-troubleshooting.md)