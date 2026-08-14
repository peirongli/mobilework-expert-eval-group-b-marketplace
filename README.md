# mobilework-expert-eval-group-b-marketplace

2026 SWARM · MobileWork 专家（团）评测优化课题 **B 组** Claude Code Marketplace 仓库。

- Marketplace 名：`mobilework-expert-eval-group-b`
- 本组插件：`group-b-expert-eval`（相对路径 `./plugins/group-b-expert-eval`）
- 公共引用：`xiaodong528/mobilework-expert-manager`（GitHub source，**本仓库不复制其内容**）

## 仓库结构

```text
.claude-plugin/marketplace.json     # 市场登记：本组插件 + 公共 manager GitHub source
plugins/group-b-expert-eval/        # 本组评测优化插件
  .claude-plugin/plugin.json
  skills/group-b-expert-eval/       # 评测流程入口 skill（含 scripts/）
  commands/                         # OpenWork/Claude Code 斜杠命令
.github/workflows/validate.yml      # CI：marketplace 校验 + 插件 validate + 脚本测试
docs/                               # 治理与流程文档
```

## Claude Code 安装（开发/验证用）

```text
/plugin marketplace add peirongli/mobilework-expert-eval-group-b-marketplace
/plugin install mobilework-expert-manager@mobilework-expert-eval-group-b
/plugin install group-b-expert-eval@mobilework-expert-eval-group-b
/reload-plugins
```

安装后核对：

```bash
claude plugin list --json
claude plugin details mobilework-expert-manager@mobilework-expert-eval-group-b
claude plugin details group-b-expert-eval@mobilework-expert-eval-group-b
```

`mobilework-expert-manager` 的来源必须显示为 `xiaodong528/mobilework-expert-manager`。

## OpenWork 导入（验收路径）

两个插件分别导入，均走 Settings → Extensions → Install from GitHub → Preview → Install → Refresh：

1. 公共 manager（冻结 SHA）：

   ```text
   https://github.com/xiaodong528/mobilework-expert-manager/tree/917a200804cf56ccf67e1c405b22caf710d78eb1
   ```

2. 本组插件（release tag `v0.2.0` 的子目录）：

   ```text
   https://github.com/peirongli/mobilework-expert-eval-group-b-marketplace/tree/v0.2.0/plugins/group-b-expert-eval
   ```

Preview 需核对：owner/repo、ref、`plugins/group-b-expert-eval` 子目录、组件清单与 warning。

## 治理摘要

- `main` 受保护：只经 PR 合入；功能分支短命，命名 `feat/<topic>`、`fix/<topic>`。
- PR 需 CI 全绿 + 至少 1 名组员 review；合并用 squash。
- release 打 tag（`vX.Y.Z`）并附变更说明；OpenWork 导入只引用 tag 子目录 URL。
- 详见 [docs/GOVERNANCE.md](docs/GOVERNANCE.md)。

## 许可证

本仓库代码以 [MIT](LICENSE) 发布。公共 `mobilework-expert-manager` 为 Apache-2.0，
由其原仓库分发，本仓库仅引用。
