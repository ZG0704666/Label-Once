<!-- 提交 PR 前请逐项确认。/ Please confirm each item before opening a PR. -->

## 这个 PR 做了什么 / What does this PR do?

<!-- 一句话说明目的；一个 PR 只做一件事。 -->

## 变更类型 / Change type

- [ ] 功能 feature
- [ ] 修复 fix
- [ ] 重构 refactor（不改行为）
- [ ] 文档 docs
- [ ] CI / 构建
- [ ] 测试

## 验证 / Verification

<!-- 勾选你实际运行过的检查，并附关键输出或截图。 -->

- [ ] `python -m pytest -q` 通过
- [ ] `ruff check .` 通过
- [ ] `mypy studio --no-site-packages` 通过
- [ ] `python scripts/check_lock_sync.py` 通过（改过依赖时）
- [ ] `dotnet build desktop/LabelOnce.sln -c Release` 0 警告 0 错误
- [ ] `dotnet test desktop/LabelOnce.Core.Tests -c Release` 通过
- [ ] 涉及 WPF 交互：已按 `docs/WPF_ACCEPTANCE.md` 手工验收，并附截图/录屏

## 检查清单 / Checklist

- [ ] 一个 PR 只做一件事，不混合重构与功能
- [ ] 功能/修复有对应测试，或说明为何不需要
- [ ] 没有提交权重、数据集、`dist/`、`build/`、日志或训练产物
- [ ] 文档已同步（协议、命令、路径、测试说明等）
- [ ] 用户可见错误信息是可理解的中文
- [ ] 不破坏旧项目格式与已有数据；文件写入使用 `atomic_write`/`save_json`
- [ ] 后端未把日志写到 stdout（会破坏 JSONL 协议）
- [ ] 说明验证环境（CPU/GPU、Windows 版本、模型）
