# 安全策略 / Security Policy

## 支持的版本 / Supported Versions

Label Once 以单主干（`main`）方式发布，安全修复只针对最新发布 tag 提供。
请始终升级到最新版本后再报告问题。

| 版本 | 支持状态 |
| --- | --- |
| 最新 tag | ✅ 接收安全修复 |
| 更早 tag | ❌ 请升级 |

## 报告漏洞 / Reporting a Vulnerability

**请不要在公开 Issue 中披露未修复的安全问题。**

优先通过 GitHub 的私密漏洞报告（Security → Report a vulnerability）提交，
或在 Issue 中仅描述“存在潜在安全问题”而不附细节，等维护者联系你。

报告时请尽量包含：

- 受影响组件与版本（后端 `studio/`、桥接协议、WPF 客户端、打包脚本）；
- 复现步骤或概念验证；
- 影响范围（本地代码执行、任意文件读写、数据泄露、模型资产篡改等）；
- 是否需要特定环境（GPU、特定 Windows 版本、特定模型格式）。

## 重点风险面 / Key Attack Surfaces

Label Once 是本地桌面应用，典型威胁模型是“处理不可信的项目数据/模型权重”。
审阅与报告时请特别关注：

- **桥接协议（stdio JSONL）**：`studio/bridge.py`、`studio/service.py`。
  后端不得把日志写到 stdout（会破坏 JSONL 帧边界）；所有协议方法必须校验参数，
  尤其是项目路径与图片名（防路径穿越，见 `service.require`/`image`）。
- **模型权重反序列化**：加载 `.pt`/`.onnx`/`.engine` 等权重等同于执行其内容。
  不要自动加载未受信来源的权重；`torch.load` 相关路径注意 `weights_only`。
- **数据集/项目文件**：`dataset.yaml`、sidecar JSON、类别表来自磁盘，解析需容错，
  不得因恶意字段触发任意写入到项目目录之外。
- **打包产物**：`scripts/` 下打包脚本与 PyInstaller spec；不要把本地路径、
  凭据或权重打包进发布物。
- **进程管理**：`studio/processes.py` 启动子进程，注意命令注入与强制结束的孤儿进程。

## 修复流程 / Remediation Flow

1. 维护者确认漏洞并评估影响范围与版本；
2. 在私有分支修复，补充回归测试（优先放入 `tests/` 或 `LabelOnce.Core.Tests`）；
3. 发布修复版本并在 Release Note 说明（细节按严重程度决定是否延迟披露）；
4. 严重问题同步更新 [故障排查](./13-troubleshooting.md) 与相关文档。

## 加固建议 / Hardening Notes

- 把权重、数据集、模型目录放在项目目录内，避免跨项目软链；
- 不要以管理员权限运行应用；
- 从可信来源获取模型权重，交付前用[发布门禁](./08-release-gate.md)校验资产；
- CI 中不要把重型 ML 运行时和凭据引入主测试作业（见 [构建、打包与 CI](./11-build-release-ci.md)）。

---

## Contributing a fix

请先阅读 [贡献指南](./contributing.md)，修复请附带回归测试，
并确认 `python -m pytest -q`、`ruff`、`mypy` 与 `dotnet test` 全部通过。
