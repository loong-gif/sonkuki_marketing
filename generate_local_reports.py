"""Render the validated Sonkuki GSC artifact as local HTML and Markdown."""
from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "sonkuki_gsc_analysis"


def pct(v):
    return f"{v * 100:.1f}%"


def num(v):
    return f"{v:,.0f}"


def table(headers, rows):
    head = "<tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in headers) + "</tr>"
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in row) + "</tr>" for row in rows)
    return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"


def bar_rows(rows, label, value, formatter=num):
    maximum = max((r.get(value, 0) for r in rows), default=1) or 1
    return "".join(
        f'<div class="bar-row"><span>{html.escape(str(r.get(label, "")))}</span>'
        f'<div class="bar"><i style="width:{r.get(value, 0) / maximum * 100:.1f}%"></i></div>'
        f'<b>{formatter(r.get(value, 0))}</b></div>'
        for r in rows
    )


def main():
    artifact = json.loads((OUT / "artifact.json").read_text(encoding="utf-8"))
    summary = json.loads((OUT / "analysis_summary.json").read_text(encoding="utf-8"))
    m = summary["metrics"]
    profile = summary["profile"]
    brand = summary["brand_mix"]
    intents = summary["intent_mix"]
    themes = summary["theme_mix"]
    pages = summary["landing_pages"][:15]
    opps = summary["opportunities"][:15]
    quality = artifact["snapshot"]["datasets"]["data_quality"]
    brand_share = next(x["clicks"] for x in brand if x["brand_class"] == "品牌") / m["total_clicks"]
    top_page = pages[0]
    top_theme = themes[0]["theme"]
    top_intent = intents[0]["intent"]

    md = f"""# SONKUKI 自然搜索流量与市场机会

## Executive Summary

- 数据覆盖 **{profile['date_min']} 至 {profile['date_max']}**，共 **{num(m['row_count'])} 行**。
- 自然搜索获得 **{num(m['total_clicks'])} 点击**、**{num(m['total_impressions'])} 曝光**，加权 CTR **{pct(m['overall_ctr'])}**，曝光加权排名 **{m['weighted_position']:.2f}**。
- 品牌词贡献 **{pct(brand_share)}** 的点击；非品牌点击仅 {num(m['total_clicks'] - next(x['clicks'] for x in brand if x['brand_class'] == '品牌'))}，说明新增获客能力仍是主要增长空间。
- 点击最多的产品主题为 **{top_theme}**，点击最多的搜索意图为 **{top_intent}**。
- 首要入口页为 `{top_page['page_label']}`，获得 {num(top_page['clicks'])} 点击、{num(top_page['impressions'])} 曝光。

## 数据边界与定义

- 原始粒度：`site + date + page + query`；重复粒度行：{m['duplicate_grain_rows']}。
- 原始 URL：{m['raw_page_count']}；规范页面：{m['canonical_page_count']}；原始查询：{m['raw_query_count']}；规范查询：{m['query_count']}。
- CTR 统一按 `sum(clicks) / sum(impressions)` 重算；排名按曝光加权。
- 缺失日期：{', '.join(profile['missing_dates'])}；不按零点击插补，趋势仅使用完整周。
- {m['suspicious_query_rows']} 行客服号码/外部域名等明显非目标查询保留在总量中，但不纳入意图、主题和机会排序。

## 品牌与非品牌

| 类型 | 点击 | 曝光 | CTR | 加权排名 |
|---|---:|---:|---:|---:|
""" + "\n".join(f"| {x['brand_class']} | {num(x['clicks'])} | {num(x['impressions'])} | {pct(x['ctr'])} | {x['weighted_position']:.2f} |" for x in brand) + "\n\n"
    md += "## 搜索意图\n\n| 意图 | 点击 | 曝光 | CTR | 加权排名 |\n|---|---:|---:|---:|---:|\n"
    md += "\n".join(f"| {x['intent']} | {num(x['clicks'])} | {num(x['impressions'])} | {pct(x['ctr'])} | {x['weighted_position']:.2f} |" for x in intents) + "\n\n"
    md += "## 产品主题\n\n| 主题 | 点击 | 曝光 | CTR | 加权排名 |\n|---|---:|---:|---:|---:|\n"
    md += "\n".join(f"| {x['theme']} | {num(x['clicks'])} | {num(x['impressions'])} | {pct(x['ctr'])} | {x['weighted_position']:.2f} |" for x in themes) + "\n\n"
    md += "## 主要入口页\n\n| 页面 | 点击 | 曝光 | CTR | 加权排名 |\n|---|---:|---:|---:|---:|\n"
    md += "\n".join(f"| `{x['page_label']}` | {num(x['clicks'])} | {num(x['impressions'])} | {pct(x['ctr'])} | {x['weighted_position']:.2f} |" for x in pages) + "\n\n"
    md += "## 优先机会\n\n| 查询簇 | 页面 | 问题类型 | 曝光 | 点击 | CTR | 排名 | 建议动作 |\n|---|---|---|---:|---:|---:|---:|---|\n"
    md += "\n".join(f"| {x['normalized_query']} | `{x['canonical_page']}` | {x['issue']} | {num(x['impressions'])} | {num(x['clicks'])} | {pct(x['ctr'])} | {x['weighted_position']:.2f} | {x['action']} |" for x in opps) + "\n\n"
    md += "## 建议行动\n\n1. 将品牌与非品牌 SEO KPI 分开，避免品牌需求掩盖非品牌增长。\n2. 优先优化高曝光、排名 4–20 且 CTR 偏低的页面。\n3. 用尺寸、LED、材质、安装/排水、底座和评价 FAQ 承接购买决策。\n4. 统一规范 URL，减少参数页分散。\n5. 在安全连接成立后接入 GA4/订单汇总，验证商业结果。\n\n## 局限\n\nGSC 只能提供曝光、点击、CTR、排名和搜索意图代理信号，不能直接证明市场规模、订单归因或因果关系。数据库增强未执行，因为现有连接为明文 HTTP。\n"
    (OUT / "sonkuki_gsc_report.md").write_text(md, encoding="utf-8")

    css = """
    :root{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17202a;background:#f5f7fb}
    body{max-width:1200px;margin:0 auto;padding:32px 20px;line-height:1.55}.hero{background:#11263d;color:#fff;padding:32px;border-radius:18px;margin-bottom:20px}.hero h1{margin:0 0 8px;font-size:32px}.muted{color:#667085}.hero .muted{color:#cbd5e1}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,section{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;margin:14px 0;box-shadow:0 3px 14px #17202a0a}.card b{display:block;font-size:28px;color:#0b7285}.card span{color:#667085;font-size:13px}h2{margin-top:4px;color:#11263d}.bar-row{display:grid;grid-template-columns:130px 1fr 80px;gap:10px;align-items:center;margin:9px 0}.bar{height:12px;background:#e8eef2;border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:#0b7285;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:13px;display:block;overflow-x:auto}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #edf0f2;vertical-align:top}th{background:#f8fafc;white-space:nowrap}.note{background:#eef8f7;border-left:4px solid #0b7285;padding:12px 14px}.pill{display:inline-block;background:#e6fffb;color:#087f7b;border-radius:20px;padding:3px 9px;margin:2px;font-size:12px}@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}.bar-row{grid-template-columns:100px 1fr 60px;font-size:12px}}@media(max-width:480px){body{padding:16px 10px}.grid{grid-template-columns:1fr 1fr}.hero h1{font-size:24px}.card b{font-size:22px}}
    """
    h = artifact["manifest"]["generatedAt"]
    html_doc = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SONKUKI GSC 自然搜索报告</title><style>{css}</style></head><body>
    <header class="hero"><h1>SONKUKI 自然搜索流量与市场机会</h1><div class="muted">GSC 静态快照：{profile['date_min']} 至 {profile['date_max']} · 生成于 {h}</div></header>
    <div class="grid"><div class="card"><span>自然点击</span><b>{num(m['total_clicks'])}</b></div><div class="card"><span>自然曝光</span><b>{num(m['total_impressions'])}</b></div><div class="card"><span>加权 CTR</span><b>{pct(m['overall_ctr'])}</b></div><div class="card"><span>曝光加权排名</span><b>{m['weighted_position']:.2f}</b></div></div>
    <section><h2>Executive Summary</h2><div class="note">品牌点击占 {pct(brand_share)}；主要产品主题为 {html.escape(top_theme)}，主要搜索意图为 {html.escape(top_intent)}。结论是搜索需求代理信号，不是订单因果结论。</div><p>总量保留 {m['suspicious_query_rows']} 行明显非目标查询（{num(m['suspicious_query_impressions'])} 曝光），这些查询已从市场意图、主题和机会表隔离。</p></section>
    <section><h2>品牌与非品牌点击</h2>{bar_rows(brand,'brand_class','clicks')}<p class="muted">品牌词贡献 {pct(brand_share)} 的点击；非品牌排名和 CTR 明显较弱，是主要 SEO 增长空间。</p></section>
    <section><h2>搜索意图点击</h2>{bar_rows(intents,'intent','clicks')}</section>
    <section><h2>产品主题曝光</h2>{bar_rows(themes,'theme','impressions')}</section>
    <section><h2>主要入口页面</h2>{table(['规范页面','点击','曝光','CTR','加权排名'], [[x['canonical_page'],num(x['clicks']),num(x['impressions']),pct(x['ctr']),f"{x['weighted_position']:.2f}"] for x in pages])}</section>
    <section><h2>优先机会</h2>{table(['查询簇','规范页面','问题类型','曝光','点击','CTR','排名','建议动作'], [[x['normalized_query'],x['canonical_page'],x['issue'],num(x['impressions']),num(x['clicks']),pct(x['ctr']),f"{x['weighted_position']:.2f}",x['action']] for x in opps])}</section>
    <section><h2>数据质量与边界</h2>{table(['检查','结果','证据','影响'], [[x['check'],x['result'],x['evidence'],x['risk']] for x in quality])}<p class="muted">缺失日期：{', '.join(profile['missing_dates'])}。缺失日未按零点击插补；数据库增强未执行，因为现有连接为明文 HTTP。</p></section>
    </body></html>'''
    (OUT / "sonkuki_gsc_report.html").write_text(html_doc, encoding="utf-8")
    print({"markdown": str(OUT / "sonkuki_gsc_report.md"), "html": str(OUT / "sonkuki_gsc_report.html")})


if __name__ == "__main__":
    main()
