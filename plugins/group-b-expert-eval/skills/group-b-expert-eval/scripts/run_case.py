#!/usr/bin/env python3
"""group-b-expert-eval：发起一次被测专家运行并自动归档证据链。

流程（对齐 eval/PLAN.md 与 HOWTO-expert-team.md）：
  1. 预检：F3 overlay 已打 / 被测包只读门 / DeepSeek 凭证 / CLI 可用
  2. 运行：opencode run --auto（真实专家/专家团，冻结模型）
  3. 回采：从 opencode.db 提取本次运行的真实 ses_ 会话 ID（主+子）
  4. 归档：交付物 + run 日志 + promptfoo 离线评分（或 CR seeded match 草稿）
  5. 生成 schema 合规 meta.json（断言自动转录，不再人工抄录）并校验

用法：
  python run_case.py --case td-01 --run-kind pilot
  python run_case.py --case td-01 --label run2 --model deepseek/deepseek-v4-pro
  python run_case.py --case td-01 --score-only --deliverable /path/to/digest.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_EVAL_ROOT = Path(os.environ.get(
    "MOBILEWORK_EVAL_ROOT", Path.home() / "Desktop/MobileWork/eval"))
OPENCODE_DB = Path(os.environ.get(
    "OPENCODE_DB", Path.home() / ".workbuddy/xdg/data/opencode/opencode.db"))
AUTH_JSON = Path(os.environ.get(
    "OPENCODE_AUTH", Path.home() / ".workbuddy/xdg/data/opencode/auth.json"))
NODE_BIN = "/Users/lipeirong/.workbuddy/binaries/node/versions/22.22.2/bin"

# 各 case 注册表：sut(name,type,version,commit) / ws / agent / prompt / deliverable
SUT_TD = ("tech-digest-team", "专家团", "1.0.0", "0da0eee")
SUT_CR = ("code-review-expert", "单专家", "1.0.0", "f7386f1")
SUT_TD_OPT = ("tech-digest-team-opt", "专家团", "1.1.0", "opt")
SUT_CR_OPT = ("code-review-expert-opt", "单专家", "1.1.0", "opt")
D = "{date}"
CASES = {
    "td-01": dict(sut=SUT_TD, ws="runs/ws-tech-digest", agent="chief-editor",
        prompt=f"帮我调研「端侧大模型推理优化」的最新进展，产出一份 600 字以内的简报。完成后把简报保存到工作区根目录 digest-{D}.md。",
        deliverable=f"digest-{D}.md"),
    "td-02": dict(sut=SUT_TD, ws="runs/ws-tech-digest", agent="chief-editor",
        prompt=f"给我一份「RAG 评测方法」的技术周报，栏目固定为：本周进展、方案对比（用表格）、风险、下周关注，800 字以内。完成后保存到工作区根目录 weekly-{D}.md。",
        deliverable=f"weekly-{D}.md"),
    "td-03": dict(sut=SUT_TD, ws="runs/ws-tech-digest", agent="chief-editor",
        prompt=f"我们要给一个日均百万级查询的知识库产品选向量数据库，候选 Milvus、Qdrant、pgvector。帮我做一份选型调研简报：给出对比维度表、明确推荐一个，并说明适用边界与风险。1500 字以内，保存为 selection-{D}.md。",
        deliverable=f"selection-{D}.md"),
    "td-04": dict(sut=SUT_TD, ws="runs/ws-tech-digest", agent="chief-editor",
        prompt=f"帮我调研「AI Agent 记忆机制」的最新进展，产出一份给技术管理者看的简报，篇幅自定（建议 1000 字左右）。保存为 agent-memory-{D}.md。",
        deliverable=f"agent-memory-{D}.md"),
    "cr-01": dict(sut=SUT_CR, ws="runs/ws-code-review", agent="code-review-expert",
        prompt="帮我评审 user_service.py，列出问题并给出修复建议。完成后把评审结果保存为 review-output.md。",
        deliverable="review-output.md"),
    "cr-02": dict(sut=SUT_CR, ws="runs/ws-code-review", agent="code-review-expert",
        prompt="审查 auth.js 的安全漏洞和性能问题，列出问题并给出修复建议。完成后把评审结果保存为 review-output.md。",
        deliverable="review-output.md"),
    "cr-03": dict(sut=SUT_CR, ws="runs/ws-code-review", agent="code-review-expert",
        prompt="评审 diagnose_expert.py 的可维护性，给出改进建议。注意：它 import 的同目录模块（archive_inspector 等）未提供，按真实项目片段处理。完成后把评审结果保存为 review-output.md。",
        deliverable="review-output.md"),
    "cr-04": dict(sut=SUT_CR, ws="runs/ws-code-review", agent="code-review-expert",
        prompt="mininote/ 是一个小工具的全部源码（__init__.py、parser.py、storage.py、cli.py），帮我做一次全面评审：找出问题、评估整体结构，给出重构建议。完成后把评审结果保存为 review-output.md。",
        deliverable="review-output.md"),
}
SUB_AGENT_HINTS = {"researcher": ("research", "调研"), "writer": ("writer", "撰稿", "撰写")}


def fail(msg: str) -> None:
    print(f"!! 预检失败：{msg}", file=sys.stderr)
    sys.exit(2)


def ok(msg: str) -> None:
    print(f"  ok  {msg}")


def resolve_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    for p in (AUTH_JSON, Path.home() / ".local/share/opencode/auth.json"):
        if p.exists():
            try:
                d = json.loads(p.read_text())
                k = ((d.get("deepseek") or {}).get("key")
                     or (d.get("deepseek") or {}).get("api_key")
                     or d.get("api_key"))
                if k:
                    return k
            except Exception:
                pass
    return ""


def preflight(eval_root: Path, case: str, spec: dict, need_run: bool) -> dict:
    print("== 预检 ==")
    ws = eval_root / spec["ws"]
    if not ws.is_dir():
        fail(f"工作区不存在：{ws}")
    ok(f"工作区 {ws.relative_to(eval_root)}")

    if spec["sut"][0] == "tech-digest-team":
        for ag in ("writer", "researcher"):
            f = ws / ".opencode/agent" / f"{ag}.md"
            if not f.exists():
                f = ws / ".opencode/agents" / f"{ag}.md"
            if not f.exists() or "allow" not in f.read_text():
                fail(f"F3-CLI overlay 未打/失效：{f} 不存在或无 allow 规则。"
                     "先按 HOWTO-expert-team.md F3 备忘重打 overlay 再运行。")
        ok("F3 overlay（writer/researcher bash+external_directory allow）")

    pkg = eval_root / "packages" / spec["sut"][0]
    if not pkg.is_dir():
        fail(f"被测包不存在：{pkg}")
    is_opt = spec["sut"][0].endswith("-opt")
    if is_opt:
        # opt 包：刚生成未 commit/tag，检查 expert.json 存在 + git init 已做
        if not (pkg / "expert.json").exists():
            fail(f"opt 包 expert.json 不存在：{pkg}")
        ok(f"opt 包 {spec['sut'][0]} expert.json 存在（未 commit/tag，允许）")
    else:
        # 原包：git status 空 + diff v<tag> 空
        tag = f"v{spec['sut'][2]}"
        r1 = subprocess.run(["git", "-C", str(pkg), "status", "--porcelain"],
                            capture_output=True, text=True)
        r2 = subprocess.run(["git", "-C", str(pkg), "diff", tag, "--stat"],
                            capture_output=True, text=True)
        if r1.stdout.strip() or r2.stdout.strip():
            fail(f"被测包只读门破坏：{spec['sut'][0]} 相对 {tag} 有改动或工作区脏")
        ok(f"被测包 {spec['sut'][0]}@{tag} 只读门（diff 为空）")

    key = resolve_key()
    if not key:
        fail("未找到 DeepSeek key（env DEEPSEEK_API_KEY 或 opencode auth.json）")
    ok("DeepSeek 凭证（auth.json/env）")

    env = dict(os.environ, PATH=NODE_BIN + os.pathsep + os.environ.get("PATH", ""))
    if need_run:
        for binname in ("opencode",):
            if shutil.which(binname, path=env["PATH"]) is None:
                fail(f"{binname} 不在 PATH（期望 {NODE_BIN}）")
        ok("opencode CLI")
    return {"key": key, "env": env, "ws": ws}


def run_opencode(spec: dict, ctx: dict, model: str, run_dir: Path,
                 timeout: int) -> dict:
    print("== 运行被测专家（opencode run --auto）==")
    start_ms = int(time.time() * 1000)
    cmd = ["opencode", "run", "--auto", "-m", model,
           "--agent", spec["agent"], spec["prompt"]]
    print(f"  cwd={ctx['ws'].name}  agent={spec['agent']}  model={model}")
    t0 = time.time()
    with open(run_dir / "run-output.log", "w") as fo, \
         open(run_dir / "run-stderr.log", "w") as fe:
        cp = subprocess.run(cmd, cwd=str(ctx["ws"]), stdout=fo, stderr=fe,
                            env=ctx["env"], timeout=timeout)
    duration = round(time.time() - t0, 1)
    print(f"  exit={cp.returncode}  duration={duration}s")
    if cp.returncode != 0:
        print("  !! 非零退出码，标记 blocked，请查 run-stderr.log", file=sys.stderr)
    return {"start_ms": start_ms, "duration": duration,
            "returncode": cp.returncode}


def harvest_sessions(ws: Path, start_ms: int) -> dict:
    """从 opencode.db 回采 start_ms 之后该 ws 的真实会话（主+子）。"""
    print("== 回采会话 ID（opencode.db）==")
    db = sqlite3.connect(str(OPENCODE_DB))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id,parent_id,title,time_created FROM session "
        "WHERE directory = ? AND time_created >= ? ORDER BY time_created",
        (str(ws), start_ms - 2000)).fetchall()
    rows = [r for r in rows]
    mains = [r for r in rows if r["parent_id"] is None]
    if not mains:
        print("  !! 未找到主会话（将无法回填 session 字段）", file=sys.stderr)
        return {"main": None, "subs": [], "side": []}
    main = mains[0]
    main_id = main["id"]
    subs = [r for r in rows if r["parent_id"] == main_id]
    side = mains[1:]
    ok(f"main={main['id'][:22]}…  subs={len(subs)}  side={len(side)}")
    return {"main": dict(main), "subs": [dict(r) for r in subs],
            "side": [dict(r) for r in side]}


def build_delegations(sessions: dict) -> list:
    """按子会话 title 线索映射 researcher/writer；映射不上的留在 sessions.sub。"""
    out = []
    for s in sessions["subs"]:
        t = (s.get("title") or "").lower()
        agent = None
        for name, hints in SUB_AGENT_HINTS.items():
            if any(h.lower() in t for h in hints):
                agent = name
                break
        if agent:
            out.append({"stage": "子代理委派", "agent": agent,
                        "session": s["id"]})
    return out


def locate_deliverable(ws: Path, pattern: str, start_ms: int, run_dir: Path,
                       explicit: str | None) -> str:
    if explicit:
        src = Path(explicit)
        if not src.is_file():
            fail(f"--deliverable 指定文件不存在：{src}")
    else:
        cands = [p for p in glob.glob(str(ws / pattern))
                 if Path(p).stat().st_mtime * 1000 >= start_ms - 60000]
        if not cands:
            fail(f"工作区未发现本次运行产出的交付物（{ws}/{pattern}）。"
                 "专家可能未落盘；查 run-output.log。")
        src = Path(max(cands, key=lambda p: Path(p).stat().st_mtime))
    dst = run_dir / src.name
    shutil.copy2(src, dst)
    ok(f"交付物 {src.name} -> {dst.name}")
    return src.name


def score_promptfoo(run_dir: Path, case: str, key: str, env: dict,
                    deliverable: str) -> dict | None:
    """复用基线归档的 promptfooconfig（改路径），评分并自动转录断言明细。"""
    tpl = DEFAULT_EVAL_ROOT / "results" / case / "promptfooconfig.yaml"
    if not tpl.exists():
        return None
    print("== 评分（promptfoo 离线）==")
    cfg = run_dir / "promptfooconfig.yaml"
    text = tpl.read_text()
    old_dir = str(tpl.parent)
    # 先扫描模板引用的本目录资产（如 wordcount_assert.py）并复制过来，再改路径
    for m in re.finditer(re.escape(old_dir) + r"/([\w.\-]+)", text):
        asset = tpl.parent / m.group(1)
        if asset.is_file() and not (run_dir / asset.name).exists():
            shutil.copy2(asset, run_dir / asset.name)
    text = text.replace(old_dir, str(run_dir))  # exec sut-output.sh / file:// 断言路径
    # 注入当前凭证（归档模板里的 key 可能已轮换）
    text = re.sub(r"apiKey: sk-[A-Za-z0-9]+", f"apiKey: {key}", text)
    cfg.write_text(text)
    sut_sh = run_dir / "sut-output.sh"
    sut_sh.write_text(f"#!/bin/sh\ncat \"$(dirname \"$0\")/{deliverable}\"\nexit 0\n")
    sut_sh.chmod(0o755)
    cp = subprocess.run(
        ["promptfoo", "eval", "-c", str(cfg), "-o", str(run_dir / "promptfoo-results.json")],
        capture_output=True, text=True, env=env, cwd=str(run_dir), timeout=900)
    rf = run_dir / "promptfoo-results.json"
    if cp.returncode != 0 and not rf.exists():
        print("  !! promptfoo 失败：" + (cp.stderr or cp.stdout)[-400:], file=sys.stderr)
        return None
    if cp.returncode != 0:
        print("  注意：promptfoo 退出码非 0（常见 telemetry 超时），结果文件已生成，继续解析")
    try:
        data = json.loads(rf.read_text())
    except Exception as exc:
        print(f"  !! 结果文件不可解析：{exc}", file=sys.stderr)
        return None
    entries = data["results"]["results"] if isinstance(data["results"], dict) else data["results"]
    assertions, n_pass = [], 0
    for e in entries:
        desc = (e.get("testCase") or {}).get("description", "")
        m = re.match(r"^(D\d+)", desc)
        if not m:
            continue
        comps = (e.get("gradingResult") or {}).get("componentResults") or []
        atype = comps[0]["assertion"]["type"] if comps else "llm-rubric"
        reason = comps[0].get("reason", "") if comps else ""
        passed = bool(e.get("success"))
        n_pass += passed
        assertions.append({"id": m.group(1), "type": atype, "pass": passed,
                           "detail": (reason or desc)[:160]})
    ok(f"断言自动转录 {len(assertions)} 条（{n_pass} 过）")
    return {"method": "offline-promptfoo（run_case.py 自动转录）",
            "assertions": assertions,
            "pass_rate": round(n_pass / len(assertions), 4) if assertions else 0.0}


def score_seeded_match(run_dir: Path, case: str, deliverable: str) -> dict | None:
    exp = DEFAULT_EVAL_ROOT / "cases/fixtures" / case / "EXPECTED.json"
    if not exp.exists():
        return None
    print("== 评分（CR seeded：match 草稿，待人工裁决）==")
    out = run_dir / "score-match-draft.json"
    cp = subprocess.run(
        [sys.executable, str(DEFAULT_EVAL_ROOT / "scripts/score_seeded.py"),
         "match", str(exp), str(run_dir / deliverable)],
        capture_output=True, text=True)
    if cp.returncode != 0:
        print("  !! match 失败：" + cp.stderr[-300:], file=sys.stderr)
        return None
    out.write_text(cp.stdout)
    ok(f"match 草稿 -> {out.name}（人工裁决后跑 score 步骤出最终指标）")
    return {"method": "seeded-match-draft（待人工裁决后 score）",
            "assertions": [], "pass_rate": 0.0}


def write_meta(run_dir: Path, case: str, spec: dict, model: str, kind: str,
               deliverable: str, sessions: dict, runinfo: dict,
               scoring: dict | None, extra_notes: str,
               variant: str = "baseline") -> None:
    verdict = "blocked"
    if scoring and scoring["assertions"]:
        verdict = "pass" if all(a["pass"] for a in scoring["assertions"]) else "fail"
    elif scoring and scoring["method"].startswith("seeded"):
        verdict = "blocked"  # 评分未完成裁决
    notes = ("meta 由 run_case.py 自动生成。permission_evidence/委派验收/异常归因"
             "请人工补充到 human_notes。")
    if sessions and sessions.get("side"):
        notes += f" 另有 {len(sessions['side'])} 个侧起主会话（见 opencode.db）。"
    if extra_notes:
        notes += " " + extra_notes
    subs_ids = [s["id"] for s in sessions["subs"]]
    process = {
        "delegations": build_delegations(sessions) if sessions else [],
        "rework_count": 0,
        "duration_sec": runinfo.get("duration", 0),
        "permission_evidence": "见 run-stderr.log（opencode --auto 权限线）",
    }
    if sessions and sessions.get("main"):
        process["sessions"] = {"main": sessions["main"]["id"], "sub": subs_ids}
    meta = {
        "case_id": run_dir.name,
        "title": f"{spec['sut'][0]} {case}（run_case.py 发起）",
        "date": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
        "run_kind": kind,
        "sut": {"name": spec["sut"][0], "type": spec["sut"][1],
                "version": spec["sut"][2], "commit": spec["sut"][3],
                "variant": variant},
        "host": "OpenCode CLI（opencode run --auto，经 group-b-expert-eval run_case.py）",
        "model": model,
        "input": spec["prompt"],
        "deliverable": deliverable,
        "verdict": verdict,
        "process": process,
        "human_notes": notes,
    }
    if scoring:
        meta["scoring"] = scoring
    if scoring and "promptfoo" in scoring["method"]:
        meta["promptfoo_results"] = "promptfoo-results.json"
    if runinfo.get("returncode"):
        meta["anomalies"] = []
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))
    ok(f"meta.json（verdict={verdict}）")


def rescore(args, spec: dict) -> int:
    """对已有 run 目录重跑评分：保留原 meta 的会话/过程证据，仅重写 scoring。"""
    run_dir = args.rescore_dir
    meta_p = run_dir / "meta.json"
    if not meta_p.exists():
        fail(f"--rescore-dir 需要 {run_dir}/meta.json")
    old = json.loads(meta_p.read_text())
    deliverable = old.get("deliverable")
    if not deliverable or not (run_dir / deliverable).exists():
        fail("原 meta 无 deliverable 或文件缺失")
    key = resolve_key()
    if not key:
        fail("未找到 DeepSeek key")
    env = dict(os.environ, PATH=NODE_BIN + os.pathsep + os.environ.get("PATH", ""))
    scoring = score_promptfoo(run_dir, args.case, key, env, deliverable)
    if scoring is None:
        fail("重评失败（见上方日志）")
    old["scoring"] = scoring
    old["verdict"] = ("pass" if all(a["pass"] for a in scoring["assertions"])
                      else "fail") if scoring["assertions"] else old["verdict"]
    old["human_notes"] = (old.get("human_notes") or "") + \
        f" | {datetime.now().strftime('%Y-%m-%d')} run_case.py --rescore 重评（断言自动转录）。"
    meta_p.write_text(json.dumps(old, ensure_ascii=False, indent=2))
    ok(f"rescore 完成（verdict={old['verdict']}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, choices=sorted(CASES))
    ap.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    ap.add_argument("--model", default="deepseek/deepseek-v4-pro")
    ap.add_argument("--run-kind", default="pilot",
                    choices=["formal", "pilot", "control-model", "control-no-expert"])
    ap.add_argument("--label", help="run 目录后缀，如 run2 → results/<case>-run2/")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--score-only", action="store_true",
                    help="不跑 opencode，只对 --deliverable 评分")
    ap.add_argument("--deliverable", help="评分用交付物路径（score-only 必填）")
    ap.add_argument("--rescore-dir", type=Path,
                    help="对已有 run 目录重新评分（保留原会话证据，重写 scoring）")
    ap.add_argument("--notes", default="", help="附加 human_notes")
    ap.add_argument("--variant", choices=["baseline", "optimized"],
                    default="baseline",
                    help="baseline=原包 v1.0.0, optimized=优化副本 v1.1.0")
    args = ap.parse_args()

    spec = CASES[args.case]
    if args.variant == "optimized":
        # 替换 SUT 和 ws 为 opt 版本
        if spec["sut"] == SUT_TD:
            spec["sut"] = SUT_TD_OPT
            spec["ws"] = "runs/ws-tech-digest-opt"
        elif spec["sut"] == SUT_CR:
            spec["sut"] = SUT_CR_OPT
            spec["ws"] = "runs/ws-code-review-opt"
    spec["prompt"] = spec["prompt"].replace("{date}",
        datetime.now().astimezone().strftime("%Y-%m-%d"))
    spec["deliverable"] = spec["deliverable"].replace("{date}",
        datetime.now().astimezone().strftime("%Y-%m-%d"))

    if args.rescore_dir:
        return rescore(args, spec)

    # optimized 变体自动加 opt 前缀到 label，避免覆盖基线 run 目录
    run_label = args.label
    if args.variant == "optimized":
        run_label = f"opt-{args.label}" if args.label else "opt"
    run_dir = args.eval_root / "results" / (
        f"{args.case}-{run_label}" if run_label else args.case)
    if run_dir.exists():
        fail(f"run 目录已存在：{run_dir}（用 --label 区分）")
    run_dir.mkdir(parents=True)

    ctx = preflight(args.eval_root, args.case, spec, need_run=not args.score_only)

    if args.score_only:
        if not args.deliverable:
            fail("--score-only 需要 --deliverable")
        sessions = None  # 无运行即无会话，不伪造占位 ID
        runinfo = {"duration": 0, "returncode": 0}
        deliverable = locate_deliverable(ctx["ws"], spec["deliverable"], 0,
                                         run_dir, args.deliverable)
        scoring = score_promptfoo(run_dir, args.case, ctx["key"], ctx["env"], deliverable)
        if scoring is None:
            scoring = score_seeded_match(run_dir, args.case, deliverable)
        write_meta(run_dir, args.case, spec, args.model, args.run_kind,
                   deliverable, sessions, runinfo, scoring,
                   "score-only：无会话回采。" + args.notes,
                   variant=args.variant)
    else:
        runinfo = run_opencode(spec, ctx, args.model, run_dir, args.timeout)
        sessions = harvest_sessions(ctx["ws"], runinfo["start_ms"])
        deliverable = locate_deliverable(ctx["ws"], spec["deliverable"],
                                         runinfo["start_ms"], run_dir, None)
        scoring = score_promptfoo(run_dir, args.case, ctx["key"], ctx["env"], deliverable)
        if scoring is None:
            scoring = score_seeded_match(run_dir, args.case, deliverable)
        write_meta(run_dir, args.case, spec, args.model, args.run_kind,
                   deliverable, sessions, runinfo, scoring, args.notes,
                   variant=args.variant)

    print(f"== 校验 schema ==")
    cp = subprocess.run([sys.executable,
                         str(args.eval_root / "schema/validate.py")],
                        capture_output=True, text=True)
    print((cp.stdout or cp.stderr).strip()[-400:])
    print(f"\n完成 -> {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
