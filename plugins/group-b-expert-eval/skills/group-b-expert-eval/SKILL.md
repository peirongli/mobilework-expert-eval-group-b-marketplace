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
   python run_case.py --case td-01 --run-kind pilot            # 全流程（基线）
   python run_case.py --case td-01 --variant optimized          # 优化副本复测
   python run_case.py --case td-01 --label run2                 # 同 case 多次运行
   python run_case.py --case td-01 --score-only --deliverable <path>
   python run_case.py --case td-01 --run-kind control-model --model deepseek/deepseek-v4-flash
   ```

   `--variant`（2026-08-19 起）：`baseline`（默认，原包 v1.0.0）或 `optimized`（副本 v1.1.0，TD 系列自动打 F3 overlay）。
   opt 包跳过 git 只读门（改为检查 expert.json 存在）；run 目录自动加 `-opt` 前缀。

   已注册 case：td-01~04（tech-digest-team）、cr-01~04（code-review-expert）。

3. `batch_run.py`（2026-08-19 起，`eval/scripts/`）：80 次正式批量编排。
   循环 8 case × 2 variant × 5 次，`run_kind=formal`，异常自动补跑（`--max-retries`），
   超时 1800s/次，跑完自动 `diagnose --diff baseline vs optimized`。
   ```
   python eval/scripts/batch_run.py                           # 跑全部 80 次
   python eval/scripts/batch_run.py --cases td-01,cr-04       # 只跑指定 case
   python eval/scripts/batch_run.py --dry-run                  # 只打印计划
   python eval/scripts/batch_run.py --resume                   # 跳过已完成的 run 目录
   ```

尚未覆盖（诚实声明）：
- 优化副本**生成**仍由人调用公共 mobilework-expert-manager 完成（create_expert.py），
  本插件负责发起**复测**与证据落盘（`--variant optimized` 已脚本化，第 6 周验证）。
- CR-01/02 的 F1 评分含人工裁决环节（finding↔EXPECTED 匹配）：
  run_case.py 自动生成 `score-match-draft.json` 草稿，人工复核后写 `score-final.json`。
- 本地结果 Web 重建需在 eval 工作区手动执行 `eval/web/build.py`。

## 使用约定

- 原始专家包全程只读；优化副本必须带版本标识并保留生成/差异/校验证据。
- 正式运行只从 OpenWork 新会话发起；异常运行不进入正式统计。
- 评测方法匹配任务性质：结构化任务用确定性断言，混合任务硬约束断言 + 质量 rubric，
  开放任务用明确 rubric + 模型裁判/人工复核。
- 凭证只从环境或本机凭证存储读取，任何密钥不得写入本仓库文件。
