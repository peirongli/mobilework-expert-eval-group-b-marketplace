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
  python build_web.py                          # 默认生成 <eval>/web/index.html
  python build_web.py --accent "#0052d9"       # 换主题色
  python build_web.py --title "B 组评测报告"    # 换标题
生成完成后打印 file:// URL，可直接粘贴到 OpenWork 内置浏览器打开。
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

EVAL_ROOT = Path(os.environ.get(
    "MOBILEWORK_EVAL_ROOT", Path.home() / "Desktop/MobileWork/eval")).resolve()
RESULTS = EVAL_ROOT / "results"
PACKAGES = EVAL_ROOT / "packages"
PROVENANCE = EVAL_ROOT / "records" / "provenance"
WEB_DIR = EVAL_ROOT / "web"
OUT = WEB_DIR / "index.html"
DS = EVAL_ROOT.parent / "MobileWork-Design-System"

ASSETS = [
    (DS / "assets" / "china-mobile-logo.png", "china-mobile-logo.png"),
    (DS / "logos" / "favicon.ico", "favicon.ico"),
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


def main():
    ap = argparse.ArgumentParser(description="本地结果 Web 生成器（agent 可调起）")
    ap.add_argument("--title", default="MobileWork 专家（团）评测结果 · B 组",
                    help="页面标题（header h1 与 <title>）")
    ap.add_argument("--accent", default="#1890ff",
                    help="主题色 hex（如 #0052d9），驱动全套派生色")
    args = ap.parse_args()

    sync_assets()
    runs = load_runs()
    if not runs:
        print("!! eval/results/ 下没有含 meta.json 的运行记录", file=sys.stderr)
        sys.exit(1)
    payload = {
        "generated_by": "group-b-expert-eval build_web.py（只读结果界面，无执行入口）",
        "runs": runs,
        "findings": load_findings(),
        "objects": load_objects(runs),
        "stats": build_stats(runs),
        "comparisons": build_comparisons(runs),
        "advice": load_advice(),
    }
    # 防御性 XSS 防护:把 < 替换为 \u003c(避免交付物里的 XSS 示例被 HTML 解析器误执行)
    data_js = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("</", "<\\/")
    page = (TEMPLATE
            .replace("/*__DATA__*/", f"const DATA = {data_js};")
            .replace("__PAGE_TITLE__", args.title)
            .replace("__ACCENT__", args.accent))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"OK -> {OUT}  (runs={len(runs)}, findings={len(payload['findings'])})")
    print(f"在 OpenWork 内置浏览器或本机浏览器打开:\n  file://{OUT}")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="assets/favicon.ico">
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
    <h2>被测对象（点击展开介绍）</h2><div id="sutList"></div>
    <h2>运行分布（按被测对象）</h2><div id="distSut"></div>
    <h2>运行分布（按模型 / 变体）</h2><div id="distModel"></div>
  </section>
  <section class="view" id="v-runs"><div id="runList"></div></section>
  <section class="view" id="v-findings"><div id="findingList"></div></section>
  <section class="view" id="v-compare"><div id="compareBox"></div></section>
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
const dist=o=>`<table><tr><th>项</th><th>次数</th></tr>${Object.entries(o).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join("")}</table>`;
$("#distSut").innerHTML=dist(st.by_sut);
$("#distModel").innerHTML=dist({...Object.fromEntries(Object.entries(st.by_model).map(([k,v])=>["模型: "+k,v])),...Object.fromEntries(Object.entries(st.by_variant).map(([k,v])=>["变体: "+k,v]))});
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
$("#runList").innerHTML=DATA.runs.map(r=>{
  const asserts=r._assertions.map(a=>`<tr><td>${badgePass(a.pass)}</td><td>${esc(a.desc)}</td><td>${esc(a.type)}</td><td class="reason">${esc(a.reason)}</td></tr>`).join("");
  const dels=(r.process?.delegations||[]).map(d=>`<tr><td>${esc(d.stage)}</td><td>${esc(d.agent)}</td><td style="font-family:var(--mono);font-size:11px">${esc(d.session)}</td><td>${esc(d.acceptance)}</td></tr>`).join("");
  const anom=(r.anomalies||[]).map(id=>{const f=DATA.findings.find(x=>x.id===id);return f?`<span class="badge b-sev-mid">${f.id} ${esc(f.title)}</span>`:id}).join(" ");
  return `<div class="run"><div class="run-head" onclick="this.parentNode.classList.toggle('open')">
    ${badgePass(r.verdict==='pass')}
    <span class="t">${esc(r.title)}</span><span class="meta">${esc(r.case_id)} · ${esc(r.date)} · ${esc(r.sut.name)}@${esc(r.sut.commit||'')} · ${esc(r.model)}</span></div>
  <div class="run-body">
    <div class="kv"><b>输入</b>　${esc(r.input)}</div>
    <div class="kv"><b>宿主</b>　${esc(r.host)} ｜ <b>声明自主度</b>　${esc(r.process?.autonomy_declared||'')} ｜ <b>返工</b>　${r.process?.rework_count??'—'}</div>
    ${dels?`<h2>委派关系与验收</h2><table><tr><th>阶段</th><th>执行者</th><th>子会话</th><th>验收</th></tr>${dels}</table>`:""}
    <div class="kv"><b>终审</b>　${esc(r.process?.final_review||'')}</div>
    <div class="kv"><b>权限决策证据</b>　${esc(r.process?.permission_evidence||'')}</div>
    ${asserts?`<h2>Promptfoo 评分（${r._assertions.filter(a=>a.pass).length}/${r._assertions.length}）</h2><table><tr><th></th><th>维度</th><th>类型</th><th>评分理由</th></tr>${asserts}</table>`:""}
    ${r._deliverable_text?`<h2>交付物（${esc(r.deliverable)}）</h2><pre>${esc(r._deliverable_text)}</pre>`:""}
    ${anom?`<div class="kv"><b>关联异常</b>　${anom}</div>`:""}
    ${r.human_notes?`<div class="kv"><b>备注</b>　${esc(r.human_notes)}</div>`:""}
  </div></div>`}).join("")||'<div class="empty">暂无运行记录</div>';
$("#findingList").innerHTML=`<table><tr><th>ID</th><th>严重度</th><th>标题</th><th>状态</th><th>详情</th></tr>${DATA.findings.map(f=>`<tr><td>${f.id}</td><td><span class="badge ${f.severity==='高'?'b-sev-high':f.severity==='中'?'b-sev-mid':'b-sev-low'}">${f.severity==='高'?'! ':f.severity==='中'?'● ':'○ '}${esc(f.severity)}</span></td><td>${esc(f.title)}</td><td>${esc(f.status)}</td><td class="reason">${esc(f.detail)}</td></tr>`).join("")}</table>`;
const cmp=Object.entries(DATA.comparisons);
const getRun=dir=>DATA.runs.find(r=>r["_dir"]===dir);
$("#compareBox").innerHTML=cmp.length?cmp.map(([name,g])=>{
  const blRun=g.baseline?getRun(g.baseline.run):null, optRun=g.optimized?getRun(g.optimized.run):null;
  const blA=blRun?(blRun["_assertions"]||[]):[], optA=optRun?(optRun["_assertions"]||[]):[];
  const allDids=[...new Set([...blA.map(a=>a.desc),...optA.map(a=>a.desc)])];
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
  return `<h2>${esc(name)} <span style="font-weight:400;color:var(--mw-muted);font-size:13px">${esc(CASE_INFO[name]||'')}</span></h2><table><tr><th>变体</th><th>版本</th><th>评分</th><th>结论</th><th>运行</th><th>耗时</th></tr>${mainRows}</table>${assertRows?`<table style="margin-top:4px"><tr><th>断言维度</th><th>基线</th><th>优化</th><th>变化</th></tr>${assertRows}</table>`:""}${blockedNote}${!g.optimized?'<div class="empty">优化副本尚未产生</div>':""}`;
}).join(""):'<div class="empty">暂无数据</div>';
const adv=DATA.advice||[];
const stB=s=>s==='applied'?'b-pass':s==='rejected'?'b-fail':'b-sev-mid';
const stI=s=>s==='applied'?'✓ ':s==='rejected'?'✗ ':'● ';
const advTable=adv.length?`<table><tr><th>ID</th><th>Case</th><th>建议</th><th>状态</th><th>评审人</th><th>日期</th><th>关联复测</th></tr>${adv.map(a=>`<tr><td>${esc(a.id)}</td><td>${esc(a.case_id)}</td><td class="reason">${esc(a.advice)}</td><td><span class="badge ${stB(a.status)}">${stI(a.status)}${esc(a.status)}</span>${a.draft?' <span class="badge b-sev-low">draft</span>':''}</td><td>${esc(a.submitted_by||'')}</td><td>${esc(a.date||'')}</td><td>${esc(a.linked_run||'—')}</td></tr>`).join("")}</table>`:'';
const sugg=DATA.runs.flatMap(r=>(r.suggestions||[]).map(s=>[r.case_id,s]));
$("#notesBox").innerHTML=advTable+(sugg.length?`<h2>运行内自动备注（非人工提交，供评审参考）</h2><ul class="clean">${sugg.map(([c,s])=>`<li><b>[${esc(c)}]</b> ${esc(s)}</li>`).join("")}</ul>`:(adv.length?'':'<div class="empty">暂无人工建议</div>'));
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
