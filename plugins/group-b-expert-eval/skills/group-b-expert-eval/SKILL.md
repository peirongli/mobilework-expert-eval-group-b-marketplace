---
name: group-b-expert-eval
description: >-
  B 组 MobileWork 专家（团）评测与优化入口。当用户要求选择被测对象、配置 case、
  发起基线运行、查看证据与评分、提交逐 case 人工建议、生成优化副本或复测时使用。
  依赖公共插件 mobilework-expert-manager 完成优化副本的生成与校验。
---

# Group B 专家（团）评测优化插件

面向 OpenWork 对话的评测全流程入口。固定运行边界：
OpenWork 对话 → 本插件 → 真实 OpenCode 专家（团）→ Promptfoo → 本地结果 Web →
mobilework-expert-manager 优化副本 → 同条件复测。

## 当前状态（Week 1 骨架）

已可用：
- `scripts/new_case.py`：按任务书 6.3 要素创建 case 定义文件（任务目标、输入、环境、
  期望证据、评分方式、主指标、异常判定）。

进行中（Week 2+，勿在未实现前声称可用）：
- OpenCode 真实运行编排（opencode:sdk provider，冻结模型与权限）
- Promptfoo 断言/rubric 评判与结果落盘
- 统一证据链（主/子会话、工具、权限、产物、耗时、异常、token/成本）
- 本地结果 Web（只读查看，不提供第二执行入口）
- 调用公共 mobilework-expert-manager 生成/校验优化副本并复测

## 使用约定

- 原始专家包全程只读；优化副本必须带版本标识并保留生成/差异/校验证据。
- 正式运行只从 OpenWork 新会话发起；异常运行不进入正式统计。
- 评测方法匹配任务性质：结构化任务用确定性断言，混合任务硬约束断言 + 质量 rubric，
  开放任务用明确 rubric + 模型裁判/人工复核。
- 凭证只从环境或本机凭证存储读取，任何密钥不得写入本仓库文件。
