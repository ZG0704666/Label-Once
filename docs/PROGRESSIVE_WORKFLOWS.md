# 渐进式工作流与 GPU 验证

“渐进式工作流”指把人放在关键节点、让模型承担重复劳动：

```text
人工初始标注 → SAM 多提示修正 → 视频抽帧 → SAM2 连续跟踪
      ↑                                      ↓
      └──── 暂停纠偏 / 关键帧 / 回填 ←────────┘
```

本文说明这条链路的验收目标、真实 GPU 验收脚本做了什么，以及如何解读结果。它**不**声称模型精度；脚本验证的是流程与几何契约。

---

## 1. 链路拆解

### 1.1 单图：多提示 + ROI + 同一对象

`scripts/check_progressive_gpu.py` 通过真实 JSONL 桥接进程执行：

1. `project.open`；
2. `sam.segment`：
   - 正点 `[200,180]` + 框 `[70,75,310,355]` + 硬 ROI；
   - 第二次追加负点 `[300,80]`；
   - 断言两次返回 `object_id` 相同；
   - 断言所有多边形顶点落在 ROI 内；
3. `annotation.save(confirm=True)`；
4. `annotation.load` 断言 revision 与 `object_id` 往返一致；
5. `export_segmentation` 断言已复核的 SAM 多边形能导出。

这一步验证：

- 提示组合正确传给 SAM；
- ROI 裁剪生效；
- 同一对象多次提示不会更换 `object_id`；
- 保存/加载/导出链路完整；
- 桥接的 stdout 没有被日志污染。

### 1.2 视频：时间戳抽帧 + 导入

脚本生成 12 帧 10fps 的 `source.mp4`：

- `extract` 使用 `interval=.2`；
- 断言导出帧号为 `[0,2,4,6,8,10]`；
- `import_video` 断言导入 6 张；
- 清单输出与帧时间戳一致。

这验证了按真实时间戳抽帧，而不是简单按帧号取模。

### 1.3 SAM2 多边形初始化与纠偏

- 用 `sam2_t.pt` 在 `device=0` 启动 `Sam2Backend`；
- 给目标 7 一个归一化矩形环作为 mask 提示；
- 断言第一帧 mask 与提示多边形的 IoU > 0.95；
- 在帧 2 调用 `correct_current`，断言目标 ID 仍为 7。

这一步验证：

- 多边形提示能保留形状，而不是退化成框；
- 纠偏不会丢失终身目标 ID；
- mask 分辨率与原图对齐。

### 1.4 连续跟踪 + 暂停 + 关键帧 + 回填

脚本：

- 把 5 张抽帧图片人工标注为目标 7 的多边形；
- 启动 `tracking`，并设置 `sample_run` 回填；
- 在进度“帧 3/”时写 `control.json` 请求暂停；
- 收到 `state=paused` 后提交 `commit`，修正当前帧并 `next_id=8`；
- 断言暂停确实发生、关键帧文件存在（帧 2/4/6/8）；
- 断言 `conflicts=[]`；
- 断言项目图片数仍为 7，且没有额外 `video_images/*.jpg`；
- 断言所有抽帧图片都有目标 7 的多边形；
- 断言被修正的图片来源变为“人工”。

这验证：

- 回填模式不会重复生成图片；
- 暂停/纠偏/恢复能连续工作；
- 人工关键帧会覆盖对应帧的自动结果；
- 已复核/人工修改的图片不会被回填覆盖。

### 1.5 重放幂等

再次执行同一 `tracking` 任务，断言所有图片的几何指纹不变。验证已完成的任务重放不会破坏已保存标注。

---

## 2. 运行真实 GPU 验收

前置：

- NVIDIA GPU + 可用驱动；
- `torch` 为 CUDA 版本（`torch.cuda.is_available()` 为 true）；
- `sam/sam2_t.pt` 存在；
- `ultralytics==8.4.161`；
- 能访问 `ultralytics.utils.ASSETS/zidane.jpg`（首次会下载）。

```powershell
python scripts/check_progressive_gpu.py
```

输出：

```text
acceptance/progressive_gpu/<uuid>/
├── project/                  # 验收项目
├── bridge-stderr.log
├── source.mp4
├── extract/                  # 抽帧运行目录
├── tracking/                 # 跟踪运行目录
└── report.json
acceptance/progressive_gpu/latest.json
```

`report.json` 的 `checks` 会列出通过的步骤，例如：

- JSONL multi-positive/negative + bbox + hard ROI + same object + save/load；
- reviewed SAM polygon segmentation export；
- real SAM2 polygon mask init/correction with stable target 7；
- timestamp extract/import → continuous tracking → existing-image backfill → pause polygon commit → resume; no duplicate images；
- completed tracking replay preserves saved annotations。

以及 `mask_prompt_iou`、`device`、`root`、`pass_`。

> 这是**真实 GPU**验收，需要数分钟；脚本使用合成/公开样例，不代表业务数据精度。

---

## 3. 冻结后端渐进式验收

`desktop/scripts/acceptance_frozen_progressive.py` 用发布目录中的 `backend.exe`，在干净环境（仅 System32 PATH、独立 APPDATA、临时工作目录）重跑关键链路：

```powershell
python desktop/scripts/acceptance_frozen_progressive.py `
  "Release/TrainStudio-WPF" `
  "acceptance/wpf/frozen/inputs/fixture_04.jpg" `
  "acceptance/wpf/frozen/inputs/portrait.mp4" `
  "acceptance/wpf/frozen/progressive"
```

它验证：

- 发布包内的后端能独立启动；
- 环境变量隔离后仍能找到模型；
- JSONL 协议、SAM、抽帧、导入、跟踪可用；
- 结果写入 `report.json` 与 `stderr.log`。

与 `check_progressive_gpu.py` 的区别：后者用源码 `python -m studio.bridge`，前者用打包后的 `backend.exe`，更接近用户环境。

---

## 4. 如何解读失败

| 断言失败 | 可能原因 | 排查 |
| --- | --- | --- |
| `GPU acceptance requires CUDA` | 安装了 CPU 版 torch | 重装 cu128 版 torch |
| mask IoU ≤ 0.95 | 多边形提示被退化/缩放错误 | 检查 `imgsz`、原图尺寸、mask resize |
| 抽帧帧号不是 `[0,2,4,...]` | 时间戳/VFR 问题 | 检查视频时间戳，重新封装 |
| 暂停未发生 | 控制命令写得太晚/任务已结束 | 检查 `control.json` 时序与 `pause_token` |
| `conflicts` 非空 | 回填遇到人工修改/已复核 | 查看 `backfill_conflicts.json` |
| 重放后指纹变化 | 回填覆盖了已保存标注 | 检查 `SampleBackfill` 保护条件 |
| 找不到 `sam2_t.pt` | 权重未准备 | 运行 `scripts/prepare_models.ps1` |

---

## 5. 与发布门禁的关系

渐进式验收证明“流程能跑通、几何契约成立”；发布门禁证明“模型在冻结基准集上没有退化”。两者不能互相替代：

- 流程验收通过 ≠ 模型精度达标；
- 门禁通过 ≠ UI/跟踪流程无回归；
- 发布前建议两者都跑。

---

## 6. 相关文档

- [视频抽帧与 SAM2 跟踪](./05-video-workflow.md)
- [WPF 成品验收](./WPF_ACCEPTANCE.md)
- [发布门禁](./08-release-gate.md)
- [测试与验收](./12-testing.md)