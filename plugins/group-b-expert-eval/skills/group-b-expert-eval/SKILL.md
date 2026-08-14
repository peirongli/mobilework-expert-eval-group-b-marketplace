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

## 能力与用法（2026-08-14 起，经 TD-01 实测）

两个脚本（`scripts/`，评测工作区默认 `~/Desktop/MobileWork/eval`，可用
`MOBILEWORK_EVAL_ROOT` 覆盖）：

1. `new_case.py`：按任务书 6.3 要素创建 case 定义文件。
2. `run_case.py`：发起一次被测专家运行并自动归档证据链。一条命令完成：
   - 预检：F3 overlay（writer/researcher bash+external_directory allow）、
     被测包相对 v1.0.0 tag 只读门（diff 非空即中止）、DeepSeek 凭证、CLI 可用
   - 运行：`opencode run --auto -m <model> --agent <agent>`（冻结模型，
     默认 deepseek/deepseek-v4-pro）
   - 回采：从 opencode.db 提取本次运行真实 `ses_` 主/子会话 ID（按 directory
     + 起始时间戳过滤，主会话 parent_id IS NULL），杜绝占位符
   - 归档：交付物、run 日志、promptfoo 离线评分（TD 系列；复用基线评分配置，
     断言明细从 gradingResult.componentResults **自动转录**进 meta.json）
     或 CR seeded match 草稿（CR-01/02，待人工裁决后跑 score 步骤）
   - 生成 schema 合规 meta.json 并跑 `schema/validate.py`

   用法：
   ```
   python run_case.py --case td-01 --run-kind pilot            # 全流程
   python run_case.py --case td-01 --label run2                # 同 case 多次运行
   python run_case.py --case td-01 --score-only --deliverable <path>
   python run_case.py --case td-01 --run-kind control-model --model deepseek/deepseek-v4-flash
   ```

   已注册 case：td-01~04（tech-digest-team）、cr-01~04（code-review-expert）。

尚未覆盖（诚实声明）：
- 优化副本生成仍由人调用公共 mobilework-expert-manager 完成，本插件负责
  发起复测与证据落盘（第 6 周接入）。
- 80 次 formal 统计的批量编排（当前逐次发起，`--label` 区分）。
- 本地结果 Web 重建需在 eval 工作区手动执行 `eval/web/build.py`。

## 使用约定

- 原始专家包全程只读；优化副本必须带版本标识并保留生成/差异/校验证据。
- 正式运行只从 OpenWork 新会话发起；异常运行不进入正式统计。
- 评测方法匹配任务性质：结构化任务用确定性断言，混合任务硬约束断言 + 质量 rubric，
  开放任务用明确 rubric + 模型裁判/人工复核。
- 凭证只从环境或本机凭证存储读取，任何密钥不得写入本仓库文件。
