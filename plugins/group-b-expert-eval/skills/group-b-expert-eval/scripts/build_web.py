#!/usr/bin/env python3
"""build_web.py — 从 OpenWork 对话调起的本地结果 Web 生成器（插件版）

与 eval/web/build.py 功能一致；本版本自包含于插件 scripts/，供 agent 在
OpenWork 对话中直接调起（导师要求：前端页面做到插件里，都是 agent 调起）。

定位 eval 工作区：环境变量 MOBILEWORK_EVAL_ROOT（默认 ~/Desktop/MobileWork/eval，
与 run_case.py/new_case.py 同一模式）。

AI 自由定制模板：HTML/CSS/JS 模板即本文件内的 TEMPLATE 字符串——agent 可直接
编辑此段自由填写前端页面模版（布局、配色、卡片、图表），保存后重新运行即生效。
--title/--accent 提供免编辑的快速参数化。

用法:
  python build_web.py                          # 只生成 <eval>/web/index.html 后退出
  python build_web.py --accent "#0052d9"       # 换主题色
  python build_web.py --title "B 组评测报告"    # 换标题
  python build_web.py --serve [--port 8763]     # 本地部署模式（G14 建议写回）

安全边界（任务书 §3.2：Web 不是第二控制台）：
  --serve 仅绑定 127.0.0.1，白名单路由只有 GET /(页面)、GET /api/data(只读)、
  POST /api/advice(G14 建议追加)；无任何发起运行/exec 类端点。
原始证据永不改写：POST 只允许追加进 advice.json（G14 建议宿主文件，
非运行证据）；meta.json/promptfoo-results.json 等 evidence 无写路径。
"""
import argparse
import json
import os
import re
import shutil
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EVAL_ROOT = Path(os.environ.get(
    "MOBILEWORK_EVAL_ROOT", Path.home() / "Desktop/MobileWork/eval")).resolve()
RESULTS = EVAL_ROOT / "results"
PACKAGES = EVAL_ROOT / "packages"
PROVENANCE = EVAL_ROOT / "records" / "provenance"
WEB_DIR = EVAL_ROOT / "web"
OUT = WEB_DIR / "index.html"
DS = EVAL_ROOT.parent / "MobileWork-Design-System"

SCRIPT_DIR = Path(__file__).resolve().parent

ASSETS = [
    (DS / "assets" / "china-mobile-logo.png", "china-mobile-logo.png"),
    (DS / "logos" / "favicon.ico", "favicon.ico"),
    # Chart.js 本地 vendored（零 CDN、file:// 离线可用）
    (SCRIPT_DIR / "assets" / "chart.umd.min.js", "chart.umd.min.js"),
]


def sync_assets():
    dst = WEB_DIR / "assets"
    dst.mkdir(exist_ok=True)
    for src, name in ASSETS:
        if src.exists():
            shutil.copy2(src, dst / name)


def load_runs():
    runs = []
    for d in sorted(RESULTS.iterdir()):
        meta_path = d / "meta.json"
        if not d.is_dir() or not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["_dir"] = d.name
        pf = d / meta.get("promptfoo_results", "promptfoo-results.json")
        meta["_assertions"] = []
        if pf.exists():
            data = json.loads(pf.read_text(encoding="utf-8"))
            for r in data["results"]["results"]:
                desc = r.get("testCase", {}).get("description", "")
                for a in r["gradingResult"]["componentResults"]:
                    meta["_assertions"].append({
                        "desc": desc or a["assertion"]["type"],
                        "type": a["assertion"]["type"],
                        "pass": bool(a["pass"]),
                        "reason": a.get("reason", ""),
                    })
        if not meta["_assertions"]:
            for a in meta.get("scoring", {}).get("assertions", []):
                meta["_assertions"].append({
                    "desc": a.get("id", ""),
                    "type": a.get("type", ""),
                    "pass": bool(a.get("pass")),
                    "reason": a.get("detail", ""),
                })
        meta["_deliverable_text"] = None
        dv = meta.get("deliverable")
        if dv and (d / dv).exists():
            meta["_deliverable_text"] = (d / dv).read_text(encoding="utf-8")
        runs.append(meta)
    return runs


def load_findings():
    f = RESULTS / "findings.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def load_objects(runs):
    by_name = {}
    for r in runs:
        by_name.setdefault(r["sut"]["name"], []).append(r)
    for pj in sorted(PACKAGES.glob("*/expert.json")):
        by_name.setdefault(pj.parent.name, [])
    objects = []
    for name, rs in sorted(by_name.items()):
        obj = {"slug": name, "runs": len(rs),
               "commits": sorted({x["sut"].get("commit", "") for x in rs if x["sut"].get("commit")}),
               "latest_verdict": rs[-1].get("verdict") if rs else None,
               "package_path": f"eval/packages/{name}/"}
        pj = PACKAGES / name / "expert.json"
        if pj.exists():
            e = json.loads(pj.read_text(encoding="utf-8"))
            obj.update({
                "name": e.get("name", name),
                "type": "专家团" if e.get("type") == "team" else "单专家",
                "summary": e.get("summary", ""),
                "description": e.get("description", ""),
                "profession": e.get("profession", ""),
                "tags": e.get("tags", []),
                "version": e.get("version", ""),
            })
            pa = e.get("primary_agent")
            if pa:
                obj["primary"] = {"id": pa.get("id"), "name": pa.get("name"),
                                  "profession": pa.get("profession"),
                                  "responsibilities": pa.get("responsibilities", [])}
            obj["members"] = [{"id": s.get("id"), "name": s.get("name"),
                               "profession": s.get("profession"),
                               "description": s.get("description", "")}
                              for s in e.get("subagents", [])]
            obj["workflows"] = [{"name": w.get("name"), "autonomy": w.get("autonomy"),
                                 "phases": [p.get("name") for p in w.get("phases", [])]}
                                for w in e.get("workflows", [])]
            obj["skills_count"] = len(e.get("common_skills", [])) + len(pa.get("skills", []) if pa else []) \
                + sum(len(s.get("skills", [])) for s in e.get("subagents", []))
        else:
            obj["name"] = name
            obj["type"] = rs[-1]["sut"].get("type", "") if rs else ""
        prov = PROVENANCE / f"{name}.md"
        if prov.exists():
            obj["provenance"] = f"eval/records/provenance/{name}.md"
        objects.append(obj)
    return objects


def build_stats(runs):
    total = len(runs)
    passed = sum(1 for r in runs if r.get("verdict") == "pass")
    by_sut, by_model, by_variant = {}, {}, {}
    for r in runs:
        sut = f"{r['sut']['name']}@{r['sut'].get('commit', '?')}"
        by_sut[sut] = by_sut.get(sut, 0) + 1
        by_model[r.get("model", "?")] = by_model.get(r.get("model", "?"), 0) + 1
        v = r["sut"].get("variant", "baseline")
        by_variant[v] = by_variant.get(v, 0) + 1
    return {"total": total, "passed": passed,
            "pass_rate": round(100 * passed / total) if total else 0,
            "by_sut": by_sut, "by_model": by_model, "by_variant": by_variant}


def build_comparisons(runs):
    groups = {}
    for r in runs:
        m = re.match(r'^(case-\d+|td-\d+|cr-\d+)', r["_dir"])
        if not m:
            continue
        base = m.group(1)
        g = groups.setdefault(base, {})
        score = f"{sum(a['pass'] for a in r['_assertions'])}/{len(r['_assertions'])}" if r["_assertions"] else "—"
        variant = r["sut"].get("variant", "baseline")
        g[variant] = {
            "version": r["sut"].get("version"), "commit": r["sut"].get("commit"),
            "verdict": r.get("verdict"), "score": score, "run": r["_dir"], "date": r.get("date"),
            "sut_name": r["sut"].get("name"),
        }
    return groups


def load_advice():
    p = RESULTS.parent / "records" / "advice.json"
    if not p.exists():
        return []
    advice = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(advice, list), "advice.json 应为数组"
    return advice


ADVICE_PATH = RESULTS.parent / "records" / "advice.json"
_ADVICE_LOCK = threading.Lock()
MAX_BODY = 65536


def append_advice(entry: dict) -> dict:
    """追加一条逐 case 人工建议（G14 数据流；append-only，不改已有条目）。"""
    case_id = str(entry.get("case_id", "")).strip()[:64]
    text = str(entry.get("advice", "")).strip()[:2000]
    if not case_id or not text:
        raise ValueError("case_id 与 advice 为必填")
    with _ADVICE_LOCK:
        advice = json.loads(ADVICE_PATH.read_text(encoding="utf-8")) \
            if ADVICE_PATH.exists() else []
        assert isinstance(advice, list)
        ids = {a.get("id", "") for a in advice}
        n = 1
        while f"A-{n:03d}" in ids:
            n += 1
        rec = {
            "id": f"A-{n:03d}",
            "case_id": case_id,
            "run_ref": str(entry.get("run_ref") or "") or None,
            "advice": text,
            "status": "open",
            "draft": False,
            "submitted_by": str(entry.get("submitted_by", "")).strip()[:32] or "页面提交",
            "date": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
            "linked_run": str(entry.get("linked_run") or "").strip()[:64] or None,
            "source": "web-ui",
        }
        if entry.get("evidence"):
            rec["evidence"] = str(entry["evidence"])[:500]
        advice.append(rec)
        ADVICE_PATH.write_text(
            json.dumps(advice, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def build_payload() -> dict:
    runs = load_runs()
    return {
        "generated_by": "group-b-expert-eval build_web.py（结果界面 + G14 建议写回，无执行入口）",
        "runs": runs,
        "findings": load_findings(),
        "objects": load_objects(runs),
        "stats": build_stats(runs),
        "comparisons": build_comparisons(runs),
        "advice": load_advice(),
    }


def write_page(payload: dict, title: str, accent: str) -> Path:
    sync_assets()
    data_js = json.dumps(payload, ensure_ascii=False) \
        .replace("<", "\\u003c").replace("</", "<\\/")
    page = (TEMPLATE
            .replace("/*__DATA__*/", f"const DATA = {data_js};")
            .replace("__PAGE_TITLE__", title)
            .replace("__ACCENT__", accent))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    return OUT


def main():
    ap = argparse.ArgumentParser(description="本地结果 Web 生成器（agent 可调起）")
    ap.add_argument("--title", default="MobileWork 专家（团）评测结果 · B 组",
                    help="页面标题（header h1 与 <title>）")
    ap.add_argument("--accent", default="#1890ff",
                    help="主题色 hex（如 #0052d9），驱动全套派生色")
    ap.add_argument("--serve", action="store_true",
                    help="本地部署模式：生成页面并起 127.0.0.1 server"
                         "（白名单 POST /api/advice 支持页面上提交 G14 建议）")
    ap.add_argument("--port", type=int, default=8763, help="--serve 模式端口")
    args = ap.parse_args()

    payload = build_payload()
    if not payload["runs"]:
        print("!! eval/results/ 下没有含 meta.json 的运行记录", file=sys.stderr)
        sys.exit(1)
    out = write_page(payload, args.title, args.accent)
    print(f"OK -> {out}  (runs={len(payload['runs'])}, "
          f"findings={len(payload['findings'])})")

    if not args.serve:
        print(f"在 OpenWork 内置浏览器或本机浏览器打开:\n  file://{out}")
        return

    class Handler(BaseHTTPRequestHandler):
        server_version = "MobileWorkEvalWeb/1.0"

        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict):
            self._send(code, "application/json; charset=utf-8",
                       json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", OUT.read_bytes())
            elif path == "/api/data":
                self._json(200, build_payload())  # 实时重扫，保证最新
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/advice":
                self._json(404, {"error": "not found（白名单外端点不存在）"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_BODY:
                    raise ValueError(f"请求体需在 1~{MAX_BODY} 字节")
                entry = json.loads(self.rfile.read(length).decode("utf-8"))
                rec = append_advice(entry)
                self._json(200, {"ok": True, "entry": rec})
                print(f"[advice] 新增 {rec['id']} ({rec['case_id']})", flush=True)
            except (ValueError, json.JSONDecodeError) as e:
                self._json(400, {"ok": False, "error": str(e)})

        def log_message(self, fmt, *log_args):  # 静默逐请求访问日志
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Serving http://127.0.0.1:{args.port}/   (仅本机可达；Ctrl+C 停止)")
    print("可用端点: GET / · GET /api/data · POST /api/advice —— 无执行类端点")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nserver 已停止")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="assets/favicon.ico">
<script src="assets/chart.umd.min.js"></script>
<title>__PAGE_TITLE__</title>
<style>
:root{
  --mw-page:#f0f2f5;--mw-ink:#121314;--mw-accent:__ACCENT__;
  --mw-surface:#ffffff;--mw-muted:#7c8085;--mw-hairline:#e5e6eb;
  --accent-bg:color-mix(in oklch,var(--mw-accent) 8%,var(--mw-surface));
  --accent-bg-hover:color-mix(in oklch,var(--mw-accent) 12%,var(--mw-surface));
  --accent-border:color-mix(in oklch,var(--mw-accent) 24%,var(--mw-hairline));
  --accent-strong:color-mix(in oklch,var(--mw-accent) 76%,var(--mw-ink));
  --font:'IBM Plex Sans Variable','IBM Plex Sans',Geist,'PingFang SC','Microsoft YaHei',ui-sans-serif,system-ui,sans-serif;
  --mono:ui-monospace,'SFMono-Regular',Menlo,Monaco,Consolas,'Liberation Mono',monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{font-size:14px}
body{font-family:var(--font);font-size:14px;line-height:1.5714;background:var(--mw-page);color:var(--mw-ink)}
header{background:var(--mw-surface);border-bottom:1px solid var(--mw-hairline);padding:20px 32px;display:flex;align-items:center;gap:16px}
header img.logo{height:36px;width:auto;display:block}
header .tt h1{font-size:18px;font-weight:600;line-height:1.25}
header .tt p{font-size:12px;color:var(--mw-muted);margin-top:2px}
nav{display:flex;gap:4px;padding:0 32px;background:var(--mw-surface);border-bottom:1px solid var(--mw-hairline);position:sticky;top:0;z-index:10}
nav button{border:0;background:none;min-height:44px;padding:0 16px;font-size:14px;font-family:var(--font);color:var(--mw-muted);cursor:pointer;border-bottom:2px solid transparent;border-radius:0}
nav button.on{color:var(--mw-accent);border-bottom-color:var(--mw-accent);font-weight:600}
nav button:hover{color:var(--mw-ink)}
main{max-width:1080px;margin:0 auto;padding:24px 32px 64px}
.view{display:none}.view.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--mw-surface);border:1px solid var(--mw-hairline);border-radius:8px;padding:16px}
.card .num{font-size:22px;font-weight:600;color:var(--mw-ink)}
.card .lbl{font-size:12px;color:var(--mw-muted);margin-top:2px}
h2{font-size:14px;font-weight:600;margin:24px 0 8px;padding-left:8px;border-left:3px solid var(--mw-accent)}
table{width:100%;border-collapse:collapse;background:var(--mw-surface);border:1px solid var(--mw-hairline);border-radius:8px;overflow:hidden;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--mw-hairline);vertical-align:top}
th{background:var(--mw-page);font-weight:600;color:var(--mw-muted);font-size:12px}
tr:last-child td{border-bottom:0}
.badge{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border-radius:5px;font-size:12px;font-weight:600;border:1px solid transparent;white-space:nowrap}
.b-pass{background:var(--accent-bg);color:var(--accent-strong);border-color:var(--accent-border)}
.b-fail{background:var(--mw-ink);color:var(--mw-surface)}
.b-sev-high{background:var(--mw-ink);color:var(--mw-surface)}
.b-sev-mid{background:var(--mw-page);color:var(--mw-ink);border-color:var(--mw-hairline)}
.b-sev-low{background:var(--mw-surface);color:var(--mw-muted);border-color:var(--mw-hairline)}
.tag{display:inline-block;padding:0 8px;border-radius:5px;font-size:11px;background:var(--mw-page);color:var(--mw-muted);border:1px solid var(--mw-hairline)}
.run{border:1px solid var(--mw-hairline);border-radius:8px;background:var(--mw-surface);margin-bottom:12px;overflow:hidden}
.run-head{padding:12px 16px;min-height:44px;cursor:pointer;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.run-head:hover{background:var(--mw-page)}
.run-head .t{font-weight:600}
.run-head .meta{font-size:12px;color:var(--mw-muted)}
.run-body{display:none;padding:0 16px 16px;border-top:1px solid var(--mw-hairline)}
.run.open .run-body{display:block}
.kv{font-size:13px;margin:8px 0}.kv b{color:var(--mw-muted);font-weight:600}
pre{white-space:pre-wrap;word-break:break-word;background:var(--mw-page);border:1px solid var(--mw-hairline);border-radius:8px;padding:12px;font-size:12px;font-family:var(--mono);max-height:420px;overflow:auto}
.reason{color:var(--mw-muted);font-size:12px}
.empty{color:var(--mw-muted);font-size:13px;padding:16px;border:1px dashed var(--mw-hairline);border-radius:8px;text-align:center;margin:8px 0}
footer{text-align:center;color:var(--mw-muted);font-size:12px;padding:20px;border-top:1px solid var(--mw-hairline);background:var(--mw-surface)}
ul.clean{list-style:none;background:var(--mw-surface);border:1px solid var(--mw-hairline);border-radius:8px;padding:4px 16px}
ul.clean li{padding:8px 0;border-bottom:1px dashed var(--mw-hairline);font-size:13px}
ul.clean li:last-child{border-bottom:0}
.filterbar,.pairbar,.formrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0;background:var(--mw-surface);border:1px solid var(--mw-hairline);border-radius:8px;padding:10px 12px}
.filterbar input[type=text],.pairbar select,.filterbar select,.formrow input,.formrow select{border:1px solid var(--mw-hairline);border-radius:8px;background:var(--mw-surface);color:var(--mw-ink);font-family:var(--font);font-size:13px;padding:6px 10px;min-height:32px}
.filterbar input[type=text]{flex:1;min-width:160px}
.formrow textarea{width:100%;min-height:72px;border:1px solid var(--mw-hairline);border-radius:8px;background:var(--mw-surface);color:var(--mw-ink);font-family:var(--font);font-size:13px;padding:8px 10px;resize:vertical}
.btn-accent{background:var(--accent-strong);color:var(--mw-surface);border:0;border-radius:8px;padding:7px 18px;font-size:13px;font-weight:600;font-family:var(--font);cursor:pointer;min-height:34px}
.btn-accent:hover{filter:brightness(1.08)}
.btn-ghost{background:var(--mw-surface);color:var(--mw-accent);border:1px solid var(--accent-border);border-radius:8px;padding:7px 14px;font-size:13px;font-weight:600;font-family:var(--font);cursor:pointer;min-height:34px}
.fcount{font-size:12px;color:var(--mw-muted);margin-left:auto}
tr.trow{cursor:pointer}
tr.trow:hover td{background:var(--accent-bg-hover)}
tr.trdetail>td{background:var(--mw-page)}
.chart-grid{display:grid;grid-template-columns:320px 1fr;gap:12px;margin-bottom:20px}
@media(max-width:760px){.chart-grid{grid-template-columns:1fr}}
.chart-cell{background:var(--mw-surface);border:1px solid var(--mw-hairline);border-radius:8px;padding:14px}
.chart-title{font-size:12px;color:var(--mw-muted);margin-bottom:8px;text-align:center}
.heatwrap{overflow-x:auto;background:var(--mw-surface);border:1px solid var(--mw-hairline);border-radius:8px;padding:14px}
table.heat{border-collapse:separate;border-spacing:3px;width:100%}
table.heat th{font-size:11px;font-weight:600;background:none;padding:2px 6px}
table.heat td.hcell{height:26px;min-width:34px;border-radius:5px;text-align:center;font-size:10px;font-weight:700;line-height:26px;padding:0}
.hp{background:var(--accent-bg);color:var(--accent-strong);border:1px solid var(--accent-border)}
.hf{background:var(--mw-ink);color:var(--mw-surface)}
.hb{background:var(--mw-page);color:var(--mw-muted);border:1px dashed var(--mw-hairline)}
.hn{background:transparent;border:1px dashed var(--mw-hairline)}
</style>
</head>
<body>
<header>
  <img class="logo" src="assets/china-mobile-logo.png" alt="中国移动 China Mobile">
  <div class="tt">
    <h1>__PAGE_TITLE__</h1>
    <p>只读结果界面 · 数据源于 eval/results/ · 视觉遵循 MobileWork Design System</p>
  </div>
</header>
<nav id="nav"></nav>
<main>
  <section class="view" id="v-overview">
    <div class="cards" id="statCards"></div>
    <h2>核心指标</h2>
    <div class="chart-grid">
      <div class="chart-cell"><canvas id="chDonut" height="210"></canvas></div>
      <div class="chart-cell"><canvas id="chByCase" height="210"></canvas></div>
    </div>
    <h2>80 次正式运行矩阵（行=case，列=5 次重复；绿=pass 黑=fail 灰=blocked/其他）</h2>
    <div id="heatGrid"></div>
    <h2>被测对象（点击展开介绍）</h2><div id="sutList"></div>
  </section>
  <section class="view" id="v-runs">
    <div class="filterbar">
      <button class="btn-accent" id="modeCard" onclick="setRunMode('card')">卡片</button>
      <button class="btn-ghost" id="modeTable" onclick="setRunMode('table')">表格</button>
      <input type="text" id="fText" placeholder="搜索标题 / case / 对象 / 模型…">
      <select id="fCase"><option value="">全部 case</option></select>
      <select id="fVariant"><option value="">全部变体</option><option value="baseline">baseline</option><option value="optimized">optimized</option><option value="__group_control">对照臂</option></select>
      <select id="fVerdict"><option value="">全部结论</option><option value="pass">pass</option><option value="fail">fail</option><option value="blocked">blocked</option><option value="__group_other">其他</option></select>
      <span class="fcount" id="fCount"></span>
    </div>
    <div id="runList"></div>
  </section>
  <section class="view" id="v-findings"><div id="findingList"></div></section>
  <section class="view" id="v-compare">
    <div id="cmpSummary"></div>
    <h2>优化净效果与耗时对比</h2>
    <div class="chart-grid">
      <div class="chart-cell"><canvas id="chDelta" height="210"></canvas></div>
      <div class="chart-cell"><canvas id="chDur" height="210"></canvas></div>
    </div>
    <h2>优化前后对比（自动配对）</h2><div id="compareBox"></div>
    <h2>自由配对对比</h2>
    <div class="pairbar">
      <label style="font-size:12px;color:var(--mw-muted)">Run A</label>
      <select id="cmpA" style="max-width:340px"></select>
      <span style="font-weight:600">vs</span>
      <label style="font-size:12px;color:var(--mw-muted)">Run B</label>
      <select id="cmpB" style="max-width:340px"></select>
    </div>
    <div id="customPair"></div>
  </section>
  <section class="view" id="v-notes"><div id="notesBox"></div></section>
</main>
<footer>本页面由 build_web.py 自动生成（agent 调起）· 本地只读，无执行入口 · 原始数据不出本机</footer>
<script>
/*__DATA__*/
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const CASE_INFO={'td-01':'端侧大模型推理优化简报(结构化,600字)','td-02':'RAG评测方法技术周报(结构化,800字,四栏目)','td-03':'向量数据库选型调研(混合式,1500字,Milvus/Qdrant/pgvector)','td-04':'AI Agent记忆机制调研(开放式,1000字)','cr-01':'预埋Python代码评审(user_service.py,8个预埋问题)','cr-02':'预埋JS安全评审(auth.js,安全+性能)','cr-03':'真实代码可维护性评审(diagnose_expert.py)','cr-04':'开放多文件评审(mininote全套源码)','case-001':'第2周链路验证case(端侧推理优化简报)'};
const VIEWS=[["v-overview","总览"],["v-runs","运行记录"],["v-findings","异常与发现"],["v-compare","优化前后对比"],["v-notes","人工建议"]];
const nav=$("#nav");
VIEWS.forEach(([id,label],i)=>{const b=document.createElement("button");b.textContent=label;b.onclick=()=>{VIEWS.forEach(([v])=>{$("#"+v).classList.remove("on")});nav.querySelectorAll("button").forEach(x=>x.classList.remove("on"));$("#"+id).classList.add("on");b.classList.add("on")};if(i===0)b.classList.add("on");nav.appendChild(b)});
$("#v-overview").classList.add("on");
const st=DATA.stats;
$("#statCards").innerHTML=[["正式运行",st.total],["通过率",st.pass_rate+"%"],["异常/发现",DATA.findings.length],["被测对象",Object.keys(st.by_sut).length]].map(([l,n])=>`<div class="card"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");

/* ===== 总览图表（Chart.js 本地 vendored；缺失时优雅降级为表格） ===== */
const VC={pass:getComputedStyle(document.documentElement).getPropertyValue('--mw-accent').trim()||'#1890ff',
          fail:'#121314',blocked:'#7c8085'};
const vcnt={pass:0,fail:0,other:0};
DATA.runs.forEach(r=>{if(r.verdict==='pass')vcnt.pass++;else if(r.verdict==='fail')vcnt.fail++;else vcnt.other++});
if(window.Chart){
  Chart.defaults.font.family=getComputedStyle(document.body).fontFamily;
  new Chart($("#chDonut"),{type:'doughnut',
    data:{labels:['通过','未通过','其他状态'],datasets:[{data:[vcnt.pass,vcnt.fail,vcnt.other],
      backgroundColor:[VC.pass,VC.fail,VC.blocked],borderWidth:2,borderColor:'#ffffff'}]},
    options:{plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}},
      title:{display:true,text:`全部运行 verdict 分布 (N=${DATA.runs.length})`,font:{size:12}}},cutout:'58%'}});

  // 按 case 聚合（共享给对比 tab 图表）：baseline/optimized 通过率 + 平均耗时
  window.AGG={};
  DATA.runs.forEach(r=>{
    const m=String(r.case_id||r._dir).match(/^(case-\d+|td-\d+|cr-\d+)/);if(!m)return;
    const base=m[1];window.AGG[base]=window.AGG[base]||{};
    const v=r.sut?.variant||'baseline';
    if(v==='baseline'||v==='optimized'){
      window.AGG[base][v]=window.AGG[base][v]||{p:0,t:0,durSum:0,durN:0};
      const g=window.AGG[base][v];g.t++;
      if(r.verdict==='pass')g.p++;
      const d=Number(r.process?.duration_sec);
      if(d>0){g.durSum+=d;g.durN++;}
    }
  });
  const byCase=window.AGG;
  const keys=Object.keys(byCase).sort();
  new Chart($("#chByCase"),{type:'bar',
    data:{labels:keys,datasets:[
      {label:'原包 pass%',data:keys.map(k=>byCase[k].baseline?Math.round(100*byCase[k].baseline.p/byCase[k].baseline.t):null),
       backgroundColor:VC.pass,borderRadius:4},
      {label:'优化副本 pass%',data:keys.map(k=>byCase[k].optimized?Math.round(100*byCase[k].optimized.p/byCase[k].optimized.t):null),
       backgroundColor:VC.blocked,borderRadius:4}]},
    options:{scales:{y:{beginAtZero:true,max:100,title:{display:true,text:'断言/verdict 通过率 %',font:{size:11}}}},
      plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}},responsive:true}});

  /* 矩阵热力格：行=case，列=5 次重复 ×2 变体 */
  const heat={};
  DATA.runs.forEach(r=>{
    const m=String(r._dir||'').match(/^(case-\d+|td-\d+|cr-\d+)(-(opt))?-formal-r(\d+)/);
    if(!m)return;
    const base=m[1],variant=m[3]?'opt':'base';
    const col=m[4];
    heat[base]=heat[base]||{};heat[base][variant+col]={verdict:r.verdict,run:r._dir};
  });
  const hkeys=Object.keys(heat).sort();
  const cell=v=>v==='pass'?['hp','✓']:v==='fail'?['hf','✗']:['hb','⚠'];
  $("#heatGrid").innerHTML=`<div class="heatwrap"><table class="heat"><tr><th></th>${[1,2,3,4,5].map(i=>`<th colspan="2" style="text-align:center;border-left:1px solid var(--mw-hairline)">R${i}</th>`).join('')}</tr>
    <tr><th></th>${[1,2,3,4,5].map(i=>'<th>基线</th><th>副本</th>').join('')}</tr>
    ${hkeys.map(b=>`<tr><th style="text-align:left">${esc(b)}</th>${[1,2,3,4,5].map(i=>['base','opt'].map(v=>{
      const d=(heat[b]&&heat[b][v+i])||null;
      if(!d)return '<td class="hcell hn"></td>';
      const [cls,ch]=cell(d.verdict);
      return `<td class="hcell ${cls}" title="${esc(d.run)}">${ch}</td>`;
    }).join('')).join('')}</tr>`).join('')}</table></div>`;
}else{
  $("#heatGrid").innerHTML='<div class="empty">chart.umd.min.js 未找到（assets 同步失败），图表降级。可用表格视图查看各 case 数据。</div>';
}
// 被测对象身份卡
$("#sutList").innerHTML=DATA.objects.map(o=>{
  const members=(o.members||[]).map(m=>`<tr><td>${esc(m.name)}</td><td style="font-family:var(--mono);font-size:11px">${esc(m.id)}</td><td>${esc(m.profession||'')}</td><td class="reason">${esc(m.description||'')}</td></tr>`).join("");
  const wfs=(o.workflows||[]).map(w=>`<tr><td>${esc(w.name)}</td><td>${esc(w.autonomy||'')}</td><td>${(w.phases||[]).map(p=>esc(p)).join(' → ')}</td></tr>`).join("");
  const tags=(o.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join(" ");
  const pa=o.primary;
  return `<div class="run"><div class="run-head" onclick="this.parentNode.classList.toggle('open')">
    <span class="badge ${o.type==='专家团'?'b-pass':'b-sev-mid'}">${esc(o.type||'对象')}</span>
    <span class="t">${esc(o.name||o.slug)}</span>
    <span class="meta">${esc(o.slug)} · v${esc(o.version||'?')}@${(o.commits||[]).join('/')} · ${o.runs} 次运行</span></div>
  <div class="run-body">
    <div class="kv"><b>简介</b>　${esc(o.summary||'')}</div>
    ${o.description?`<div class="kv"><b>详述</b>　${esc(o.description)}</div>`:""}
    <div class="kv"><b>类型/职能</b>　${esc(o.profession||'')} ｜ <b>技能数</b>　${o.skills_count??'—'} ${tags?'｜ '+tags:''}</div>
    ${pa?`<h2>团长 / 主角色</h2><table><tr><th>名称</th><th>ID</th><th>职能</th><th>职责</th></tr><tr><td>${esc(pa.name)}</td><td style="font-family:var(--mono);font-size:11px">${esc(pa.id)}</td><td>${esc(pa.profession||'')}</td><td class="reason">${(pa.responsibilities||[]).map(x=>esc(x)).join('；')}</td></tr></table>`:""}
    ${members?`<h2>成员（${(o.members||[]).length}）</h2><table><tr><th>名称</th><th>ID</th><th>职能</th><th>说明</th></tr>${members}</table>`:""}
    ${wfs?`<h2>工作流</h2><table><tr><th>名称</th><th>自主度</th><th>阶段</th></tr>${wfs}</table>`:""}
    <div class="kv"><b>包路径</b>　<span style="font-family:var(--mono);font-size:12px">${esc(o.package_path||'')}</span>${o.provenance?` ｜ <b>来源记录</b>　<span style="font-family:var(--mono);font-size:12px">${esc(o.provenance)}</span>`:""}</div>
  </div></div>`}).join("")||'<div class="empty">暂无被测对象</div>';
const badgePass=p=>p?'<span class="badge b-pass">✓ 通过</span>':'<span class="badge b-fail">✗ 未通过</span>';
const badgeVerdict=v=>v==='pass'?'<span class="badge b-pass">✓ 通过</span>':v==='fail'?'<span class="badge b-fail">✗ 未通过</span>':v==='blocked'?'<span class="badge b-sev-mid">⚠ 评分未裁决</span>':'<span class="badge b-sev-low">'+esc(v)+'</span>';
$("#findingList").innerHTML=`<table><tr><th>ID</th><th>严重度</th><th>标题</th><th>状态</th><th>详情</th></tr>${DATA.findings.map(f=>`<tr><td>${f.id}</td><td><span class="badge ${f.severity==='高'?'b-sev-high':f.severity==='中'?'b-sev-mid':'b-sev-low'}">${f.severity==='高'?'! ':f.severity==='中'?'● ':'○ '}${esc(f.severity)}</span></td><td>${esc(f.title)}</td><td>${esc(f.status)}</td><td class="reason">${esc(f.detail)}</td></tr>`).join("")}</table>`;
const cmp=Object.entries(DATA.comparisons);
const getRun=dir=>DATA.runs.find(r=>r["_dir"]===dir);
$("#compareBox").innerHTML=cmp.length?(()=>{
  let gUp=0,gDown=0,gSame=0;
  const groupsHtml=cmp.map(([name,g])=>{
  const blRun=g.baseline?getRun(g.baseline.run):null, optRun=g.optimized?getRun(g.optimized.run):null;
  const blA=blRun?(blRun["_assertions"]||[]):[], optA=optRun?(optRun["_assertions"]||[]):[];
  const allDids=[...new Set([...blA.map(a=>a.desc),...optA.map(a=>a.desc)])];
  let up=0,down=0,same=0;
  allDids.forEach(d=>{const b=blA.find(a=>a.desc===d)?.pass,o=optA.find(a=>a.desc===d)?.pass;
    if(b===false&&o===true)up++;else if(b===true&&o===false)down++;else if(b!==undefined&&o!==undefined)same++});
  gUp+=up;gDown+=down;gSame+=same;
  const sumBadge=(up||down||same)?`<span class="tag" style="margin-left:8px">↑提升 ${up}</span> <span class="tag" style="margin-left:4px">↓退化 ${down}</span> <span class="tag" style="margin-left:4px">不变 ${same}</span>`:'';
  const mainRows=["baseline","optimized"].filter(v=>g[v]).map(v=>{
    const run=v==='baseline'?blRun:optRun;
    const dur=run?.process?.duration_sec?Math.round(run.process.duration_sec)+'s':'—';
    return `<tr><td>${v==='baseline'?'原包':'优化副本'}</td><td>${esc(g[v].version||'')}</td><td>${g[v].score}</td><td>${badgeVerdict(g[v].verdict)}</td><td style="font-family:var(--mono);font-size:11px">${esc(g[v].run||'')}</td><td>${dur}</td></tr>`;
  }).join("");
  const blockedNote=(g.baseline?.verdict==='blocked'||g.optimized?.verdict==='blocked')?`<div style="padding:4px 0;color:var(--mw-muted);font-size:12px">⚠ 评分未裁决:该 case 使用 seeded match 评分(预埋答案匹配),需人工裁决后才能出最终断言。运行本身正常(有交付物)。</div>`:"";
  const assertRows=allDids.length?allDids.map(d=>{
    const b=blA.find(a=>a.desc===d), o=optA.find(a=>a.desc===d);
    const bP=b?.pass, oP=o?.pass;
    let chg='<span style="color:var(--mw-muted)">不变</span>';
    if(bP===false&&oP===true) chg='<span class="badge b-pass">↑ 提升</span>';
    else if(bP===true&&oP===false) chg='<span class="badge b-fail">↓ 退化</span>';
    else if(bP===undefined&&oP!==undefined) chg='<span class="badge b-sev-low">新增</span>';
    else if(oP===undefined&&bP!==undefined) chg='<span class="badge b-sev-low">移除</span>';
    let row=`<tr><td class="reason">${esc(d)}</td><td>${bP===undefined?'—':badgePass(bP)}</td><td>${oP===undefined?'—':badgePass(oP)}</td><td>${chg}</td></tr>`;
    if(bP===false||oP===false){
      const failReason=(bP===false?b?.reason:'')||(oP===false?o?.reason:'')||'';
      if(failReason)row+=`<tr><td colspan="4" style="padding:2px 8px 6px 24px;color:var(--mw-muted);font-size:12px">↳ ${esc(failReason.slice(0,150))}</td></tr>`;
    }
    return row;
  }).join(""):"";
  return `<h2>${esc(name)} <span style="font-weight:400;color:var(--mw-muted);font-size:13px">${esc(CASE_INFO[name]||'')}</span>${sumBadge}</h2><table><tr><th>变体</th><th>版本</th><th>评分</th><th>结论</th><th>运行</th><th>耗时</th></tr>${mainRows}</table>${assertRows?`<table style="margin-top:4px"><tr><th>断言维度</th><th>基线</th><th>优化</th><th>变化</th></tr>${assertRows}</table>`:""}${blockedNote}${!g.optimized?'<div class="empty">优化副本尚未产生</div>':""}`;
  }).join('');
  const verdict=gUp-gDown>=0?'b-pass':'b-fail';
  $("#cmpSummary").innerHTML=`<div class="card" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin-bottom:4px">
    <span style="font-weight:600;font-size:13px">全局净效果（${cmp.length} 个 case 断言汇总）</span>
    <span class="badge ${verdict}">↑ 提升 ${gUp}</span><span class="badge b-fail">↓ 退化 ${gDown}</span>
    <span class="badge b-sev-low">不变 ${gSame}</span></div>`;
  return groupsHtml;
})():'<div class="empty">暂无数据</div>';

/* ===== 对比 tab 两张聚合图（Δ 通过率正负柱 + 耗时成对柱） ===== */
if(window.Chart){
  const agg=window.AGG||{};
  const keys=Object.keys(agg).sort();
  const delta=keys.map(k=>{
    const b=agg[k].baseline,o=agg[k].optimized;
    if(!b||!o)return null;
    return Math.round(100*(o.p/o.t - b.p/b.t));
  });
  new Chart($("#chDelta"),{type:'bar',
    data:{labels:keys,datasets:[{label:'优化副本 − 原包 (百分点)',
      data:delta,backgroundColor:delta.map(v=>v>=0?VC.pass:VC.fail),borderRadius:3}]},
    options:{plugins:{legend:{display:false},title:{display:true,text:'通过率变化 Δ(副本−基线)',font:{size:12}}},
      scales:{y:{title:{display:true,text:'百分点',font:{size:11}}}}}});
  const hasDur=keys.filter(k=>agg[k].baseline?.durN&&agg[k].optimized?.durN);
  new Chart($("#chDur"),{type:'bar',
    data:{labels:hasDur,datasets:[
      {label:'原包 平均耗时(s)',data:hasDur.map(k=>Math.round(agg[k].baseline.durSum/agg[k].baseline.durN)),
       backgroundColor:VC.pass,borderRadius:3},
      {label:'副本 平均耗时(s)',data:hasDur.map(k=>Math.round(agg[k].optimized.durSum/agg[k].optimized.durN)),
       backgroundColor:VC.blocked,borderRadius:3}]},
    options:{plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}},
      scales:{y:{beginAtZero:true,title:{display:true,text:'秒',font:{size:11}}}}}});
}
const adv=DATA.advice||[];
const stB=s=>s==='applied'?'b-pass':s==='rejected'?'b-fail':'b-sev-mid';
const stI=s=>s==='applied'?'✓ ':s==='rejected'?'✗ ':'● ';
const advTable=adv.length?`<table><tr><th>ID</th><th>Case</th><th>建议</th><th>状态</th><th>评审人</th><th>日期</th><th>关联复测</th></tr>${adv.map(a=>`<tr><td>${esc(a.id)}</td><td>${esc(a.case_id)}</td><td class="reason">${esc(a.advice)}</td><td><span class="badge ${stB(a.status)}">${stI(a.status)}${esc(a.status)}</span>${a.draft?' <span class="badge b-sev-low">draft</span>':''}</td><td>${esc(a.submitted_by||'')}</td><td>${esc(a.date||'')}</td><td>${esc(a.linked_run||'—')}</td></tr>`).join("")}</table>`:'';
const sugg=DATA.runs.flatMap(r=>(r.suggestions||[]).map(s=>[r.case_id,s]));
$("#notesBox").innerHTML=advTable+(sugg.length?`<h2>运行内自动备注（非人工提交，供评审参考）</h2><ul class="clean">${sugg.map(([c,s])=>`<li><b>[${esc(c)}]</b> ${esc(s)}</li>`).join("")}</ul>`:(adv.length?'':'<div class="empty">暂无人工建议</div>'));

/* ===== G14 逐 case 建议表单（--serve 模式下可写回 advice.json） ===== */
const onServe=location.protocol.startsWith('http');
$("#notesBox").insertAdjacentHTML('beforeend',`
<h2>提交逐 case 建议（G14）</h2>
<div style="font-size:12px;color:var(--mw-muted);margin:4px 0">建议追加写入 eval/records/advice.json；原始运行证据只读不受影响。${onServe?'':'<b>当前为 file:// 直开，写回不可用——请用 build_web.py --serve 本地部署模式。</b>'}</div>
<div class="formrow" style="flex-direction:column;align-items:stretch">
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <select id="advCase" required></select>
    <input id="advBy" placeholder="评审人（可选）" style="max-width:160px">
    <input id="advRun" placeholder="关联运行目录（可选，如 td-01-formal-r3）" style="flex:1;min-width:200px">
  </div>
  <textarea id="advText" placeholder="针对该 case 的改进建议：问题定位、优化方向、预期效果…"></textarea>
  <div><button class="btn-accent" onclick="submitAdvice()" ${onServe?'':'disabled'}>提交建议</button>
  <span id="advMsg" class="reason"></span></div>
</div>`);
{
  const caseIds=[...new Set([...DATA.runs.map(r=>r.case_id),...DATA.advice.map(a=>a.case_id)])].filter(Boolean).sort();
  $("#advCase").innerHTML='<option value="">— 选择 case —</option>'+caseIds.map(c=>`<option>${esc(c)}</option>`).join('');
}
async function submitAdvice(){
  const m=$("#advMsg");
  const body={case_id:$("#advCase").value, advice:$("#advText").value.trim(),
    submitted_by:$("#advBy").value.trim(), linked_run:$("#advRun").value.trim()};
  if(!body.case_id||!body.advice){m.textContent='⚠ 请选择 case 并填写建议内容';m.style.color='var(--mw-ink)';return}
  try{
    const r=await fetch('/api/advice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json();
    if(j.ok){DATA.advice.push(j.entry);renderNotesTable();$("#advText").value='';
      m.textContent=`✓ 已提交 ${j.entry.id}`;}
    else{m.textContent='✗ '+(j.error||'提交失败');}
  }catch(e){m.textContent='✗ 网络/服务错误：'+e}
}
function renderNotesTable(){
  const a2=DATA.advice;
  const t=a2.length?`<table><tr><th>ID</th><th>Case</th><th>建议</th><th>状态</th><th>评审人</th><th>日期</th><th>关联复测</th></tr>${a2.map(a=>`<tr><td>${esc(a.id)}</td><td>${esc(a.case_id)}</td><td class="reason">${esc(a.advice)}</td><td><span class="badge ${stB(a.status)}">${stI(a.status)}${esc(a.status)}</span></td><td>${esc(a.submitted_by||'')}</td><td>${esc(a.date||'')}</td><td>${esc(a.linked_run||'—')}</td></tr>`).join("")}</table>`:'<div class="empty">暂无人工建议</div>';
  // 仅替换表格区域：插入在表单 h2 之前
  const formStart=$("#notesBox").innerHTML.indexOf('<h2>提交逐 case 建议（G14）</h2>');
  if(formStart>=0)$("#notesBox").innerHTML=t+$("#notesBox").innerHTML.slice(formStart);
}

/* ===== 运行记录筛选 + 卡片/表格双模式 ===== */
const baseCase=s=>(String(s).match(/^(case-\d+|td-\d+|cr-\d+)/)||[''])[0];
const allRuns=DATA.runs;
let runMode='card';
let runDetailBody=null; // 卡片详情渲染函数（每条 run 展开后的 HTML）
runDetailBody=r=>{
  const asserts=r._assertions.map(a=>`<tr><td>${badgePass(a.pass)}</td><td>${esc(a.desc)}</td><td>${esc(a.type)}</td><td class="reason">${esc(a.reason)}</td></tr>`).join("");
  const dels=(r.process?.delegations||[]).map(d=>`<tr><td>${esc(d.stage)}</td><td>${esc(d.agent)}</td><td style="font-family:var(--mono);font-size:11px">${esc(d.session)}</td><td>${esc(d.acceptance)}</td></tr>`).join("");
  const anom=(r.anomalies||[]).map(id=>{const f=DATA.findings.find(x=>x.id===id);return f?`<span class="badge b-sev-mid">${f.id} ${esc(f.title)}</span>`:id}).join(" ");
  return `
    <div class="kv"><b>输入</b>　${esc(r.input)}</div>
    <div class="kv"><b>宿主</b>　${esc(r.host)} ｜ <b>声明自主度</b>　${esc(r.process?.autonomy_declared||'')} ｜ <b>返工</b>　${r.process?.rework_count??'—'}</div>
    ${dels?`<h2>委派关系与验收</h2><table><tr><th>阶段</th><th>执行者</th><th>子会话</th><th>验收</th></tr>${dels}</table>`:""}
    <div class="kv"><b>终审</b>　${esc(r.process?.final_review||'')}</div>
    <div class="kv"><b>权限决策证据</b>　${esc(r.process?.permission_evidence||'')}</div>
    ${asserts?`<h2>Promptfoo 评分（${r._assertions.filter(a=>a.pass).length}/${r._assertions.length}）</h2><table><tr><th></th><th>维度</th><th>类型</th><th>评分理由</th></tr>${asserts}</table>`:""}
    ${r._deliverable_text?`<details style="margin:8px 0"><summary class="btn-ghost" style="display:inline-block;list-style:none;cursor:pointer">📄 查看交付物全文（${esc(r.deliverable)}）</summary><pre style="margin-top:6px">${esc(r._deliverable_text)}</pre></details>`:""}
    ${anom?`<div class="kv"><b>关联异常</b>　${anom}</div>`:""}
    ${r.human_notes?`<div class="kv"><b>备注</b>　${esc(r.human_notes)}</div>`:""}`;
};
function renderRuns(filtered){
  if(runMode==='card'){
    $("#runList").innerHTML=filtered.length?filtered.map(r=>`
      <div class="run"><div class="run-head" onclick="this.parentNode.classList.toggle('open')">
        ${badgePass(r.verdict==='pass')}
        <span class="t">${esc(r.title)}</span><span class="meta">${esc(r.case_id)} · ${esc(r.date)} · ${esc(r.sut.name)}@${esc(r.sut.commit||'')} · ${esc(r.model)}</span></div>
      <div class="run-body">${runDetailBody(r)}</div></div>`).join(''):'<div class="empty">没有符合筛选条件的运行</div>';
  }else{
    const rows=filtered.map((r,i)=>{
      const asrt=r._assertions,score=asrt.length?`${asrt.filter(a=>a.pass).length}/${asrt.length}`:'—';
      const dur=r.process?.duration_sec>0?Math.round(r.process.duration_sec)+'s':'—';
      const v=r.sut?.variant||'baseline';
      return `<tr class="trow" onclick="toggleTRow(${i})">
        <td>${badgeVerdict(r.verdict)}</td><td style="max-width:260px" class="reason">${esc(r.title)}</td>
        <td>${esc(r.case_id)}</td><td><span class="tag">${esc(v)}</span></td>
        <td class="reason">${esc(r.model.replace('deepseek/',''))}</td><td>${dur}</td><td>${score}</td></tr>
      <tr class="trdetail" id="tdetail-${i}" style="display:none"><td colspan="7">${runDetailBody(r)}</td></tr>`;
    }).join('');
    $("#runList").innerHTML=filtered.length?`<table class="rtable"><tr><th>结论</th><th>标题</th><th>Case</th><th>变体</th><th>模型</th><th>耗时</th><th>得分</th></tr>${rows}</table>`:'<div class="empty">没有符合筛选条件的运行</div>';
  }
  window._shown=filtered;
  $("#fCount").textContent=`${filtered.length} / ${allRuns.length} 条`;
}
function toggleTRow(i){
  const el=document.getElementById('tdetail-'+i);
  el.style.display=el.style.display==='none'?'':'none';
}
function setRunMode(m){
  runMode=m;
  $("#modeCard").className=m==='card'?'btn-accent':'btn-ghost';
  $("#modeTable").className=m==='table'?'btn-accent':'btn-ghost';
  applyFilters();
}
function applyFilters(){
  const kw=$("#fText").value.trim().toLowerCase(), fc=$("#fCase").value,
        fv=$("#fVariant").value, fvj=$("#fVerdict").value;
  const filtered=allRuns.filter(r=>{
    if(fc&&baseCase(r.case_id)!==fc)return false;
    const variant=r.sut?.variant||'baseline';
    if(fv==='__group_control'){if(!variant.startsWith('control'))return false}
    else if(fv&&variant!==fv)return false;
    if(fvj==='__group_other'){if(['pass','fail','blocked'].includes(r.verdict))return false}
    else if(fvj&&r.verdict!==fvj)return false;
    if(kw&&![r.title,r.case_id,r.sut?.name,r.model,r._dir].join(' ').toLowerCase().includes(kw))return false;
    return true});
  renderRuns(filtered);
}
{
  const cases=[...new Set(allRuns.map(r=>baseCase(r.case_id)).filter(Boolean))].sort();
  $("#fCase").innerHTML+='<option>'+cases.join('</option><option>')+'</option>';
  ["#fText","#fCase","#fVariant","#fVerdict"].forEach(s=>{
    const el=$(s);el.addEventListener(el.tagName==='INPUT'?'input':'change',applyFilters)});
  renderRuns(allRuns);
}

/* ===== 自由配对对比 ===== */
const pairDiff=(ra,rb)=>{
  const A=ra?ra._assertions:[],B=rb?rb._assertions:[];
  const dims=[...new Set([...A.map(a=>a.desc),...B.map(a=>a.desc)])];
  const rows=dims.map(d=>{
    const p=A.find(a=>a.desc===d),q=B.find(a=>a.desc===d);
    const x=p?.pass,y=q?.pass;
    let chg='<span style="color:var(--mw-muted)">不变</span>';
    if(x===false&&y===true)chg='<span class="badge b-pass">↑ 提升</span>';
    else if(x===true&&y===false)chg='<span class="badge b-fail">↓ 退化</span>';
    else if(x===undefined&&y!==undefined)chg='<span class="badge b-sev-low">仅 B 有</span>';
    else if(y===undefined&&x!==undefined)chg='<span class="badge b-sev-low">仅 A 有</span>';
    let row=`<tr><td class="reason">${esc(d)}</td><td>${x===undefined?'—':badgePass(x)}</td><td>${y===undefined?'—':badgePass(y)}</td><td>${chg}</td></tr>`;
    if(x===false||y===false){
      const fr=(x===false?p?.reason:'')||(y===false?q?.reason:'')||'';
      if(fr)row+=`<tr><td colspan="4" style="padding:2px 8px 6px 24px;color:var(--mw-muted);font-size:12px">↳ ${esc(fr.slice(0,150))}</td></tr>`;
    }
    return row}).join("");
  const head=(lbl,run)=>run?`${lbl}: <b>${esc(run.title)}</b> <span class="reason">${esc(run.case_id)} · ${esc(run.date)} · ${esc(run.sut.name)} · ${esc(run.sut.variant||'')}</span>`:`${lbl}: —`;
  return `<div class="kv">${head('A',ra)}</div><div class="kv">${head('B',rb)}</div>`+
    (dims.length?`<table><tr><th>断言维度</th><th>A</th><th>B</th><th>变化</th></tr>${rows}</table>`:'<div class="empty">所选运行缺少断言数据</div>');
};
const runLabel=r=>`${r.case_id} · ${r.date} · ${(r.sut?.variant||'?')} · ${r.verdict} · ${r._dir}`;
function initPair(){
  const opts=allRuns.map((r,i)=>`<option value="${i}">${esc(runLabel(r))}</option>`).join("");
  $("#cmpA").innerHTML=opts;$("#cmpB").innerHTML=opts;
  const baseIdx=allRuns.findIndex(r=>/^(td-01|cr-04)-formal-r1$/.test(r._dir));
  const optIdx=allRuns.findIndex(r=>/-opt-formal-r5(\-retry\d+)?$/.test(r._dir));
  $("#cmpA").value=Math.max(baseIdx,0);$("#cmpB").value=optIdx>=0?optIdx:allRuns.length-1;
  const upd=()=>{$("#customPair").innerHTML=pairDiff(allRuns[+$("#cmpA").value],allRuns[+$("#cmpB").value])};
  $("#cmpA").onchange=upd;$("#cmpB").onchange=upd;upd();
}
initPair();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
