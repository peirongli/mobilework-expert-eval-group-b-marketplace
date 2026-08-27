# 复现文档（B 组）

从零复现 B 组 MobileWork 专家评测全流程的完整步骤。

## 1. 环境准备

```bash
# 安装 Node.js 22 + Python 3.13（或使用 WorkBuddy 托管版本）
export PATH="/Users/lipeirong/.workbuddy/binaries/node/versions/22.22.2/bin:$PATH"
# Python venv
python3 -m venv ~/.workbuddy/binaries/python/envs/mobilework-eval
pip install pyyaml jsonschema
```

详见 `eval/ENVIRONMENT.md` 的软件版本矩阵。

## 2. Claude Code Marketplace 验证

```bash
git clone https://github.com/peirongli/mobilework-expert-eval-group-b-marketplace.git
cd mobilework-expert-eval-group-b-marketplace
claude plugin validate ./plugins/group-b-expert-eval --strict
# CI 自动验证 marketplace.json + 禁止内嵌 manager + new_case.py 冒烟
```

## 3. OpenWork 导入两个插件

在 OpenWork Desktop (0.17.24) 中：

1. **公共 manager**：Settings → Extensions → Install from GitHub
   - URL: `https://github.com/xiaodong528/mobilework-expert-manager/tree/917a200804cf56ccf67e1c405b22caf710d78eb1`
   - Preview → 核对 owner=xiaodong528, ref=冻结 SHA → Install → Refresh

2. **B 组插件**：同上
   - URL: `https://github.com/peirongli/mobilework-expert-eval-group-b-marketplace/tree/v0.3.1/plugins/group-b-expert-eval`
   - Preview → 核对 owner=peirongli, tag=v0.3.1 → Install → Refresh

3. 在扩展列表中确认两个插件均已安装。

## 4. 发起评测

从新的 OpenWork 对话：

```
请用 group-b-expert-eval 对 tech-digest-team 跑 td-01 case
```

或通过 CLI 直接调用：

```bash
cd /Users/lipeirong/Desktop/MobileWork
python3 repos/.../run_case.py --case td-01 --run-kind formal
```

## 5. 查看结果

```bash
# 重建本地 Web
python3 eval/web/build.py
# 在浏览器打开 eval/web/index.html
```

## 6. 生成优化副本

从 OpenWork 对话调用公共 manager（create_expert.py），生成优化副本 v1.1.0。
详见 `eval/ENVIRONMENT.md` 七.2 被测对象快照。

## 7. 复测

```bash
python3 run_case.py --case td-01 --variant optimized --run-kind formal
```

## 8. 80 次批量运行

```bash
python3 eval/scripts/batch_run.py --run-kind formal --resume
```

## 9. CR-01/02 批量 F1 评分

```bash
python3 eval/scripts/batch_score.py
```

## 10. 跨组复测

其他组导入 B 组插件（v0.3.1 子目录 URL），复现至少 1 个新 case。
ENVIRONMENT.md 七.3 有完整复现命令。
