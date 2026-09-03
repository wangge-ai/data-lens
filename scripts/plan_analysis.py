from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from _common import SKILL_NAME, SKILL_VERSION, guard_cli_output, load_json, write_json


DIMENSIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("angle_discovery", "自动发现分析角度", (
        r"自动(?:寻找|发现|生成|选择|筛选).{0,8}(?:分析)?角度",
        r"自己(?:寻找|发现|生成|选择|筛选).{0,8}(?:分析)?角度",
        r"自己找角度", r"自动找角度", r"无预设(?:分析)?角度",
        r"不给.{0,8}(?:分析)?角度",
        r"不交代.{0,8}(?:分析)?角度",
        r"不(?:提供|指定|预设).{0,8}(?:分析)?角度",
        r"先不(?:提供|指定|预设).{0,8}(?:分析)?角度",
        r"没想好.{0,8}(?:分析)?角度", r"不知道.{0,8}(?:怎么|如何)分析",
        r"(?:给你|让你|由你)?自由发挥", r"自行发挥", r"随你(?:分析|判断|发挥)",
        r"你来(?:定|决定|选择).{0,8}(?:分析)?角度",
    )),
    ("inventory_profile", "资料清点与数据画像", (r"有什么资料", r"有哪些资料", r"清点", r"盘点", r"数据画像", r"字段画像", r"缺失率", r"重复值", r"数据质量")),
    ("generic_tabular", "通用表格分析", (r"描述统计", r"探索性数据分析", r"EDA", r"字段分布", r"数值分布", r"分组统计", r"中位数", r"四分位", r"稳健异常", r"变化点", r"CSV", r"TSV")),
    ("semantic_retrieval", "语义检索与候选召回", (r"语义检索", r"向量检索", r"向量库", r"相似段落", r"相似内容", r"候选召回")),
    ("operational_performance", "连续经营数据", (r"经营数据", r"经营分析", r"经营复盘", r"日报", r"订单", r"支付额", r"销售额", r"推广支出", r"库存", r"退款", r"履约", r"平台.{0,6}(?:对比|区分)", r"前\s*\d+\s*天", r"后\s*\d+\s*天", r"趋势", r"异常", r"下钻", r"聚合")),
    ("performance", "内容表现", (r"阅读", r"点赞", r"转发", r"收藏", r"表现", r"爆款", r"后台数据", r"转化率")),
    ("audience_voice", "评论与用户需求", (r"评论", r"用户需求", r"痛点", r"异议", r"反馈", r"问了什么")),
    ("visual_layout", "视觉与排版", (r"排版", r"封面", r"首图", r"配图", r"图片", r"视觉", r"字体", r"配色", r"卡片")),
    ("topic_selection", "选题", (r"选题", r"题材", r"选题角度", r"切入角度", r"从哪些角度", r"写什么", r"内容方向")),
    ("title_hook", "标题与钩子", (r"标题", r"钩子", r"开头", r"首屏", r"吸引", r"打开率")),
    ("writing_style", "写作风格", (r"写作风格", r"写作习惯", r"语气", r"语言", r"文风", r"句式")),
    ("content_structure", "内容结构", (r"结构", r"段落", r"章节", r"框架", r"怎么展开")),
    ("conversion_design", "转化设计", (r"转化", r"关注", r"成交", r"引流", r"私域", r"购买", r"CTA")),
    ("method_extraction", "方法提炼", (
        r"方法论", r"可复用规律", r"打法", r"SOP", r"流程", r"步骤", r"共同点", r"关联",
        r"怎么赚钱", r"如何放大", r"赚钱项目", r"变现路径",
        r"(?:提炼|总结|归纳|抽取|找出).{0,8}(?:可复用的?)?方法",
        r"(?:这些|这批|资料(?:中|里)|文章(?:中|里)|项目(?:中|里)|案例(?:中|里)|课程(?:中|里)).{0,8}(?:的)?方法",
        r"方法.{0,8}(?:步骤|条件|适用|冲突|边界|效果|失效|共性|差异)",
    )),
    ("course_structure", "课程与教学组织", (r"课程", r"课件", r"讲义", r"教学", r"练习", r"章节关系")),
    ("family_relation", "资料家族与关系", (r"资料家族", r"不同家族", r"跨家族", r"版本关系", r"上下游", r"有没有关联", r"真实关联", r"不关联")),
]

MIXED_GOAL_PATTERNS = (
    r"混合资料", r"多种资料", r"多类资料", r"不同类型", r"多种格式", r"资料家族", r"跨家族",
    r"文件很多", r"没有关联", r"有的.{0,12}文章.{0,20}表格", r"正文.{0,12}表格.{0,12}图片",
)
AUTHOR_GOAL_PATTERNS = (r"同一作者", r"这个作者", r"同一个作者", r"公众号", r"账号", r"博主", r"小红书")
METHOD_ROUTE_PATTERNS = (
    r"(?:提炼|总结|归纳|抽取|找出).{0,12}(?:可复用的?)?(?:方法|打法|SOP|流程|步骤|规律|共性)",
    r"(?:这些|这批|资料(?:中|里)|文章(?:中|里)|项目(?:中|里)|案例(?:中|里)|课程(?:中|里)|教程(?:中|里)).{0,12}(?:的)?(?:方法|打法|SOP|流程|步骤|规律|共同点|冲突)",
    r"(?:方法|打法|流程|步骤).{0,12}(?:条件|适用|冲突|边界|效果|失效|共性|差异|放大)",
    r"怎么赚钱|如何放大|赚钱项目|变现路径",
)


def canonical_role_counts(inventory: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in inventory.get("files", []):
        if not item.get("canonical", True):
            continue
        role = str(item.get("evidence_role") or "unclassified")
        counts[role] = counts.get(role, 0) + 1
    if not counts:
        summary_counts = (inventory.get("summary") or {}).get("by_evidence_role") or {}
        counts = {str(key): int(value) for key, value in summary_counts.items()}
    return dict(sorted(counts.items()))


def canonical_container_counts(inventory: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in inventory.get("files", []):
        if not item.get("canonical", True):
            continue
        kind = str(item.get("container_type") or "file")
        counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        summary_counts = (inventory.get("summary") or {}).get("by_container_type") or {}
        counts = {str(key): int(value) for key, value in summary_counts.items()}
    return dict(sorted(counts.items()))


def recognize_dimensions(goal: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for dimension_id, label, patterns in DIMENSIONS:
        positions = [match.start() for pattern in patterns for match in re.finditer(pattern, goal, flags=re.I)]
        if positions:
            hits.append({"id": dimension_id, "label": label, "first_position": min(positions)})
    hits.sort(key=lambda item: item["first_position"])
    return hits


def has_explicit_method_route_intent(goal: str) -> bool:
    """Distinguish corpus methods from meta-talk about how the analysis should run."""
    return any(re.search(pattern, goal, re.I) for pattern in METHOD_ROUTE_PATTERNS)


def _inventory_for_scope(inventory: dict[str, Any], scope_gate: dict[str, Any] | None) -> dict[str, Any]:
    if not scope_gate or scope_gate.get("next_action") != "analysis_ready" or scope_gate.get("deep_analysis_allowed") is not True:
        return inventory
    selected_ids = {str(value) for value in scope_gate.get("selected_source_ids", []) if str(value)}
    if not selected_ids:
        return inventory
    files = [
        item for item in inventory.get("files", [])
        if str(item.get("source_container_id") or "") in selected_ids
    ]
    canonical = [item for item in files if item.get("canonical", True)]
    extensions = Counter(str(item.get("extension") or Path(str(item.get("path") or "")).suffix).lower() for item in canonical)
    dates = {str(item.get("collection_date")) for item in canonical if item.get("collection_date")}
    repeated_families = {
        str(item.get("repeated_export_family_key"))
        for item in canonical
        if item.get("repeated_export_family_key")
    }
    table_extensions = {".csv", ".tsv", ".xls", ".xlsx", ".xlsm"}
    summary = {
        **(inventory.get("summary") or {}),
        "canonical_items": len(canonical),
        "by_extension": dict(sorted(extensions.items())),
        "date_partition_count": len(dates),
        "repeated_table_family_count": len(repeated_families),
        "table_files": sum(count for extension, count in extensions.items() if extension in table_extensions),
    }
    return {**inventory, "files": files, "summary": summary}


def _route_from_scope_gate(scope_gate: dict[str, Any] | None) -> str | None:
    """Use the verified selection to recover the route without rewriting the user goal."""
    if not scope_gate or scope_gate.get("next_action") != "analysis_ready" or scope_gate.get("deep_analysis_allowed") is not True:
        return None
    selection = scope_gate.get("selection") or {}
    if selection.get("scope_type") == "whole_corpus":
        return "mixed_corpus"
    selected_family_id = str(scope_gate.get("selected_family_id") or "")
    if not selected_family_id:
        return None
    for family in scope_gate.get("families", []):
        if (
            str(family.get("family_id") or "") == selected_family_id
            and family.get("analysis_ready") is True
        ):
            route = str(family.get("recommended_route") or "")
            return route if route in {
                "tabular_analysis",
                "repeated_operational_tables",
                "qualitative_corpus",
                "same_author_content",
                "account_content_performance",
                "method_corpus",
                "multimodal_evidence",
                "mixed_corpus",
                "novel_route",
            } else None
    return None


def _analysis_unit_from_scope_gate(scope_gate: dict[str, Any] | None) -> str | None:
    if not scope_gate or (scope_gate.get("selection") or {}).get("scope_type") != "family":
        return None
    selected_family_id = str(scope_gate.get("selected_family_id") or "")
    for family in scope_gate.get("families", []):
        if str(family.get("family_id") or "") == selected_family_id and family.get("analysis_ready") is True:
            value = str(family.get("analysis_unit") or "").strip()
            return value or None
    return None


def _scope_route_defaults(route: str) -> tuple[str, str, list[str]]:
    defaults = {
        "tabular_analysis": ("table_row_or_declared_business_unit", "full_census", ["table_profile", "grouped_descriptive"]),
        "repeated_operational_tables": ("business_date_x_platform", "full_census", ["table_quality_gate", "operational_fact_layer"]),
        "qualitative_corpus": ("document_or_declared_case", "balanced_topic", ["qualitative_framework"]),
        "same_author_content": ("article", "balanced_topic", []),
        "account_content_performance": ("article_with_confirmed_metrics", "performance_contrast", ["same_author_content"]),
        "method_corpus": ("atomic_method_claim", "stratified", []),
        "multimodal_evidence": ("media_segment_or_visual_region", "stratified", ["multimodal_inventory"]),
        "mixed_corpus": ("family_specific", "family_stratified", []),
        "novel_route": ("pilot_defined", "pilot", []),
    }
    return defaults[route]


def build_plan(goal: str, inventory: dict[str, Any], scope_gate: dict[str, Any] | None = None) -> dict[str, Any]:
    inventory = _inventory_for_scope(inventory, scope_gate)
    role_counts = canonical_role_counts(inventory)
    container_counts = canonical_container_counts(inventory)
    dimensions = recognize_dimensions(goal)
    ids = {item["id"] for item in dimensions}
    has_text = role_counts.get("content_text", 0) > 0
    has_metrics = role_counts.get("performance_table", 0) > 0
    summary = inventory.get("summary") or {}
    extension_counts = summary.get("by_extension") or {}
    has_original_html = sum(int(extension_counts.get(extension, 0) or 0) for extension in (".html", ".htm", ".mhtml")) > 0
    pdf_count = int(extension_counts.get(".pdf", 0) or 0)
    has_pdf = pdf_count > 0
    has_visual = role_counts.get("visual_layout", 0) > 0 or has_original_html
    has_audience = role_counts.get("audience_voice", 0) > 0
    has_av = role_counts.get("audio_video", 0) > 0
    has_tabular = role_counts.get("tabular_data", 0) > 0 or has_metrics
    date_partition_count = int(summary.get("date_partition_count") or 0)
    repeated_table_family_count = int(summary.get("repeated_table_family_count") or 0)
    table_file_count = int(summary.get("table_files") or role_counts.get("tabular_data", 0) + role_counts.get("performance_table", 0))
    role_diversity = sum(1 for role, count in role_counts.items() if count and role != "unclassified")
    container_diversity = sum(1 for count in container_counts.values() if count)
    explicit_mixed_goal = any(re.search(pattern, goal, re.I) for pattern in MIXED_GOAL_PATTERNS)
    author_goal = any(re.search(pattern, goal, re.I) for pattern in AUTHOR_GOAL_PATTERNS)
    explicit_method_intent = has_explicit_method_route_intent(goal)
    angle_discovery_requested = "angle_discovery" in ids
    multi_dimension_mixed = (
        "method_extraction" in ids
        and len(ids.intersection({"visual_layout", "course_structure", "audience_voice", "performance", "family_relation"})) >= 1
        and role_diversity >= 2
    )
    scope_gate_ready = bool(
        scope_gate
        and scope_gate.get("contract_version") == "data-lens-corpus-scope-gate/1.0"
        and scope_gate.get("next_action") == "analysis_ready"
        and scope_gate.get("deep_analysis_allowed") is True
    )
    selected_scope_route = _route_from_scope_gate(scope_gate)
    selected_scope_unit = _analysis_unit_from_scope_gate(scope_gate)
    mixed_scope_needs_gate = role_diversity >= 2 and (
        explicit_mixed_goal or angle_discovery_requested or multi_dimension_mixed or not dimensions
    )
    mixed_corpus = (explicit_mixed_goal and role_diversity >= 2) or multi_dimension_mixed or (angle_discovery_requested and has_text and has_tabular)
    operational_intent = "operational_performance" in ids
    explicit_operational_business = bool(re.search(r"经营|订单|支付|销售|推广|广告|库存|退款|履约|店铺|商品|平台", goal, re.I))
    generic_tabular_intent = "generic_tabular" in ids or ("inventory_profile" in ids and has_tabular)
    repeated_operational_shape = has_tabular and table_file_count >= 3 and (
        date_partition_count >= 3 or repeated_table_family_count >= 1
    )
    missing: list[str] = []
    supporting: list[str] = []
    confidence = "high"

    if mixed_scope_needs_gate and not scope_gate_ready:
        route = "inventory_and_profile"
        comparison_unit = "source_container_then_candidate_family"
        sampling = "full_census"
        confidence = "high"
        supporting.extend(["data_profile", "corpus_scope_gate"])
        missing.append("资料包含多个证据角色，但尚无通过校验的资料群选择；只能盘点、去重、分类并提出分群问题，不得执行全目录综合")
    elif selected_scope_route:
        route = selected_scope_route
        comparison_unit, sampling, scope_supporting = _scope_route_defaults(route)
        if selected_scope_unit:
            comparison_unit = selected_scope_unit
        supporting.extend(scope_supporting)
        confidence = "high"
        if route == "qualitative_corpus" and angle_discovery_requested:
            supporting.append("angle_discovery")
        if route == "mixed_corpus" and has_tabular:
            supporting.append("tabular_screening")
        if route in {"mixed_corpus", "multimodal_evidence"} and has_av:
            supporting.append("multimodal_inventory")
            missing.append("音视频在形成内容结论前仍需转录或抽帧")
    elif "inventory_profile" in ids and not ids.intersection({"operational_performance", "generic_tabular", "performance", "method_extraction", "family_relation"}):
        route = "inventory_and_profile"
        comparison_unit = "source_container"
        sampling = "full_census"
        confidence = "high"
        supporting.append("data_profile")
    elif generic_tabular_intent and has_tabular and not repeated_operational_shape and not explicit_operational_business and not explicit_mixed_goal:
        route = "tabular_analysis"
        comparison_unit = "table_row_or_declared_business_unit"
        sampling = "full_census"
        confidence = "high"
        supporting.extend(["table_profile", "grouped_descriptive"])
        if re.search(r"异常", goal):
            supporting.append("robust_anomaly_candidates")
        if re.search(r"变化点|断点", goal):
            supporting.append("change_point_candidate")
    elif operational_intent and explicit_operational_business and has_tabular and not explicit_mixed_goal:
        route = "repeated_operational_tables"
        comparison_unit = "business_date_x_platform"
        sampling = "full_census"
        confidence = "high" if repeated_operational_shape else "medium"
        supporting.extend(["table_quality_gate", "operational_fact_layer"])
        if not repeated_operational_shape:
            missing.append("尚未确认至少三个日期批次或一个重复导出家族；先校准日期与表族映射，再做趋势判断")
    elif repeated_operational_shape and has_tabular and not has_text and not explicit_mixed_goal:
        route = "repeated_operational_tables"
        comparison_unit = "business_date_x_platform"
        sampling = "full_census"
        confidence = "medium"
        supporting.extend(["table_quality_gate", "operational_fact_layer"])
        missing.append("用户问题未明确经营指标优先级；默认先做总量、趋势、阶段、平台、结构、实体和异常七层分析")
    elif mixed_corpus:
        route = "mixed_corpus"
        comparison_unit = "family_specific"
        sampling = "family_stratified"
        confidence = "high" if explicit_mixed_goal else "medium"
        if angle_discovery_requested:
            supporting.append("angle_discovery")
        if "method_extraction" in ids:
            supporting.append("method_corpus")
        if has_metrics or role_counts.get("tabular_data", 0):
            supporting.append("tabular_screening")
        if has_audience:
            supporting.append("audience_voice")
        if has_av:
            supporting.append("multimodal_course")
            missing.append("音视频在形成内容结论前仍需转录或抽帧")
    elif "performance" in ids:
        if has_metrics and has_text:
            route = "account_content_performance"
            comparison_unit = "article_with_confirmed_metrics"
            sampling = "performance_contrast"
            supporting.append("same_author_content")
        elif has_text:
            route = "same_author_content"
            comparison_unit = "article"
            sampling = "balanced_topic"
            confidence = "medium"
            missing.append("缺少可匹配到文章的后台表现表，只能分析内容特征，不能判断哪些写法表现更好")
        else:
            route = "novel_route"
            comparison_unit = "pilot_defined"
            sampling = "pilot"
            confidence = "low"
            missing.append("表现数据缺少可解释其内容差异的正文或视觉材料")
    elif "audience_voice" in ids:
        if has_audience:
            route = "novel_route"
            comparison_unit = "comment"
            sampling = "stratified"
            confidence = "medium"
            supporting.append("comment_voc")
        elif has_metrics:
            route = "novel_route"
            comparison_unit = "comment"
            sampling = "pilot"
            confidence = "medium"
            supporting.append("comment_voc")
            missing.append("发现表格但尚未确认列结构；先检查它是否真的是评论或用户反馈")
        else:
            route = "novel_route"
            comparison_unit = "pilot_defined"
            sampling = "pilot"
            confidence = "low"
            missing.append("没有识别到评论或用户反馈资料")
    elif angle_discovery_requested and has_text:
        article_count = int(container_counts.get("article_candidate") or 0)
        text_count = int(role_counts.get("content_text") or 0)
        all_text_units_are_articles = article_count > 0 and article_count == text_count
        route = "same_author_content" if author_goal and all_text_units_are_articles else "qualitative_corpus"
        if has_pdf and not all_text_units_are_articles:
            comparison_unit = "internal_project_or_chapter_pending_confirmation"
            sampling = "pdf_structure_then_internal_unit_stratified"
            supporting.extend(["pdf_structure_profile", "multimodal_evidence"])
            missing.append("PDF 文件数不是分析单位数；先确认目录、项目或章节边界，再按内部单元分层，不能按物理文件数宣称全量")
        else:
            comparison_unit = "article" if all_text_units_are_articles else "document_or_declared_case"
            sampling = "full_census" if 0 < text_count <= 20 else "balanced_topic"
        confidence = "high" if author_goal and all_text_units_are_articles else "medium"
        supporting.extend(["angle_discovery", "qualitative_framework"])
        if all_text_units_are_articles and not author_goal:
            missing.append("尚未确认资料是否来自同一作者或同一账号；确认前只形成当前语料范围内的横向模式")
    elif "course_structure" in ids or (not dimensions and has_av and not has_text) or ("visual_layout" in ids and has_visual and not has_text):
        route = "multimodal_evidence"
        comparison_unit = "media_segment_or_visual_region"
        sampling = "stratified"
        confidence = "medium" if has_av else "low"
        supporting.append("multimodal_inventory")
        if has_av:
            missing.append("音视频在形成内容结论前仍需转录或抽帧")
    elif has_text and ids.intersection({"visual_layout", "topic_selection", "title_hook", "writing_style", "content_structure", "conversion_design"}) and not author_goal:
        route = "qualitative_corpus"
        comparison_unit = "document_or_declared_case"
        sampling = "balanced_topic"
        confidence = "medium"
        supporting.append("qualitative_framework")
        missing.append("尚未确认资料是否来自同一作者或同一业务主体；仅形成当前语料范围内的横向模式")
    elif has_text and author_goal and ids.intersection({"visual_layout", "topic_selection", "title_hook", "writing_style", "content_structure", "conversion_design"}):
        route = "same_author_content"
        comparison_unit = "article"
        sampling = "balanced_topic"
    elif has_text and "method_extraction" in ids and explicit_method_intent:
        route = "method_corpus"
        comparison_unit = "atomic_method_claim"
        sampling = "stratified"
        confidence = "high"
    else:
        route = "novel_route"
        comparison_unit = "pilot_defined"
        sampling = "pilot"
        confidence = "low"
        if has_text and "method_extraction" in ids and not explicit_method_intent:
            missing.append("尚未确认用户是在提炼资料中的方法，还是在讨论分析方式；先试读样本确认分析单位和路线")

    if "visual_layout" in ids:
        supporting.append("visual_analysis")
        if not has_visual:
            missing.append("没有本地图片、原始HTML或截图；图片链接数量不能代替视觉分析")
    if "audience_voice" in ids and has_audience:
        supporting.append("audience_voice")
    if "conversion_design" in ids:
        supporting.append("conversion_path")
    if "semantic_retrieval" in ids:
        supporting.append("local_vector_retrieval")

    required_lanes = ["content_text"] if has_text or route in {"qualitative_corpus", "same_author_content", "account_content_performance", "method_corpus", "mixed_corpus"} else []
    if route == "repeated_operational_tables":
        if role_counts.get("tabular_data", 0):
            required_lanes.append("tabular_data")
        if has_metrics:
            required_lanes.append("performance_table")
    if route == "tabular_analysis":
        required_lanes.append("tabular_data")
    if route == "multimodal_evidence" and has_visual:
        required_lanes.append("visual_layout")
    if "performance" in ids:
        required_lanes.append("performance_table")
    if "visual_layout" in ids:
        required_lanes.append("visual_layout")
    if "audience_voice" in ids:
        required_lanes.append("audience_voice")
    if has_av or "course_structure" in ids:
        required_lanes.append("audio_video")
    if route == "mixed_corpus" and role_counts.get("tabular_data", 0):
        required_lanes.append("tabular_data")
    if route == "mixed_corpus" and has_metrics:
        required_lanes.append("performance_table")

    boundaries = []
    if has_metrics:
        boundaries.append("后台表负责证明记录到的表现，正文和视觉只用于提出机制线索，不能把相关写成因果")
    if has_visual or "visual_layout" in ids:
        boundaries.append("只有实际检查过的图片、页面或视频帧才能支持视觉结论")
    if has_audience or "audience_voice" in ids:
        boundaries.append("评论只代表参与评论的人，不能自动代表全部读者")
    if not boundaries:
        boundaries.append("仅根据当前资料形成有边界的描述和推断，不补造缺失数据")
    if route == "repeated_operational_tables":
        boundaries.extend([
            "文件夹日期、订单日期、推广日期、退款日期和库存快照日期是不同时间轴，未经映射不得混用",
            "排名缺席、字段缺失和真实零值必须分开；不把TopN未出现的实体补成零",
            "变化点只作为排查候选，不自动归因于活动、代理、平台或经营动作",
            "平台是必选分析维度；平台口径不同则先分别计算，再在兼容指标上汇总",
        ])

    fingerprint = hashlib.sha256((goal + "|" + route + "|" + ",".join(item["id"] for item in dimensions)).encode("utf-8")).hexdigest()[:12]
    method_fingerprint = hashlib.sha256(
        (SKILL_VERSION + "|" + route + "|" + ",".join(sorted(set(supporting))) + "|" + ",".join(sorted(ids))).encode("utf-8")
    ).hexdigest()
    return {
        "plan_version": "1.6",
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "user_goal": goal,
        "decision_question": goal.strip(),
        "recognized_dimensions": [{"id": item["id"], "label": item["label"]} for item in dimensions],
        "primary_route": route,
        "route_confidence": confidence,
        "supporting_modules": list(dict.fromkeys(supporting)),
        "method_fingerprint": method_fingerprint,
        "comparison_unit": comparison_unit,
        "recommended_sampling_strategy": sampling,
        "angle_discovery": {
            "requested": angle_discovery_requested,
            "status": "required" if angle_discovery_requested else "not_requested",
            "candidate_limit": 8,
            "adopted_angle_limit": 4,
            "selection_policy": "candidate_generation_then_evidence_screen",
            "required_checks": [
                "decision_relevance",
                "answerable_from_declared_scope",
                "coverage_plan",
                "distinct_from_other_candidates",
                "action_value",
                "overreach_risk",
            ],
        },
        "host_context_review": {
            "required": not bool(dimensions),
            "reason": "本轮原话没有可确定路由的分析维度；宿主智能体必须结合可见对话上下文解析承接意图，但不得改写 decision_question。" if not dimensions else None,
            "may_use_conversation_history": True,
            "must_record_route_or_angle_override_reason": True,
        },
        "corpus_shape": {
            "canonical_items": int((inventory.get("summary") or {}).get("canonical_items") or sum(role_counts.values())),
            "role_diversity": role_diversity,
            "container_diversity": container_diversity,
            "by_evidence_role": role_counts,
            "by_container_type": container_counts,
            "explicit_mixed_goal": explicit_mixed_goal,
            "date_partition_count": date_partition_count,
            "repeated_table_family_count": repeated_table_family_count,
            "repeated_operational_shape": repeated_operational_shape,
            "explicit_method_route_intent": explicit_method_intent,
            "scope_gate_required": mixed_scope_needs_gate,
            "scope_gate_ready": scope_gate_ready,
        },
        "corpus_scope_gate": {
            "provided": scope_gate is not None,
            "contract_version": scope_gate.get("contract_version") if scope_gate else None,
            "next_action": scope_gate.get("next_action") if scope_gate else "compile_scope_before_analysis" if mixed_scope_needs_gate else "not_required",
            "deep_analysis_allowed": scope_gate.get("deep_analysis_allowed") if scope_gate else not mixed_scope_needs_gate,
            "selected_family_id": scope_gate.get("selected_family_id") if scope_gate else None,
            "selected_source_count": len(scope_gate.get("selected_source_ids", [])) if scope_gate else 0,
        },
        "available_evidence_roles": role_counts,
        "required_evidence_roles": list(dict.fromkeys(required_lanes)),
        "missing_evidence": missing,
        "evidence_boundaries": boundaries,
        "report_depth": "deep" if route in {"account_content_performance", "mixed_corpus", "repeated_operational_tables"} else "standard",
        "deliverable_mode": "workbook_primary_html_reading" if route == "repeated_operational_tables" else "markdown_data_attachments" if route in {"inventory_and_profile", "tabular_analysis"} else "html_primary",
        "novel_case_key": f"novel-{fingerprint}" if route == "novel_route" else None,
        "review_required": confidence == "low",
        "review_note": "模型必须复核目的识别；若改路线，需在运行上下文记录改变理由。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Recognize the user's analysis purpose and produce an auditable Data Lens route plan.")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--scope-gate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.inventory, *([args.scope_gate] if args.scope_gate else [])])
    result = build_plan(args.goal, load_json(args.inventory), load_json(args.scope_gate) if args.scope_gate else None)
    write_json(args.output, result)
    print(f"plan={args.output} route={result['primary_route']} confidence={result['route_confidence']} dimensions={len(result['recognized_dimensions'])}")


if __name__ == "__main__":
    main()
