# 术语表

| 术语 | 英文/代码 | 含义 |
| --- | --- | --- |
| 项目 | Project | 一个包含 `Main/`、`Main_labels/`、`Config/`、`Model/`、`runs/` 的目录 |
| 素材 | image / sample | 项目中的一张图片或视频帧 |
| 批次 | batch | 一次导入或一次视频结果导入的样本集合；划分时整组同 split |
| 分组 | group | 视频/批次/单图的聚合单位；划分的最小不可拆单元 |
| 复核 | review / confirm | 明确接受一张图片的标注（包括空标注）；只有 confirmed 进数据集 |
| 拒绝 | reject | 标记样本不可用并记录原因 |
| 旧样本 | legacy | 复核台账中无记录的样本；数据集创建时允许入选 |
| 标注文档 | `.annotation.json` | schema 2 的权威标注文件，像素坐标、revision、对象 ID |
| 投影 | projection | 由权威文档生成的 `.txt`/`.mark`/`.segments.json` 兼容文件 |
| 同步日志 | `.sync.json` | 标注保存/修复用的 journal |
| 几何指纹 | geometry fingerprint | `.txt/.mark/.segments.json/.annotation.json` 的 SHA256 组合，用于复核失效判断 |
| 数据集版本 | dataset version | 不可变的训练数据快照，位于 `<项目>_dataset/versions/<version>` |
| 激活版本 | active version | `active.json` 指向的版本；训练默认使用 |
| 清单 | manifest | `dataset_manifest.json` 或 `frame_manifest.json` |
| 泄漏 | leakage | 同组近邻帧或基准集图片同时出现在训练集与验证集 |
| 基准集 | golden set | 冻结的发布验收数据；整合时进入黑名单并固定到 val |
| 发布门禁 | release gate | 发布前的类别/泄漏/mAP/量化检查 |
| 实验 | experiment | 一次训练运行，记录在 `Model/experiments.jsonl` |
| 运行目录 | run directory | `runs/<kind>_<时间戳>_<随机串>`，含任务输入/事件/日志/产物 |
| Worker | worker | 独立子进程，执行训练/推理/导出等重任务 |
| 桥接 | bridge | 常驻 Python 进程，通过 JSONL stdio 暴露 RPC |
| 任务 | task | 一次后台操作，`kind` 决定执行方法 |
| 控制命令 | control | 写入 `control.json` 的跟踪暂停/恢复/纠偏等命令 |
| 暂停令牌 | pause_token | 跟踪暂停会话的随机令牌，防止过期命令提交 |
| 关键帧 | keyframe | 人工修正并提交的跟踪帧，用于后续重新初始化 |
| 回填 | backfill | 把连续跟踪结果写回已有抽帧图片 |
| 终身目标 ID | target_id | 跟踪任务内 0–31 的目标编号，结束后不可复用 |
| 轮廓 | polygon | 归一化多边形环，用于实例分割 |
| 孔洞 | hole | 多边形内部的挖空环 |
| ROI | region of interest | 限定框/轮廓/分割的矩形区域 |
| SAM | Segment Anything Model | 交互式分割模型 |
| SAM2 | SAM 2 | 视频跟踪/分割模型，本项目固定 ultralytics 8.4.161 |
| 抽帧 | extract | 按帧间隔或时间间隔从视频导出图片 |
| VFR | variable frame rate | 可变帧率；时间戳可能不单调，抽帧会拒绝不可靠输入 |
| ONNX | Open Neural Network Exchange | 跨平台模型格式 |
| OpenVINO | — | Intel 推理运行时/格式 |
| TensorRT | — | NVIDIA 推理引擎；engine 与机器绑定 |
| INT8 / FP16 / FP32 | — | 量化/半精度/单精度 |
| mAP50 | mean Average Precision @ IoU 0.5 | 目标检测指标 |
| AP50 | per-class AP @ IoU 0.5 | 逐类指标；门禁比较跌幅 |
| 量化掉点 | quantization drop | 量化模型相对浮点模型的 AP 下降 |
| 基线模型 | baseline | 上一版模型，用于逐类对比 |
| DDP | Distributed Data Parallel | Ultralytics 多卡训练；入口需支持 `-m` 分发 |
| CRT | C Runtime | Windows VC++ 运行库；torch `c10.dll` 依赖 |
| 冻结后端 | frozen backend | PyInstaller 打包的 `backend.exe` |
| 自包含发布 | self-contained | .NET 发布时携带运行时，无需目标机安装 .NET |
| DIP | Device Independent Pixel | WPF 逻辑像素；画布坐标单位 |
| EXIF 方向 | orientation 1–8 | 图片旋转/镜像元数据；标注始终保存原始像素 |
| 原子写入 | atomic write | 临时文件 + fsync + `os.replace`，防止半写 |
| 分阶段提交 | staging | 先写临时目录，校验后原子改名 |
| BLOCK / WARN | — | 整合计划中的阻断项/警告项 |
| 类别别名 | class alias | `classes_alias.json` 中记住的类别映射 |

---

返回 [文档中心](./README.md)。