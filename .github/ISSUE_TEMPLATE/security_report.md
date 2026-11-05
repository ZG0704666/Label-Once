---
name: 安全问题 / Security report
about: 报告安全漏洞（请勿公开敏感细节） / Report a vulnerability (do not disclose sensitive detail)
labels: ["security"]
---

<!-- ⚠️ 重要：请不要在此公开未修复漏洞的可利用细节、PoC 或受影响数据。 -->
<!-- ⚠️ Important: do NOT publicly post exploitable detail, PoC, or affected data here. -->

## 请优先使用私密渠道 / Please prefer private disclosure

1. 首选 GitHub「Security → Report a vulnerability」私密报告；
2. 若只能用 Issue，请**只**写「存在潜在安全问题 + 联系方式」，等维护者私下联系；
3. 详见仓库根目录 [SECURITY.md](../../SECURITY.md)。

## 可以公开的信息 / What is safe to share

- 受影响组件（后端 `studio/` / 桥接协议 / WPF / 打包脚本）；
- 版本或 commit；
- 问题类别（路径穿越、任意文件写入、权重反序列化、进程注入等）；
- 严重程度的自评。

## 不要公开的信息 / Do not share publicly

- 可直接利用的复现步骤或代码；
- 受影响项目的真实路径、数据或模型资产；
- 任何凭据或个人信息。

## 联系方式 / Contact

<!-- 你的 GitHub 账号或邮箱，便于维护者私下跟进。 -->
