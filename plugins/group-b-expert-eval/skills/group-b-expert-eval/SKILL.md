---
name: group-b-expert-eval
description: >-
  B 组 MobileWork 专家（团）评测与优化入口（通用插件）。当用户要求选择被测对象、
  配置 case、创建新专家包、发起基线运行、查看证据与评分、重建结果 Web、提交逐 case
  人工建议、生成优化副本或复测时使用。
  依赖公共插件 mobilework-expert-manager 完成专家包创建/优化副本的生成与校验。
---

# Group B 专家（团）评测优化插件

面向 OpenWork 对话的评测全流程入口（通用：不绑定特定领域对象）。固定运行边界：
OpenWork 对话 → 本插件 → 真实 OpenCode 专家（团）→ Promptfoo → 本地结果 Web →
mobilework-expert-manager 创建/优化副本 → 同条件复测。
**全流程由 agent 在对话中调起脚本完成，用户无需切换终端。**

## 能力与用法（2026-08-27 更新，80 次 formal 实测验证）

四个脚本（`scripts/`，评测工作区默认 `~/Desktop/MobileWork/eval`，可用
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

4. `batch_score.py` / `batch_run.py`（`eval/scripts/`，W7 落地）：
   - `batch_run.py`：80 次正式批量编排（8 case × 2 variant × 5 次，
     run_kind=formal，异常自动补跑，跑完自动 diagnose --diff）。
     **长运行须在终端执行**（编排器内含交互式预检，不适合对话内阻塞等待）：
     `python eval/scripts/batch_run.py --run-kind formal --resume`
   - `batch_score.py`：CR-01/02 的 F1 批量评分（blocked→pass/fail 自动裁决）
5. `build_web.py`（2026-08-27 起，本插件内）：**结果 Web 由 agent 直接调起生成**。
   用户说"查看结果 / 重建报告页 / 看看评测数据"时调用：
   ```
   python <scripts>/build_web.py                     # 静态模式：生成后 file:// 打开
   python <scripts>/build_web.py --accent "#0052d9"  # 换主题色
   python build_web.py --title "自定义标题"           # 换标题
   python build_web.py --serve [--port 8763]         # 本地部署模式（可交互）
   ```
   交互能力（--serve 模式，仅绑 127.0.0.1）：
   - 运行记录按 case/变体/结论/关键词筛选；
   - 对比视图可任选两次运行自由配对做断言级 diff；
   - 页面上直接**提交逐 case 建议**（G14），追加写回 advice.json——
     **原始运行证据永不改写，无任何发起运行类端点**（任务书 §3.2 红线）。
   agent 应将 `http://127.0.0.1:<port>/` 给用户在浏览器打开；任务结束提醒用户
   Ctrl+C 或由 agent 停止进程。静态模式下提交按钮自动禁用并提示改用 --serve。
   **AI 自由填写前端模板**：HTML/CSS 模板即脚本内的 TEMPLATE 字符串——
   agent 可按用户要求直接编辑该段定制布局/配色/卡片/图表，保存后重新调起生效。

## 接入新被测对象（低门槛创建，对话式）

不同类型/应用场景的专家（团）接入评测只需三步，全部可由 agent 在对话中引导完成：

1. **创建专家包**：引导用户从 OpenWork 对话调用公共 mobilework-expert-manager
   （`create_expert.py`），人工整理 expert.json 后生成派生产物并校验；
2. **注册 case**：用本插件 `new_case.py` 创建 case 定义文件，并在
   `run_case.py` 的 case 注册表登记任务输入与评分方式（结构化=断言 /
   混合式=rubric+硬约束 / 开放式=rubric+人工复核）；
3. **跑基线**：`run_case.py --case <new-case> --run-kind pilot` 验证全链路，
   再进入正式统计。评分配置复用同领域模板或按 case 类型新建。

尚未覆盖（诚实声明）：
- 优化副本**生成**仍由人主导调用公共 mobilework-expert-manager 完成（create_expert.py），
  本插件负责发起**复测**与证据落盘（`--variant optimized` 已脚本化）。
- CR-01/02 类 seeded case 的 F1 评分草稿由 run_case.py 自动生成，
  终稿裁决已由 `batch_score.py` 自动化（额外发现标 valid_extra 不计 fp）。

## 使用约定

- 原始专家包全程只读；优化副本必须带版本标识并保留生成/差异/校验证据。
- 正式运行只从 OpenWork 新会话发起；异常运行不进入正式统计。
- 评测方法匹配任务性质：结构化任务用确定性断言，混合任务硬约束断言 + 质量 rubric，
  开放任务用明确 rubric + 模型裁判/人工复核。
- 凭证只从环境或本机凭证存储读取，任何密钥不得写入本仓库文件。
