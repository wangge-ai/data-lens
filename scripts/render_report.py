from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, file_sha256, guard_cli_output, load_json, write_json
from validate_deep_analysis import validate_analysis


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def human_class(value: str | None) -> str:
    return {"fact": "事实", "calculation": "数据结果", "inference": "分析判断", "hypothesis": "待验证"}.get(value or "", value or "分析判断")


def human_confidence(value: str | None) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value or "", value or "未标注")


def human_route(value: str | None) -> str:
    return {
        "same_author_content": "同一作者内容拆解",
        "account_content_performance": "账号内容与表现复盘",
        "method_corpus": "方法与打法归纳",
        "mixed_corpus": "混合资料分析",
        "repeated_operational_tables": "连续经营表格分析",
        "novel_route": "新类型试验分析",
    }.get(value or "", value or "未确认")


def human_depth(value: str | None) -> str:
    return {"brief": "快速试验", "standard": "标准分析", "deep": "深度分析"}.get(value or "", value or "未确认")


def human_analysis_unit(value: str | None) -> str:
    return {
        "file": "文件",
        "document": "文档",
        "source_container": "来源容器",
        "article": "文章",
        "article_with_confirmed_metrics": "已匹配后台指标的文章",
        "atomic_method_claim": "单条方法主张",
        "family_specific": "按各类资料自己的分析单位",
        "business_date_x_platform": "业务日期 × 平台",
        "lesson_or_chapter": "课程或章节",
        "comment": "评论",
        "note": "笔记",
        "workbook": "工作簿",
        "image_sequence_candidate": "候选图片序列",
        "pilot_defined": "试验后确定",
    }.get(value or "", value or "未确认")


def human_metric_type(value: str | None) -> str:
    return {
        "exact": "精确指标",
        "proxy": "代理指标",
        "descriptive_count": "描述性计数",
    }.get(value or "", value or "未标注")


def human_unit_status(value: str | None) -> str:
    return {
        "confirmed": "已确认",
        "provisional": "暂定，仍需确认",
        "provisional_requires_semantic_confirmation": "暂定，仍需语义确认",
    }.get(value or "", value or "未确认")


def human_processing_state(value: str) -> str:
    return {
        "parsed": "已解析",
        "source_only": "仅记录来源",
        "pixel_readable": "图片可读取",
        "semantic_reviewed": "已完成语义审阅",
        "unreadable": "无法读取",
        "excluded": "已排除",
    }.get(value, value)


def join_text(values: list[Any]) -> str:
    return "".join(f"<li>{esc(value)}</li>" for value in values)


def evidence_refs(ids: list[str], evidence_map: dict[str, dict[str, Any]]) -> str:
    labels = []
    for evidence_id in ids:
        item = evidence_map.get(evidence_id, {})
        label = item.get("label") or item.get("note") or evidence_id
        labels.append(f'<span class="evidence-source">{esc(label)}</span>')
    return "".join(labels) or '<span class="empty-state">暂无可展示依据</span>'


def route_copy(route: str) -> dict[str, str]:
    if route in {"same_author_content", "account_content_performance"}:
        return {
            "toc_middle": "看内容表现", "toc_comparisons": "最值得看的文章对比", "toc_actions": "下一批文章怎么做",
            "summary_note": "先看会影响下一步内容决策的结果，再往下看文章对比和具体原因。",
            "scope_note": "先把能比较的文章和暂时缺少的数据说清楚，避免把未知当成零。",
            "findings_title": "账号目前最重要的几个发现",
            "comparisons_title": "最值得看的文章对比",
            "comparisons_note": "把任务相近、表现差异较大的文章放在一起，更容易看见可复用的写法。",
            "actions_title": "下一批文章具体怎么做",
        }
    return {
        "toc_middle": "看清区别和关系", "toc_comparisons": "几个容易混淆的区别", "toc_actions": "接下来怎么做",
        "summary_note": "先看会影响下一步判断的结果，再往下看依据、差异和适用边界。",
        "scope_note": "先把哪些资料可以比较、哪些暂时不能合并说清楚，避免把未知当成结论。",
        "findings_title": "最值得记住的判断",
        "comparisons_title": "几个容易混淆的区别",
        "comparisons_note": "把用途相近但角色不同的资料放在一起，才能看见真正可复用的部分。",
        "actions_title": "接下来怎么改",
    }


def render_toc(presentation: dict[str, Any], sections: list[dict[str, Any]], route: str = "") -> str:
    groups = presentation.get("toc_groups")
    if not groups:
        copy = route_copy(route)
        groups = [
            {"label": "先看结论", "items": [{"anchor": "summary", "label": "最重要的结论"}, {"anchor": "findings", "label": "六个关键发现"}]},
            {"label": copy["toc_middle"], "items": [{"anchor": "comparisons", "label": copy["toc_comparisons"]}, *[{"anchor": f'section-{item.get("id")}', "label": item.get("title")} for item in sections]]},
            {"label": "决定下一步", "items": [{"anchor": "actions", "label": copy["toc_actions"]}]},
        ]
    rendered = []
    for group in groups:
        items = "".join(f'<li><a href="#{esc(item.get("anchor"))}">{esc(item.get("label"))}</a></li>' for item in group.get("items", []))
        rendered.append(f'<section class="toc-group"><h2>{esc(group.get("label"))}</h2><ul>{items}</ul></section>')
    return "".join(rendered)


def human_lane(value: str) -> str:
    return {
        "content_text": "正文与文档",
        "performance_table": "后台表现数据",
        "tabular_data": "尚待分表确认的表格",
        "visual_layout": "封面与页面视觉",
        "audience_voice": "评论与用户反馈",
        "temporal_metadata": "发布时间",
        "audio_video": "音视频内容",
        "source_metadata": "来源信息",
    }.get(value, value)


def human_coverage_status(value: str) -> str:
    return {
        "available": "可用",
        "partial": "部分可用",
        "uninspected": "尚未实际检查",
        "missing": "缺少",
        "not_required": "本次不需要",
    }.get(value, value)


def numeric_count(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:份|篇|张|条|行|个|项|页|段|文件)?\s*", str(value or ""))
    return float(match.group(1)) if match else None


def render_coverage(
    sampling: dict[str, Any], coverage: list[dict[str, Any]], units: dict[str, Any] | None = None,
    metrics: list[dict[str, Any]] | None = None,
) -> str:
    units = units or {}
    metrics = metrics or []
    warnings = "".join(f"<li>{esc(value)}</li>" for value in sampling.get("bias_warnings", []))
    rows = []
    for item in coverage:
        rows.append(
            '<article class="coverage-row">'
            f'<div><strong>{esc(human_lane(str(item.get("lane", ""))))}</strong><span class="coverage-status">{esc(human_coverage_status(str(item.get("status", ""))))} · {esc(item.get("items"))}</span></div>'
            f'<p><b>能说明：</b>{esc(item.get("proves"))}</p><p><b>不能说明：</b>{esc(item.get("cannot_prove"))}</p>'
            '</article>'
        )
    exclusions = sampling.get("exclusions") or {}
    exclusion_text = "；".join(f"{key} {value}" for key, value in exclusions.items()) if isinstance(exclusions, dict) else "；".join(str(value) for value in exclusions)
    sample = (
        '<div class="sample-rule">'
        f'<p><strong>怎么选的：</strong>{esc(sampling.get("inclusion_rule", "未记录"))}</p>'
        f'<dl><div><dt>候选范围</dt><dd>{esc(sampling.get("eligible_count", "—"))}</dd></div><div><dt>实际分析</dt><dd>{esc(sampling.get("selected_count", "—"))}</dd></div><div><dt>排除情况</dt><dd>{esc(exclusion_text or "无额外排除")}</dd></div></dl>'
        + (f'<div class="sample-warnings"><strong>样本偏差</strong><ul>{warnings}</ul></div>' if warnings else "")
        + '</div>'
    )
    unit_block = ""
    if units:
        unit_block = (
            '<div class="sample-rule">'
            f'<p><strong>真正按什么比较：</strong>{esc(human_analysis_unit(str(units.get("analysis_unit") or "")))}（{esc(human_unit_status(str(units.get("unit_status") or "")))}）</p>'
            f'<dl><div><dt>来源文件或容器</dt><dd>{esc(units.get("source_container_count", "—"))}</dd></div>'
            f'<div><dt>可纳入单元</dt><dd>{esc(units.get("eligible_count", "—"))}</dd></div>'
            f'<div><dt>实际观察单元</dt><dd>{esc(units.get("observed_count", "—"))}</dd></div></dl>'
            f'<p><b>去重和分组：</b>{esc(units.get("deduplication_rule", "未记录"))}；{esc(units.get("grouping_rule", "未记录"))}</p>'
            '</div>'
        )
    metric_rows = ""
    if metrics:
        rendered_metrics = []
        for metric in metrics:
            rendered_metrics.append(
                '<article class="coverage-row">'
                f'<div><strong>{esc(metric.get("label"))}</strong><span class="coverage-status">{esc(metric.get("unit"))} · {esc(human_metric_type(str(metric.get("metric_type") or "")))}</span></div>'
                f'<p><b>怎么算：</b>{esc(metric.get("numerator"))} ÷ {esc(metric.get("denominator"))}</p>'
                f'<p><b>不能当成：</b>{esc(metric.get("interpretation_limit"))}</p>'
                '</article>'
            )
        metric_rows = '<div class="coverage-list">' + "".join(rendered_metrics) + '</div>'
    return sample + unit_block + f'<div class="coverage-list">{"".join(rows)}</div>' + metric_rows


def format_scope(scope: dict[str, Any]) -> str:
    entries = [
        ("决策问题", scope.get("decision_question")),
        ("资料范围", scope.get("corpus_summary")),
        ("时间范围", scope.get("time_range")),
        ("比较单位", human_analysis_unit(str(scope.get("comparison_unit") or ""))),
        ("纳入口径", scope.get("eligibility_rule")),
    ]
    return "".join(f'<div class="scope-row"><dt>{esc(label)}</dt><dd>{esc(value or "未记录")}</dd></div>' for label, value in entries)


def render_summary(items: list[dict[str, Any]], evidence_map: dict[str, dict[str, Any]]) -> str:
    rendered = []
    for index, item in enumerate(items, start=1):
        rendered.append(
            '<article class="summary-item">'
            f'<span class="summary-number">{index:02d}</span>'
            f'<div><h3>{esc(item.get("title"))}</h3><p>{esc(item.get("summary"))}</p>'
            f'<div class="inline-meta"><span class="class-tag">{esc(human_class(item.get("classification", "inference")))}</span>'
            f'{evidence_refs(item.get("evidence_ids", []), evidence_map)}</div></div></article>'
        )
    return "".join(rendered)


def render_overview_charts(data: dict[str, Any]) -> str:
    coverage = [
        (item, numeric_count(item.get("items")))
        for item in data.get("evidence_coverage", [])
        if item.get("lane") != "source_metadata" and numeric_count(item.get("items")) is not None
    ]
    max_items = max((value or 0 for _, value in coverage), default=0.0)
    coverage_rows = []
    for item, value in coverage:
        value = value or 0
        width = 0 if max_items <= 0 else max(3, round(value / max_items * 100))
        coverage_rows.append(
            '<li><span>' + esc(human_lane(str(item.get("lane") or ""))) + '</span>'
            f'<div class="bar-track"><i style="width:{width}%"></i></div><b>{esc(item.get("items"))}</b></li>'
        )
    classification_order = [("fact", "事实"), ("calculation", "数据结果"), ("inference", "分析判断"), ("hypothesis", "待验证")]
    finding_counts = {key: sum(1 for item in data.get("findings", []) if item.get("classification") == key) for key, _ in classification_order}
    finding_total = max(1, sum(finding_counts.values()))
    finding_rows = []
    for key, label in classification_order:
        count = finding_counts[key]
        if count:
            finding_rows.append(
                f'<li><span>{esc(label)}</span><div class="bar-track"><i style="width:{round(count / finding_total * 100)}%"></i></div><b>{count}</b></li>'
            )
    priority_copy = {"now": "现在做", "next": "接着做", "later": "以后做"}
    priority_counts = {key: sum(1 for item in data.get("recommendations", []) if item.get("priority") == key) for key in priority_copy}
    priority_items = "".join(
        f'<div><span>{esc(label)}</span><strong>{priority_counts[key]}</strong></div>'
        for key, label in priority_copy.items() if priority_counts[key]
    )
    if not coverage_rows and not finding_rows and not priority_items:
        return ""
    priority_panel = f'<div class="priority-mini">{priority_items}</div>' if priority_items else '<p class="overview-empty">当前版本尚未给行动分级。</p>'
    return (
        '<section class="overview-visuals" aria-label="报告数据概览">'
        '<header><h2>一眼看清这次分析</h2><p>这里显示的是实际审阅规模、结论性质和行动优先级，不把文件数量当成共识。</p></header>'
        '<div class="overview-grid">'
        f'<article><h3>实际审阅的证据</h3><ol class="bar-list">{"".join(coverage_rows)}</ol></article>'
        f'<article><h3>结论由什么组成</h3><ol class="bar-list">{"".join(finding_rows)}</ol></article>'
        f'<article><h3>行动先后顺序</h3>{priority_panel}</article>'
        '</div></section>'
    )


def render_findings(items: list[dict[str, Any]], evidence_map: dict[str, dict[str, Any]], recommendation_map: dict[str, dict[str, Any]]) -> str:
    rendered = []
    for index, item in enumerate(items, start=1):
        rendered.append(
            '<article class="finding-record">'
            '<header class="record-header">'
            f'<span class="record-index">发现 {index:02d}</span><div><h3>{esc(item.get("title"))}</h3>'
            f'<div class="inline-meta"><span class="class-tag">{esc(human_class(item.get("classification")))}</span><span>把握程度：{esc(human_confidence(item.get("confidence")))}</span></div></div></header>'
            '<div class="reasoning-grid">'
            f'<div class="reason-row fact-row"><h4>事实</h4><p>{esc(item.get("fact"))}</p></div>'
            f'<div class="reason-row"><h4>证据</h4><div>{evidence_refs(item.get("evidence_ids", []), evidence_map)}</div></div>'
            f'<div class="reason-row"><h4>解释</h4><p>{esc(item.get("explanation"))}</p></div>'
            f'<div class="reason-row caution-row"><h4>反例</h4><ul>{join_text(item.get("counterexamples", []))}</ul></div>'
            f'<div class="reason-row boundary-row"><h4>边界</h4><ul>{join_text(item.get("boundaries", []))}</ul></div>'
            f'<div class="reason-row action-row"><h4>接下来做</h4><p>{"；".join(esc(recommendation_map.get(v, {}).get("title", v)) for v in item.get("recommendation_ids", [])) or "暂时不需要单独行动"}</p></div>'
            '</div></article>'
        )
    return "".join(rendered)


def render_comparisons(items: list[dict[str, Any]], evidence_map: dict[str, dict[str, Any]]) -> str:
    rendered = []
    for index, item in enumerate(items, start=1):
        sides = []
        for key, default_label in (("left", "样本 A"), ("right", "样本 B")):
            side = item.get(key, {})
            sides.append('<div class="comparison-side">' f'<span class="side-label">{esc(side.get("label", default_label))}</span>' f'<strong>{esc(side.get("value"))}</strong><p>{esc(side.get("body"))}</p></div>')
        rendered.append(
            '<article class="comparison-record">'
            f'<div class="record-kicker">对照 {index:02d}</div><h3>{esc(item.get("title"))}</h3>'
            f'<div class="comparison-grid">{"".join(sides)}</div>'
            f'<div class="comparison-note"><strong>解释</strong><p>{esc(item.get("interpretation"))}</p></div>'
            f'<div class="comparison-note caution"><strong>反例</strong><p>{esc(item.get("counterexample"))}</p></div>'
            f'<div class="comparison-note boundary"><strong>边界</strong><p>{esc(item.get("boundary"))}</p></div>'
            f'<div class="inline-meta">{evidence_refs(item.get("evidence_ids", []), evidence_map)}</div></article>'
        )
    return "".join(rendered)


def render_table(table: dict[str, Any]) -> str:
    columns = table.get("columns", [])
    head = "".join(f'<th scope="col">{esc(column.get("label"))}</th>' for column in columns)
    rows = []
    for row in table.get("rows", []):
        rows.append("<tr>" + "".join(f'<td>{esc(row.get(column.get("key"), "—"))}</td>' for column in columns) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def safe_gallery_src(value: Any) -> str:
    source = str(value or "").replace("\\", "/")
    if not re.fullmatch(r"[0-9A-Za-z_./-]+\.(?:png|jpe?g|webp|gif)", source, flags=re.I):
        return ""
    if source.startswith("/") or ":" in source or ".." in source.split("/"):
        return ""
    return source


def render_gallery(items: list[dict[str, Any]]) -> str:
    figures = []
    for item in items:
        source = safe_gallery_src(item.get("src"))
        if not source:
            continue
        fit = str(item.get("fit") or "contain")
        fit = fit if fit in {"contain", "cover"} else "contain"
        position = str(item.get("position") or "50% 50%")
        if not re.fullmatch(r"(?:\d{1,3}%|left|center|right) (?:\d{1,3}%|top|center|bottom)", position):
            position = "50% 50%"
        figures.append(
            '<figure class="visual-example">'
            f'<img class="fit-{fit}" style="object-position:{esc(position)}" src="{esc(source)}" alt="{esc(item.get("alt") or item.get("caption") or "视觉证据")}" loading="lazy">'
            f'<figcaption><strong>{esc(item.get("title"))}</strong><span>{esc(item.get("caption"))}</span></figcaption>'
            '</figure>'
        )
    return f'<div class="visual-gallery">{"".join(figures)}</div>' if figures else ""


def render_analysis_sections(items: list[dict[str, Any]], evidence_map: dict[str, dict[str, Any]]) -> str:
    rendered = []
    for section in items:
        blocks = []
        for item in section.get("items", []):
            boundary = item.get("boundary")
            blocks.append(
                '<article class="analysis-item">'
                f'<h3>{esc(item.get("title"))}</h3><p>{esc(item.get("body"))}</p>'
                f'<div class="inline-meta">{evidence_refs(item.get("evidence_ids", []), evidence_map)}</div>'
                + (f'<p class="item-boundary"><strong>边界：</strong>{esc(boundary)}</p>' if boundary else "")
                + '</article>'
            )
        gallery = render_gallery(section.get("gallery", []))
        table = render_table(section["table"]) if section.get("table") else ""
        rendered.append(
            f'<section class="analysis-module" id="section-{esc(section.get("id"))}">'
            f'<header><h2>{esc(section.get("title"))}</h2><p>{esc(section.get("summary"))}</p></header>'
            f'{gallery}{table}<div class="analysis-list">{"".join(blocks)}</div></section>'
        )
    return "".join(rendered)


def render_recommendations(items: list[dict[str, Any]], finding_map: dict[str, dict[str, Any]]) -> str:
    rendered = []
    for index, item in enumerate(items, start=1):
        rendered.append(
            '<article class="action-record">'
            f'<span class="action-number">{index:02d}</span><div><div class="action-title-row"><h3>{esc(item.get("title"))}</h3>'
            + (f'<span class="priority-tag priority-{esc(item.get("priority"))}">{esc({"now": "现在做", "next": "接着做", "later": "以后做"}.get(item.get("priority"), ""))}</span>' if item.get("priority") else "")
            + '</div>'
            f'<p class="action-command">{esc(item.get("action"))}</p><p><strong>理由：</strong>{esc(item.get("rationale"))}</p>'
            f'<dl class="action-details"><div><dt>看什么结果</dt><dd>{esc(item.get("validation_metric"))}</dd></div><div><dt>做多久</dt><dd>{esc(item.get("timebox"))}</dd></div><div><dt>解决什么问题</dt><dd>{esc("；".join(finding_map.get(v, {}).get("title", v) for v in item.get("finding_ids", [])))}</dd></div></dl>'
            f'<p class="risk"><strong>风险：</strong>{esc("；".join(item.get("risks", [])))}</p><p class="fallback"><strong>未达预期：</strong>{esc(item.get("fallback"))}</p>'
            '</div></article>'
        )
    return "".join(rendered)


def render_experiments(items: list[dict[str, Any]], finding_map: dict[str, dict[str, Any]]) -> str:
    rendered = []
    for index, item in enumerate(items, start=1):
        rendered.append(
            '<article class="experiment-record">'
            f'<span class="action-number">{index:02d}</span><div><h3>{esc(item.get("title"))}</h3>'
            f'<p class="experiment-question">{esc(item.get("question"))}</p>'
            '<div class="experiment-grid">'
            f'<div><h4>要验证的假设</h4><p>{esc(item.get("hypothesis"))}</p></div>'
            f'<div><h4>只改变什么</h4><p>{esc(item.get("changed_variable"))}</p></div>'
            f'<div><h4>怎么对照</h4><p>{esc(item.get("comparison_design"))}</p></div>'
            f'<div><h4>原来的基线</h4><p>{esc(item.get("baseline"))}</p></div>'
            '</div>'
            f'<dl class="experiment-details"><div><dt>主指标</dt><dd>{esc(item.get("primary_metric"))}</dd></div><div><dt>保护指标</dt><dd>{esc("；".join(item.get("guardrail_metrics", [])))}</dd></div><div><dt>观察周期</dt><dd>{esc(item.get("measurement_window"))}</dd></div><div><dt>最少样本</dt><dd>{esc(item.get("minimum_sample"))}</dd></div></dl>'
            f'<p><strong>判定规则：</strong>{esc(item.get("decision_rule"))}</p>'
            f'<p><strong>需要记录：</strong>{esc("；".join(item.get("required_data", [])))}</p>'
            f'<p class="risk"><strong>可能干扰：</strong>{esc("；".join(item.get("confounders", [])))}</p>'
            f'<p class="fallback"><strong>停止条件：</strong>{esc(item.get("stop_condition"))}</p>'
            f'<p class="experiment-links"><strong>对应发现：</strong>{esc("；".join(finding_map.get(v, {}).get("title", v) for v in item.get("linked_finding_ids", [])))}</p>'
            '</div></article>'
        )
    return "".join(rendered)


def render_evidence_index(items: list[dict[str, Any]]) -> str:
    rendered = []
    for item in items:
        locator = item.get("locator", {})
        position = locator.get("pointer") or (f'{locator.get("start")}-{locator.get("end")}' if locator.get("type") == "line_range" else f'row {locator.get("row")}' if locator.get("type") == "csv_row" else locator.get("region", ""))
        rendered.append(
            f'<div class="evidence-record" id="evidence-{esc(item.get("id"))}"><dt>{esc(item.get("id"))}</dt>'
            f'<dd><strong>{esc(item.get("label") or item.get("note"))}</strong><span>{esc(Path(item.get("source_path", "")).name)} · {esc(locator.get("type"))} {esc(position)}</span>'
            + (f'<blockquote>{esc(item.get("quote"))}</blockquote>' if item.get("quote") else "") + '</dd></div>'
        )
    return "".join(rendered)


def render_html(data: dict[str, Any], css: str, run_context: dict[str, Any] | None = None) -> str:
    evidence_map = {item["id"]: item for item in data.get("evidence", [])}
    recommendation_map = {item["id"]: item for item in data.get("recommendations", [])}
    finding_map = {item["id"]: item for item in data.get("findings", [])}
    sections = data.get("analysis_sections", [])
    presentation = data.get("presentation", {})
    labels = presentation.get("section_labels", {})
    copy = route_copy(str(data.get("route") or ""))
    toc_html = render_toc(presentation, sections, str(data.get("route") or ""))
    limitations = "".join(f'<li>{esc(item)}</li>' for item in data.get("limitations", []))
    questions = "".join(f'<li>{esc(item)}</li>' for item in data.get("unanswered_questions", []))
    header_metrics = "".join(f'<div><dt>{esc(item.get("label"))}</dt><dd>{esc(item.get("value"))}</dd></div>' for item in presentation.get("header_metrics", []))
    completion_status = str(data.get("completion_status") or "legacy")
    completion_note = str(presentation.get("completion_note") or "").strip()
    completion_copy = {
        "preliminary": ("阶段性分析", completion_note or "本报告只呈现当前已审核证据；仍未覆盖的资料与证据通道见下文。"),
        "final": ("已完成本轮分析", completion_note or "本报告已完成声明范围内的分析；各证据通道的实际覆盖程度见下文。"),
    }.get(completion_status)
    completion_banner = (
        f'<div class="completion-status status-{esc(completion_status)}"><strong>{esc(completion_copy[0])}</strong><span>{esc(completion_copy[1])}</span></div>'
        if completion_copy else ""
    )
    coverage_section = ""
    if data.get("sampling") or data.get("evidence_coverage"):
        coverage_section = f'<section class="report-section" id="coverage"><header class="section-heading"><div><h2>{esc(labels.get("coverage", "这次样本能说明什么"))}</h2><p>样本怎么选、真正按什么计数、哪些资料真的检查过，会直接影响结论能走多远。</p></div></header>{render_coverage(data.get("sampling", {}), data.get("evidence_coverage", []), data.get("analysis_units"), data.get("metric_definitions"))}</section>'
    experiment_section = ""
    if data.get("experiments"):
        experiment_section = f'<section class="report-section" id="experiments"><header class="section-heading"><div><h2>{esc(labels.get("experiments", "下一轮怎么验证"))}</h2><p>每次只改变一个关键变量，提前写清指标和判定规则。</p></div></header><div class="experiment-list">{render_experiments(data.get("experiments", []), finding_map)}</div></section>'
    return f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(data.get("title"))}</title><style>{css}</style></head>
<body><article class="report-shell" data-data-lens-report="2">
  <header class="report-header"><div class="report-identity"><p class="eyebrow">{esc(presentation.get("kicker", "内容分析报告"))}</p><h1>{esc(data.get("title"))}</h1><p class="lead">{esc(data.get("subtitle"))}</p>{completion_banner}</div><dl class="header-meta">{header_metrics}</dl></header>
  <div class="report-layout"><nav class="toc" aria-label="阅读导航"><strong>{esc(presentation.get("toc_title", "这份报告怎么看"))}</strong>{toc_html}</nav><main class="report-main">
    <section class="report-section summary-section" id="summary"><header class="section-heading"><div><h2>{esc(labels.get("summary", "先看最重要的结论"))}</h2><p>{esc(copy["summary_note"])}</p></div></header><div class="summary-list">{render_summary(data.get("executive_summary", []), evidence_map)}</div></section>
    {render_overview_charts(data)}
    <section class="report-section" id="scope"><header class="section-heading"><div><h2>{esc(labels.get("scope", "这份分析用了哪些资料"))}</h2><p>{esc(copy["scope_note"])}</p></div></header><dl class="scope-list">{format_scope(data.get("scope", {}))}</dl></section>
    {coverage_section}
    <section class="report-section" id="findings"><header class="section-heading"><div><h2>{esc(labels.get("findings", copy["findings_title"]))}</h2><p>每个判断都同时保留实际表现、可能原因、反例和适用边界。</p></div></header><div class="finding-list">{render_findings(data.get("findings", []), evidence_map, recommendation_map)}</div></section>
    <section class="report-section" id="comparisons"><header class="section-heading"><div><h2>{esc(labels.get("comparisons", copy["comparisons_title"]))}</h2><p>{esc(copy["comparisons_note"])}</p></div></header><div class="comparison-list">{render_comparisons(data.get("comparisons", []), evidence_map)}</div></section>
    {render_analysis_sections(sections, evidence_map)}
    <section class="report-section" id="actions"><header class="section-heading"><div><h2>{esc(labels.get("actions", copy["actions_title"]))}</h2><p>把结论变成可执行的小实验，每次只验证一两个关键变化。</p></div></header><div class="action-list">{render_recommendations(data.get("recommendations", []), finding_map)}</div></section>
    {experiment_section}
    <aside class="reader-caveats" aria-label="阅读提醒"><h2>{esc(labels.get("caveats", "看结论前要注意"))}</h2><div class="limit-grid"><div><h3>这份数据暂时不能证明什么</h3><ul>{limitations}</ul></div><div><h3>以后补什么数据会更准确</h3><ul>{questions}</ul></div></div></aside>
  </main></div><footer class="report-footer">{esc(presentation.get("footer_note", "根据现有资料形成，下一轮用真实结果继续验证"))}</footer>
</article></body></html>'''


def md_evidence(ids: list[str]) -> str:
    return "、".join(ids) if ids else "无"


def render_markdown(data: dict[str, Any]) -> str:
    completion_status = str(data.get("completion_status") or "")
    completion_note = str((data.get("presentation") or {}).get("completion_note") or "").strip()
    completion_copy = {
        "preliminary": f"阶段性分析：{completion_note or '本报告只呈现当前已审核证据；仍未覆盖的资料与证据通道见下文。'}",
        "final": f"已完成本轮分析：{completion_note or '本报告已完成声明范围内的分析；各证据通道的实际覆盖程度见下文。'}",
    }.get(completion_status)
    lines = [f'# {data.get("title", "分析报告")}', "", str(data.get("subtitle", "")), ""]
    if completion_copy:
        lines.extend([f'> {completion_copy}', ""])
    lines.extend([f'- 分析方法：{human_route(str(data.get("route") or ""))}', f'- 分析深度：{human_depth(str(data.get("report_depth") or ""))}', "", "## 结论摘要", ""])
    for item in data.get("executive_summary", []):
        lines.extend([f'### {item.get("title")}', "", str(item.get("summary", "")), "", f'> 分类：{human_class(item.get("classification"))}；证据：{md_evidence(item.get("evidence_ids", []))}', ""])
    scope = data.get("scope", {})
    lines.extend(["## 口径与覆盖", "", f'- 决策问题：{scope.get("decision_question", "")}', f'- 资料范围：{scope.get("corpus_summary", "")}', f'- 时间范围：{scope.get("time_range", "")}', f'- 比较单位：{human_analysis_unit(str(scope.get("comparison_unit") or ""))}', f'- 纳入口径：{scope.get("eligibility_rule", "")}', ""])
    if data.get("analysis_units"):
        units = data["analysis_units"]
        lines.extend([
            "### 分析单元契约", "",
            f'- 来源容器单位：{human_analysis_unit(str(units.get("source_container_unit") or ""))}',
            f'- 真正分析单位：{human_analysis_unit(str(units.get("analysis_unit") or ""))}（{human_unit_status(str(units.get("unit_status") or ""))}）',
            f'- 来源容器数：{units.get("source_container_count", "")}',
            f'- 可纳入 / 已选择 / 已观察 / 缺失：{units.get("eligible_count", "")} / {units.get("selected_count", "")} / {units.get("observed_count", "")} / {units.get("missing_count", "")}',
            f'- 去重规则：{units.get("deduplication_rule", "")}',
            f'- 版本规则：{units.get("version_rule", "")}',
            f'- 分组规则：{units.get("grouping_rule", "")}', "",
        ])
    if data.get("sampling") or data.get("evidence_coverage"):
        sampling = data.get("sampling", {})
        lines.extend(["## 样本与证据覆盖", "", f'- 抽样策略：{sampling.get("strategy", "")}', f'- 纳入规则：{sampling.get("inclusion_rule", "")}', f'- 候选数：{sampling.get("eligible_count", "")}', f'- 实际分析数：{sampling.get("selected_count", "")}', "", "### 样本偏差", ""])
        lines.extend([f'- {value}' for value in sampling.get("bias_warnings", [])])
        lines.extend(["", "### 各类证据能说明什么", ""])
        for item in data.get("evidence_coverage", []):
            lines.extend([f'#### {human_lane(str(item.get("lane", "")))} · {human_coverage_status(str(item.get("status", "")))}', "", f'- 数量：{item.get("items")}', f'- 处理状态：{"、".join(human_processing_state(str(state)) for state in item.get("processing_states", []))}', f'- 能说明：{item.get("proves")}', f'- 不能说明：{item.get("cannot_prove")}', ""])
    if data.get("metric_definitions"):
        lines.extend(["## 指标定义", ""])
        for item in data.get("metric_definitions", []):
            lines.extend([
                f'### {item.get("label")}', "",
                f'- 指标类型：{human_metric_type(str(item.get("metric_type") or ""))}', f'- 单位：{item.get("unit")}',
                f'- 分子：{item.get("numerator")}', f'- 分母：{item.get("denominator")}',
                f'- 纳入条件：{item.get("eligibility_rule")}', f'- 缺失处理：{item.get("missing_policy")}',
                f'- 排除：{"；".join(item.get("exclusions", []))}', f'- 来源证据：{item.get("source_lane")}',
                f'- 算法版本：{item.get("algorithm_version")}', f'- 有效条件：{"；".join(item.get("validity_conditions", []))}',
                f'- 解释边界：{item.get("interpretation_limit")}', "",
            ])
    lines.extend(["## 完整发现", ""])
    for item in data.get("findings", []):
        lines.extend([f'### {item.get("title")}', "", f'**事实**：{item.get("fact")}', "", f'**证据**：{md_evidence(item.get("evidence_ids", []))}', "", f'**解释**：{item.get("explanation")}', "", "**反例**", ""])
        lines.extend([f'- {value}' for value in item.get("counterexamples", [])])
        lines.extend(["", "**边界**", ""])
        lines.extend([f'- {value}' for value in item.get("boundaries", [])])
        lines.extend(["", f'**关联动作**：{md_evidence(item.get("recommendation_ids", []))}', ""])
    lines.extend(["## 成对比较", ""])
    for item in data.get("comparisons", []):
        left, right = item.get("left", {}), item.get("right", {})
        lines.extend([f'### {item.get("title")}', "", f'- **{left.get("label")} · {left.get("value")}**：{left.get("body")}', f'- **{right.get("label")} · {right.get("value")}**：{right.get("body")}', "", f'**解释**：{item.get("interpretation")}', "", f'**反例**：{item.get("counterexample")}', "", f'**边界**：{item.get("boundary")}', "", f'**证据**：{md_evidence(item.get("evidence_ids", []))}', ""])
    for section in data.get("analysis_sections", []):
        lines.extend([f'## {section.get("title")}', "", str(section.get("summary", "")), ""])
        for visual in section.get("gallery", []):
            lines.extend([f'- **{visual.get("title")}**：{visual.get("caption")}', ""])
        table = section.get("table")
        if table:
            columns = table.get("columns", [])
            lines.extend(["| " + " | ".join(str(c.get("label", "")) for c in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
            for row in table.get("rows", []):
                lines.append("| " + " | ".join(str(row.get(c.get("key"), "—")).replace("|", "\\|") for c in columns) + " |")
            lines.append("")
        for item in section.get("items", []):
            lines.extend([f'### {item.get("title")}', "", str(item.get("body", "")), "", f'**证据**：{md_evidence(item.get("evidence_ids", []))}', ""])
            if item.get("boundary"):
                lines.extend([f'**边界**：{item.get("boundary")}', ""])
    lines.extend(["## 下一步动作", ""])
    for item in data.get("recommendations", []):
        priority = {"now": "现在做", "next": "接着做", "later": "以后做"}.get(item.get("priority"), "未分级")
        lines.extend([f'### {item.get("title")}', "", str(item.get("action", "")), "", f'- 优先级：{priority}', f'- 理由：{item.get("rationale")}', f'- 关联发现：{md_evidence(item.get("finding_ids", []))}', f'- 验证指标：{item.get("validation_metric")}', f'- 周期：{item.get("timebox")}', f'- 风险：{"；".join(item.get("risks", []))}', f'- 未达预期：{item.get("fallback")}', ""])
    if data.get("experiments"):
        lines.extend(["## 下一轮验证实验", ""])
        for item in data.get("experiments", []):
            lines.extend([f'### {item.get("title")}', "", str(item.get("question", "")), "", f'- 假设：{item.get("hypothesis")}', f'- 只改变：{item.get("changed_variable")}', f'- 对照设计：{item.get("comparison_design")}', f'- 基线：{item.get("baseline")}', f'- 主指标：{item.get("primary_metric")}', f'- 保护指标：{"；".join(item.get("guardrail_metrics", []))}', f'- 观察周期：{item.get("measurement_window")}', f'- 最少样本：{item.get("minimum_sample")}', f'- 判定规则：{item.get("decision_rule")}', f'- 需要数据：{"；".join(item.get("required_data", []))}', f'- 干扰因素：{"；".join(item.get("confounders", []))}', f'- 停止条件：{item.get("stop_condition")}', f'- 关联发现：{md_evidence(item.get("linked_finding_ids", []))}', ""])
    lines.extend(["## 限制与未知", "", "### 证据限制", ""])
    lines.extend([f'- {item}' for item in data.get("limitations", [])])
    lines.extend(["", "### 目前还不能回答的问题", ""])
    lines.extend([f'- {item}' for item in data.get("unanswered_questions", [])])
    lines.extend(["", "## 证据索引", ""])
    for item in data.get("evidence", []):
        lines.append(f'- **{item.get("id")}** {item.get("label") or item.get("note")} — lane=`{item.get("lane", "")}` · review=`{item.get("review_status", "")}` · family=`{item.get("source_family", "")}` · `{item.get("source_path")}` · `{json.dumps(item.get("locator", {}), ensure_ascii=False)}`')
    if data.get("analysis_checklist"):
        lines.extend(["", "## 路线完整性检查（内部）", ""])
        for item in data.get("analysis_checklist", []):
            lines.append(
                f'- **{item.get("id")} · {item.get("status")}** {item.get("question")}；证据：{md_evidence(item.get("evidence_ids", []))}；发现：{md_evidence(item.get("finding_ids", []))}；{item.get("note")}'
            )
    return "\n".join(lines).strip() + "\n"


def verify_run_context(data: dict[str, Any], context: dict[str, Any]) -> None:
    if context.get("route") != data.get("route") or context.get("report_depth") != data.get("report_depth"):
        raise ValueError("run_context route/depth does not match deep_analysis")
    if context.get("skill_version") != SKILL_VERSION:
        raise ValueError("run_context skill version is stale")
    for key in ("method_loads", "artifact_inputs"):
        for item in context.get(key, []):
            path = Path(item["path"])
            if not path.is_file() or not item.get("loaded") or file_sha256(path) != item.get("sha256"):
                raise ValueError(f"stale or unverified run_context item: {path}")


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "size_bytes": path.stat().st_size}


def build_manifest(data: dict[str, Any], analysis_path: Path, validation_path: Path, context_path: Path, context: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    outputs = [record(output_dir / "report.html"), record(output_dir / "report.md")]
    evidence_positions = [{"evidence_id": item.get("id"), "source_path": item.get("source_path"), "locator": item.get("locator")} for item in data.get("evidence", [])]
    pipeline_steps = list(dict.fromkeys([*context.get("pipeline_steps", ["materialize_run_context.py"]), "validate_deep_analysis.py", "render_report.py"]))
    contract_version = str(data.get("contract_version") or "")
    manifest_version = contract_version if contract_version in {"2.3", "2.4"} else "2.2"
    return {"manifest_version": manifest_version, "generated_at": datetime.now().astimezone().isoformat(), "skill_name": context.get("skill_name", SKILL_NAME), "skill_version": context.get("skill_version", SKILL_VERSION), "route": data.get("route"), "report_depth": data.get("report_depth"), "completion_status": data.get("completion_status", "legacy"), "analysis_artifact": record(analysis_path), "analysis_validation": record(validation_path), "run_context": record(context_path), "method_loads": context.get("method_loads", []), "deterministic_artifacts": context.get("artifact_inputs", []), "evidence_positions": evidence_positions, "pipeline_steps": pipeline_steps, "outputs": outputs}


def main() -> None:
    parser = argparse.ArgumentParser(description="Render every item in a validated Data Lens deep_analysis.json artifact.")
    parser.add_argument("deep_analysis", type=Path)
    parser.add_argument("--run-context", type=Path, required=True)
    parser.add_argument("--analysis-validation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sources = [args.deep_analysis, args.run_context, args.analysis_validation]
    for name in ("report.html", "report.md", "run_manifest.json"):
        guard_cli_output(parser, args.output_dir / name, sources)
    data = load_json(args.deep_analysis)
    context = load_json(args.run_context)
    validation = load_json(args.analysis_validation)
    if not validation.get("valid"):
        raise ValueError("deep_analysis validation did not pass")
    current_validation = validate_analysis(data)
    if not current_validation.get("valid"):
        raise ValueError("deep_analysis no longer passes current validation: " + ";".join(current_validation.get("errors", [])))
    verify_run_context(data, context)
    css_path = Path(__file__).resolve().parent.parent / "assets" / "report-template" / "report.css"
    css = css_path.read_text(encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.html").write_text(render_html(data, css, context), encoding="utf-8")
    (args.output_dir / "report.md").write_text(render_markdown(data), encoding="utf-8")
    manifest = build_manifest(data, args.deep_analysis, args.analysis_validation, args.run_context, context, args.output_dir)
    write_json(args.output_dir / "run_manifest.json", manifest)
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "rendered_counts": {key: len(data.get(key, [])) for key in ("executive_summary", "findings", "comparisons", "analysis_sections", "recommendations", "experiments", "evidence_coverage", "evidence")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
