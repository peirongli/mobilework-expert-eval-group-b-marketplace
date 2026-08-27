# mobilework-expert-eval-group-b-marketplace

2026 SWARM · MobileWork 专家（团）评测优化课题 **B 组** Claude Code Marketplace 仓库。

通用评测优化插件 `group-b-expert-eval`：从 OpenWork 对话驱动真实 OpenCode 专家（团），
经 Promptfoo 评判、统一证据链、本地结果 Web，直至依据证据生成优化副本并复测的完整闭环。
不绑定特定领域对象——不同类型/应用场景的专家包可按三步接入评测。

## 成果速览（第 7 周，80 次正式基准）

| 指标 | 结果 |
|---|---|
| 正式运行 | **80 次**（8 case × 基线/优化 × 5 次，run_kind=formal，schema 全过） |
| 可重复提升 | 单专家 CR-02 检出 F1 `0.973 → 1.000`（5/5 全 1.0，超出运行方差） |
| 不退化核验 | 7/8 case 保持或提升；专家团 TD 系列唯一波动项 td-01 已归因为运行间方差并有证据解释 |
| F1 护栏 | CR-01 高严重度召回 4/4、CR-02 安全召回 5/5，全部 ≥ 口径 |
| 异常处置 | F2 流式挂起 ~7% 触发自动补跑；四类归因登记 findings.json |

## 被测对象与 case 集（8 个）

| 对象 | 类型 | Case | 主指标 |
|---|---|---|---|
| tech-digest-team | 专家团（团长+researcher/writer） | td-01 简报 / td-02 周报 / td-03 选型调研 / td-04 开放调研 | 断言通过率 |
| code-review-expert | 单专家 | cr-01 预埋 Python / cr-02 预埋 JS 安全 / cr-03 真实代码 / cr-04 开放多文件 | 检出 F1 |

任务类型覆盖结构化 / 混合式 / 开放式三类；另有不同模型臂（v4-flash）、
无专家臂两组对照演示（`eval/results/*control*/`）。

## 插件能力（`plugins/group-b-expert-eval/skills/group-b-expert-eval/scripts/`）

| 脚本 | 能力 |
|---|---|
| `new_case.py` | 创建 case 定义文件 |
| `run_case.py` | 单次运行全流程：预检（overlay/只读门/凭证）→ opencode 真实会话 → 会话回采 → Promptfoo 离线评分 → schema 合规 meta 归档；支持 `--variant optimized` 复测优化副本 |
| `batch_run.py` * | 80 次批量编排（`--resume` 断点续跑、异常自动补跑） |
| `batch_score.py` * | CR-01/02 的 seeded-match F1 批量自动裁决 |
| `build_web.py` | 结果 Web 生成 + `--serve` 本地部署（页面上直接提交逐 case 建议，G14 写回 advice.json）；Chart.js 本地仪表盘 |

\* 位于评测工作区 `eval/scripts/`（由 MOBILEWORK_EVAL_ROOT 定位），非本仓库直发。

### 本地结果 Web

五个视图：总览仪表盘（verdict 分布环形图、基线 vs 副本分组柱状、80 次运行矩阵热力格）·
运行记录（卡片/表格双模式 + 四维筛选）· 异常发现 · 优化前后对比（净效果徽章 + Δ 正负柱状 +
耗时对比图）· 人工建议。仅绑 127.0.0.1、无执行类端点，守住"Web 不是第二控制台"边界。

## 快速开始

### Claude Code 安装（开发/验证用）

```text
/plugin marketplace add peirongli/mobilework-expert-eval-group-b-marketplace
/plugin install mobilework-expert-manager@mobilework-expert-eval-group-b
/plugin install group-b-expert-eval@mobilework-expert-eval-group-b
/reload-plugins
```

```bash
claude plugin list --json
claude plugin details group-b-expert-eval@mobilework-expert-eval-group-b
```

### OpenWork 导入（验收路径，v0.3.6 子目录 URL）

1. 公共 manager（冻结 SHA）：
   `https://github.com/xiaodong528/mobilework-expert-manager/tree/917a200804cf56ccf67e1c405b22caf710d78eb1`
2. 本组插件：
   `https://github.com/peirongli/mobilework-expert-eval-group-b-marketplace/tree/v0.3.6/plugins/group-b-expert-eval`

均走 Settings → Extensions → Install from GitHub → Preview → Install → Refresh。

### 发起评测 / 复测 / 看结果

```bash
export PATH="<托管 node bin>:$PATH"
python <scripts>/run_case.py --case td-01 --run-kind formal          # 基线
python <scripts>/run_case.py --case td-01 --variant optimized        # 优化副本复测
python eval/scripts/batch_run.py --run-kind formal --resume          # 80 次批量
python <scripts>/build_web.py                                        # 重建结果页
```

完整复现步骤见 [docs/REPRODUCE.md](docs/REPRODUCE.md)。

## 仓库结构

```text
.claude-plugin/marketplace.json     # 市场登记：本组插件 + 公共 manager GitHub source
plugins/group-b-expert-eval/        # 本组评测优化插件
  .claude-plugin/plugin.json
  skills/group-b-expert-eval/
    SKILL.md                        # agent 使用说明（触发话术 / 接入新对象三步指引）
    scripts/                        # new_case / run_case / build_web (+ vendored Chart.js)
docs/
  REPRODUCE.md                      # 从零复现全流程步骤
  GOVERNANCE.md                     # 治理规则
.github/workflows/validate.yml      # CI：marketplace 校验 + plugin validate --strict + 冒烟测试
```

## 版本历史

| Tag | 内容 |
|---|---|
| v0.1.0 | 插件骨架 |
| v0.2.0 | run_case.py 运行编排落地（PR #1） |
| v0.3.0 | `--variant` 支持优化副本复测 |
| v0.3.1 | 版本双处同步修复 + SKILL/ENVIRONMENT 文档 |
| v0.3.2 | build_web.py 前端进插件（agent 调起）+ 新对象接入指引 |
| v0.3.3 | `--serve` 本地部署 + G14 建议页上提交写回 + 筛选与自由配对 |
| v0.3.4 | Chart.js 本地仪表盘 + 80 次运行矩阵热力格 + 对比徽章汇总 |
| v0.3.5 | 运行记录表格/卡片双视图 + Δ 通过率正负柱状 + 耗时对比图 |
| v0.3.6 | case-001（W2 链路验证）归档出正式视图，runs 口径收敛至正式 8 case |

## 治理摘要

- `main` 只经 PR 合入；功能分支短命，命名 `feat/<topic>`、`fix/<topic>`；
  PR 需 CI 全绿（单人项目期间 review 由 commit 说明补偿记录）。
- release 打 tag 并附变更说明；OpenWork 导入只引用 tag 子目录 URL。
- 详见 [docs/GOVERNANCE.md](docs/GOVERNANCE.md)。

## 许可证

本仓库代码以 [MIT](LICENSE) 发布。公共 `mobilework-expert-manager` 为 Apache-2.0，
由其原仓库分发，本仓库仅引用。
