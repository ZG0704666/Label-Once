# 参与贡献

欢迎提交 Issue、Fork 和 Pull Request。本文说明代码风格、测试要求、文档同步和提交前检查。

---

## 1. 开发环境

```powershell
./scripts/install.ps1
./desktop/scripts/start.ps1
```

- Python 3.10 x64；
- .NET 10 SDK；
- 可选 NVIDIA GPU；
- 模型权重放 `models/`、`sam/`，不要提交。

---

## 2. 分支与提交

- 从 `main` 创建功能分支；
- 一次 PR 只做一件事，避免混合重构与功能；
- 提交信息建议使用“范围: 动作”格式，例如：

```text
ci: 移除测试对 ultralytics/torch 的依赖
fix: 续训时保留原运行目录
docs: 新增文档中心与数据格式说明
```

- 不提交：模型权重、数据集、`Release/`、`dist/`、`build/`、缓存、日志、训练产物、本地标注副产物。

`.gitignore` 已覆盖主要规则；提交前执行：

```powershell
git status --short
```

---

## 3. 代码约定

### Python

- 目标版本 3.10；
- 公共逻辑放 `studio/`，GUI 相关放 `app.py`/`canvas.py` 等；
- `service.py`/`bridge.py` 不导入 Qt；
- 重型依赖（torch/ultralytics）在任务方法内延迟导入；
- 文件写入使用 `atomic_write`/`save_json`；
- 用户可见错误使用中文 `ValueError`/`RuntimeError`；
- 不要把日志写到 stdout（会破坏 JSONL 协议）。

### C# / WPF

- `LabelOnce.Core` 保持无 UI 依赖，便于测试；
- ViewModel 通过 `BridgeClient.Call` 调用后端；
- 新增 UI 操作时同时考虑忙碌状态、取消、错误提示；
- 坐标转换统一走 `Viewport`，不要在控件里手写 EXIF 逻辑。

### 数据与协议

- 数据集版本不可变；
- 类别只追加，不移动既有 ID；
- 新增协议方法必须校验参数并更新 [桥接协议](./09-bridge-protocol.md)；
- 新增 sidecar/格式变更必须考虑旧项目兼容与恢复。

---

## 4. 测试

提交前至少运行：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
dotnet run --project desktop/LabelOnce.Core.Tests -c Release
```

涉及 WPF 交互时，再运行 [WPF 成品验收](./WPF_ACCEPTANCE.md) 或 `test-desktop.ps1`。

测试原则：

- 单元测试不依赖真实模型/GPU；
- 需要模型时用假对象或 `sys.modules` 注入；
- 文件格式改动覆盖旧格式读取、往返、冲突/中断恢复；
- 划分改动覆盖“同组同 split”和确定性；
- 协议改动覆盖请求/响应/错误帧。

详见 [测试与验收](./12-testing.md)。

---

## 5. 文档

- 文档中心位于 `docs/`，入口 [docs/README.md](./README.md)；
- 功能/接口/命令变化时同步更新对应页面；
- 新增文档需加入文档中心索引；
- 构建脚本会复制 `docs/` 下的 `ANNOTATION_TO_TRAINING.md`、`DATASET_MERGE.md`、`PROGRESSIVE_WORKFLOWS.md`、`WPF_ACCEPTANCE.md`，不要随意重命名；
- 截图放 `docs/screenshots/`，注意隐藏本地路径、API Key、个人信息和未发布模型。

---

## 6. CI

GitHub Actions 工作流：`.github/workflows/ci.yml`。

- `python-tests`：Python 3.10 + 轻量依赖 + `pytest -q`；
- `dotnet-build`：`dotnet restore/build LabelOnce.sln -c Release`；
- `package-windows`：tag/手动触发时发布 WPF 并上传 artifact。

PR 合并前应确保两个基础作业通过。若修改测试依赖，请先阅读 [构建、打包与 CI](./11-build-release-ci.md) 中关于 torch DLL 的说明，不要把重型 ML 运行时重新加回主测试作业。

---

## 7. PR 检查清单

- [ ] 功能/修复有对应测试，或说明为何不需要；
- [ ] Python 测试通过；
- [ ] .NET 构建/几何测试通过；
- [ ] 没有提交权重/数据/构建产物/日志；
- [ ] 文档已同步（尤其协议、命令、路径）；
- [ ] 错误信息对用户可理解；
- [ ] 不破坏旧项目格式与已有数据；
- [ ] 涉及 UI 的改动有截图或录屏；
- [ ] 说明验证环境（CPU/GPU、Windows 版本、模型）。

---

## 8. 报告问题

提交 Issue 时附上：

- 复现步骤与期望/实际行为；
- 完整错误栈；
- `python --version`、`dotnet --info`、`nvidia-smi`；
- 相关 `activity.log`、`process.log`、`events.jsonl`（脱敏）；
- 截图/录屏。

更多排查方法见 [故障排查](./13-troubleshooting.md)。