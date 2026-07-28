# B 组仓库治理约定

## 分支

- `main`：受保护主干，始终保持可安装、CI 绿。
- 功能分支：`feat/<topic>`；修复分支：`fix/<topic>`；短命，合入后删除。
- 禁止直接向 `main` push（含组长）。

## PR

- 标题写清意图，描述含：变更点、验证方式、关联 issue/任务。
- 必需检查：CI `Validate` 全绿；至少 1 名非作者组员 approve。
- 合并方式：squash merge，保持 main 历史线性可读。
- 公共 manager 相关 PR 只能改 `marketplace.json` 的引用（repo/SHA），
  不得引入其文件复制件。

## 依赖与许可证

- 新依赖先在 PR 中说明用途与许可证；禁止引入与 MIT 不兼容的依赖。
- 公共 `mobilework-expert-manager`：Apache-2.0，仅以 GitHub source 引用。
- Promptfoo：MIT（0.121.19）；OpenCode/Claude Code 按其各自许可使用。

## 安全

- 任何密钥、token、`.env` 不得入库（`.gitignore` 已覆盖常见形态）；
  发现误提交立刻吊销并重写历史。
- 评测原始数据（会话、证据）不进本仓库；报告只放脱敏统计与结论。

## 发布

- 语义化版本：功能性变更 MINOR，修复 PATCH，破坏性 MAJOR（0.x 阶段从宽）。
- 发布物：tag `vX.Y.Z` + GitHub Release（变更说明 + 安装/导入说明）。
- 每次 release 后，由非发布者按 README 的 OpenWork 导入路径做一次干净环境安装验证。

## 贡献统计

- 代码、文档、评测、验证均计入个人贡献；commit 使用本人 GitHub 身份。
- 周评审前由组长汇总贡献记录（PR、review、case、运行证据）。
