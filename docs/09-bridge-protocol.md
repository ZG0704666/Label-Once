# JSONL 桥接协议与任务事件

WPF 桌面端与 Python 后端之间使用**版本化 UTF-8 JSON Lines（JSONL）**协议，通过标准输入/输出通信。协议实现位于 `studio/bridge.py`，客户端实现位于 `desktop/LabelOnce.Desktop/Services/BridgeClient.cs`。

---

## 1. 传输与编码

- 一行一个 JSON 对象，以 `\n` 分隔；
- 编码固定 UTF-8；`bridge.main()` 会把 stdin/stdout/stderr 重配置为 UTF-8；
- **stdout 只承载协议帧**；日志、第三方库横幅、进度条必须走 stderr；
- 后端退出码/异常通过 stderr 与错误帧传递。

### stdout 卫生

Ultralytics 等库可能在导入/推理时给 logger 挂 `StreamHandler(sys.stdout)`，把日志混进协议管道。`_rebind_stdout_handlers()` 会在每帧发送前扫描 root logger 与所有已注册 logger，把指向 `sys.stdout` 的 handler 改指 `sys.stderr`。

`StudioService.dispatch()` 执行期间还会用 `contextlib.redirect_stdout(sys.stderr)` 兜底，确保业务代码的 `print` 不会污染协议。

客户端也会容错：

- 忽略空行；
- 去掉行首 BOM/空白；
- 无法解析为 JSON 的脏行降级为日志，不崩桥；
- 版本号不是 1 的帧忽略并提示更新后端。

---

## 2. 请求

```json
{"version": 1, "id": 42, "method": "project.open", "params": {"path": "D:\\data\\项目"}}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `version` | int | 必须为 `1` |
| `id` | string \| int | 客户端生成，响应原样带回 |
| `method` | string | 方法名 |
| `params` | object | 可选，默认 `{}`；必须是对象 |

校验失败（版本/ID/params 类型）会返回错误帧，`id` 可能为 `null`。

---

## 3. 响应

成功：

```json
{"version": 1, "id": 42, "result": {"project": "...", "classes": ["目标"]}}
```

失败：

```json
{
  "version": 1,
  "id": 42,
  "error": {
    "code": "ValueError",
    "message": "请先打开或新建项目",
    "retryable": false
  }
}
```

- `code` 是异常类名；
- `retryable` 对 `OSError` / `RuntimeError` 为 `true`，表示可能是暂时性问题（如任务忙、文件占用）；
- 详细 traceback 写入后端 stderr，不进入协议帧。

客户端 `Call()` 默认等待 30 分钟；超时会抛出“后端响应超时”的 `IOException`，但后台任务可能仍在运行。

---

## 4. 事件

后台任务产生的事件由 `StudioService` 的 emit 回调包装后发送：

```json
{"version": 1, "event": {"event": "progress", "value": 0.42, "text": "第 8/20 轮", "task_kind": "train", "project": "...", "run": "...", "session": "..."}}
```

外层 `version=1` + `event`，内层保留 worker 的原始事件字段。`ProcessManager` 还会补充：

- `task_kind`
- `project`
- `run`
- `session`（若任务有）
- `request`（若任务有）

常见事件：

| event | 关键字段 | 说明 |
| --- | --- | --- |
| `progress` | `value`、`text`、可选 `frame/total/exported` | 通用进度 0–1 |
| `epoch` | `epoch`、`metrics` | 训练每轮指标 |
| `log` | `message` / `data` | 日志/提示 |
| `tracking_state` | `state`、`targets`、`frame`、`pause_token`、`gpu_released` | 跟踪状态 |
| `tracking_frame` | `frame`、`path`、`boxes`、`targets` | 跟踪预览 |
| `result` | `result` | 任务成功结果 |
| `error` | `message`、`traceback` | 任务失败 |
| `cancelled` | `message` | 用户取消 |
| `finished` | `exit_code` | 监督层收尾，总会发送 |

终止事件是 `result` / `error` / `cancelled`。监督层若在进程退出前没看到终止事件，会补发 `error`。

---

## 5. 方法表

### 5.1 连接与设置

| 方法 | 说明 |
| --- | --- |
| `hello` | 返回协议版本、capabilities、settings、WPF preferences、模型路径、默认超参/增强 |
| `settings.save` | 保存全局设置与 WPF 偏好；`sam_imgsz` 必须是 32 的倍数 |

`hello` 返回的 capabilities 当前包括：`review.batch`、`review.pending`、`review.reject`、`progress.frame_counts`、`task.control.supersedes`。

### 5.2 项目

| 方法 | 说明 |
| --- | --- |
| `project.open` | 打开/创建项目，校验文件名唯一，更新最近项目，返回快照 |
| `project.snapshot` | 返回当前项目完整快照 |
| `workspace.save` | 保存 UI 工作区状态 |

项目快照包含：项目路径、类别、统计、图片列表及复核状态/批次/元数据、数据集版本与激活版本、发布门禁状态、模型/SAM 路径、工作区、实验记录。

### 5.3 图片

| 方法 | 说明 |
| --- | --- |
| `images.import` | 导入文件/目录，返回名称、重复/失败报告与快照 |
| `images.transfer` | 复制或移动图片到另一个项目 |
| `images.rename` | 预览或执行批量重命名（图片与 sidecar 成对） |
| `images.trash` | 移到项目 `.trash/`，可恢复 |

### 5.4 标注与复核

| 方法 | 说明 |
| --- | --- |
| `annotation.load` | 加载图片（生成无 EXIF 旋转的临时 PNG）、尺寸、方向、框、revision、复核元数据 |
| `annotation.save` | 保存标注，可选 `confirm`；支持 `expected_revision` |
| `annotation.simplify` | 对 `raw_polygons` 做轮廓简化 |
| `review.pending` | 批量检查缺标签/空标签/未知类别 |
| `review.confirm` | 确认复核（校验图片、标签、类别、哈希） |
| `review.reject` | 拒绝复核并记录原因 |

### 5.5 类别

| 方法 | 说明 |
| --- | --- |
| `classes.ensure` | 按名称获取或追加类别，返回 class_id |
| `classes.save` | 保存类别表并按映射重排旧标签，写前备份 |

`classes.save` 的 `mapping` 未提供时，会按同名保留并补齐未映射项；显式映射中 `-1` 表示移除该旧类别的标注。

### 5.6 SAM

| 方法 | 说明 |
| --- | --- |
| `sam.segment` | 单图交互式分割；支持点/框/ROI；可复用跟踪暂停帧 |
| `sam.release` | 释放 SAM 模型与显存 |

### 5.7 数据集

| 方法 | 说明 |
| --- | --- |
| `dataset.activate` | 激活指定版本，更新 `dataset.yaml` 与 `active.json` |
| `dataset.merge.preview` | 预览整合计划，不写版本 |
| `dataset.sources` | 列出/遗忘外部来源缓存 |
| `dataset.merge.external_versions` | 列出外部项目的版本 |

### 5.8 预设与视频

| 方法 | 说明 |
| --- | --- |
| `preset.get` | 合并默认值、旧预设与 WPF 预设 |
| `preset.save` | 保存 WPF 训练预设 |
| `video.open` | 打开视频，返回第 0 帧与会话 ID |
| `video.frame` | 读取指定帧（会话校验） |
| `video.draft.save` / `video.draft.load` | 按视频路径哈希保存/读取逐帧草稿 |

### 5.9 任务

| 方法 | 说明 |
| --- | --- |
| `task.start` | 启动任务；忙碌时拒绝；校验 kind 与必填参数 |
| `task.cancel` | 写 cancel 文件；`force=true` 时杀进程树 |
| `task.status` | 返回 `busy` 与当前任务 |
| `task.control` | 写入控制命令（暂停/恢复/纠偏/提交等） |
| `task.restore` | 恢复当前项目的跟踪/抽帧任务 |
| `tracking.candidate` | 读取回填冲突候选 |

---

## 6. 任务控制与并发

- `StudioService.require(params, idle=True)` 会：
  - 要求项目已打开；
  - 拒绝属于旧项目的过期请求；
  - 在 `idle=True` 时拒绝忙碌状态下的修改操作。
- 大多数写操作（导入、重命名、保存、数据集、训练等）都要求空闲；
- 跟踪暂停时允许特定 SAM/纠偏操作，但需要 `pause_token` 与 `gpu_released` 校验；
- `task.control` 同一时间只允许一条未处理的 `control.json`，避免命令堆积；
- 取消是协作式的：worker 在循环/回调中检查 `cancel` 文件；强制取消只是兜底。

---

## 7. 客户端实现要点

`BridgeClient`：

- 用 `SemaphoreSlim` 串行化写端，避免多线程交错写坏 JSON 行；
- 用 `ConcurrentDictionary<id, TaskCompletionSource>` 管理并发请求；
- 事件通过 WPF Dispatcher 切回 UI 线程；
- 后端退出时，所有 pending 请求以异常结束，并触发 `Faulted`；
- `Dispose()` 先关闭 stdin，等待 15 秒，必要时 `Kill(true)`；
- 后端找不到时给出明确路径提示（`LABELONCE_BACKEND` / `LABELONCE_SOURCE` / `LABELONCE_PYTHON`）。

---

## 8. 扩展协议

新增方法时：

1. 在 `StudioService.dispatch()` 中加入分支；
2. 明确是否要求项目、是否要求空闲、是否允许任务运行中调用；
3. 参数校验失败用 `ValueError`，忙碌/状态冲突用 `RuntimeError`；
4. 返回可 JSON 序列化的普通结构（`dataclasses.asdict` 或 dict/list）；
5. 更新本文方法表；
6. 在 `tests/test_bridge.py` 或对应测试中加入协议级测试。

避免在 `dispatch` 中直接 `print`；需要日志时写 stderr 或事件。

---

## 9. 相关文档

- [架构总览](./02-architecture.md)
- [WPF 桌面端](./10-desktop-client.md)
- [故障排查](./13-troubleshooting.md)