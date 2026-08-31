from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _common import classify_title, load_json, safe_number, write_json


STRATEGIES = {
    "auto", "pilot", "full_census", "stratified", "latest", "earliest", "spread_time",
    "balanced_topic", "performance_contrast", "family_stratified",
}
ANALYSIS_UNITS = {"auto", "article", "document", "workbook", "table", "image", "recording", "source_container"}
ARTICLE_EXTENSIONS = {".md", ".txt", ".html", ".htm", ".mhtml"}


def source_bucket(path_value: Any, inventory: dict[str, Any]) -> str:
    path = Path(str(path_value or ""))
    roots = [Path(value) for value in inventory.get("supplied_paths", []) if value]
    matching: list[tuple[int, Path]] = []
    for root in roots:
        try:
            relative = path.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        matching.append((len(root.parts), root))
        if len(roots) == 1 and relative.parts:
            return relative.parts[0] if len(relative.parts) > 1 else root.name
    if matching:
        return max(matching, key=lambda item: item[0])[1].name
    return path.parent.name or "未识别目录"


def infer_business_role(item: dict[str, Any]) -> str:
    text = f"{item.get('path', '')} {item.get('title', '')}".lower()
    role = str(item.get("evidence_role") or "unclassified")
    suffix = str(Path(str(item.get("path") or "")).suffix).lower()
    if re.search(r"股票|证券|k线|均线|涨停|选股|stocks?", text, re.I):
        return "股票与投资研究"
    if role == "audience_voice":
        if re.search(r"生成|合成|测试|模拟|扣子", text, re.I):
            return "合成话术测试"
        if re.search(r"模板|要素|schema|字段", text, re.I):
            return "评论分析模板"
        return "真实评论与用户声音"
    if role == "performance_table":
        if re.search(r"排行|榜单|市场|竞品|行业", text, re.I) and not re.search(r"后台|账号|自有|发布|文章", text, re.I):
            return "外部市场观察"
        return "账号与业务表现"
    if role == "tabular_data":
        if re.search(r"需求|rpa|自动化", text, re.I):
            return "自动化需求与执行"
        if re.search(r"对接|排期|交付|进度|周报", text, re.I):
            return "执行与交付记录"
        if re.search(r"评论|评价|问大家|voc", text, re.I):
            return "评论与用户声音"
        if re.search(r"打品|市场|竞品|关键词|排行|投放", text, re.I):
            return "电商市场研究"
        return "待逐表确认的数据工作簿"
    if role == "visual_layout":
        if re.search(r"包装|六面图|说明书|成分|产品图", text, re.I):
            return "产品事实与包装"
        if re.search(r"主图|详情|线框|车图|海报|素材", text, re.I):
            return "电商视觉与创意"
        return "待映射视觉资产"
    if role == "audio_video":
        return "视频成品与演示"
    if re.search(r"skill|技能", text, re.I):
        return "可复用Skill与方法"
    if re.search(r"rpa|xpath|自动化|工作流|workflow|扣子", text, re.I):
        return "自动化与智能体工作流"
    if re.search(r"报告|复盘|周报|总结", text, re.I):
        return "分析报告与执行复盘"
    if re.search(r"课程|培训|教程|ppt|课件", text, re.I) or suffix in {".ppt", ".pptx"}:
        return "课程与培训材料"
    if re.search(r"市场|竞品|打品|关键词|标题|评论分析", text, re.I):
        return "电商市场研究"
    if re.search(r"主图|详情页|作图|生图|提示词|aigc", text, re.I):
        return "电商视觉与创意"
    if suffix in {".zip", ".rar", ".7z", ".exe", ".rp", ".db"}:
        return "程序包与归档"
    if role == "content_text":
        category = classify_title(str(item.get("title") or ""))
        return category if category != "其他" else "通用AI资料"
    return "待识别业务资料"


def inferred_container_type(item: dict[str, Any]) -> str:
    if item.get("container_type"):
        return str(item["container_type"])
    suffix = str(item.get("extension") or "").lower()
    if suffix in ARTICLE_EXTENSIONS:
        return "article_candidate"
    if suffix in {".pdf", ".docx"}:
        return "document"
    if suffix in {".xls", ".xlsx"}:
        return "workbook"
    if suffix in {".csv", ".tsv"}:
        return "table"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "image"
    if suffix in {".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv"}:
        return "recording"
    return "file"


def unit_matches(item: dict[str, Any], requested: str) -> bool:
    if requested in {"auto", "source_container"}:
        return True
    kind = inferred_container_type(item)
    if requested == "article":
        return kind == "article_candidate"
    if requested == "document":
        return item.get("evidence_role") == "content_text"
    return kind == requested


def selectable_sources(
    inventory: dict[str, Any], analysis_unit: str = "auto", include_roles: set[str] | None = None,
    completed_units: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if analysis_unit not in ANALYSIS_UNITS:
        raise ValueError(f"invalid analysis unit: {analysis_unit}")
    exclusions: Counter[str] = Counter()
    raw: list[dict[str, Any]] = []
    for item in inventory.get("files", []):
        source_identity = str(item.get("source_container_id") or item.get("path") or "")
        review_status = str(item.get("manual_review_status") or item.get("human_review_status") or "").lower()
        if item.get("human_review_complete") is True or review_status in {"complete", "completed", "fully_confirmed", "human_confirmed"}:
            exclusions["already_human_confirmed"] += 1
            continue
        if completed_units and source_identity in completed_units:
            exclusions["already_human_confirmed"] += 1
            continue
        if not item.get("canonical", True):
            exclusions["noncanonical_or_exact_duplicate"] += 1
            continue
        role = str(item.get("evidence_role") or "unclassified")
        if include_roles and role not in include_roles:
            exclusions[f"role_{role}"] += 1
            continue
        if not unit_matches(item, analysis_unit):
            exclusions["different_container_type"] += 1
            continue
        title = item.get("title") or item.get("name") or ""
        kind = inferred_container_type(item)
        raw.append(
            {
                "source_container_id": item.get("source_container_id"),
                "path": item.get("path"),
                "source_paths": [item.get("path")],
                "title": title,
                "publish_date": item.get("publish_date"),
                "category": classify_title(str(title)) if role == "content_text" else kind,
                "container_type": kind,
                "evidence_role": role,
                "source_family_key": item.get("source_family_key") or item.get("path"),
                "possible_sequence_key": item.get("possible_sequence_key"),
                "capture_session_key": item.get("capture_session_key"),
                "capture_session_relation": item.get("capture_session_relation"),
                "top_level_bucket": source_bucket(item.get("path"), inventory),
                "requires_unit_review": True,
                "provisional_analysis_unit": "article" if kind == "article_candidate" else kind,
                "size_bytes": item.get("size_bytes") or 0,
                "modified_at": item.get("modified_at") or 0,
            }
        )
        raw[-1]["business_role"] = infer_business_role(raw[-1])

    # Keep one provisional representative per possible version family. Alternatives stay visible for review.
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in raw:
        families[str(item["source_family_key"])].append(item)
    collapsed: list[dict[str, Any]] = []
    for members in families.values():
        ranked = sorted(members, key=lambda row: (float(row.get("modified_at") or 0), int(row.get("size_bytes") or 0), str(row.get("path"))), reverse=True)
        chosen = dict(ranked[0])
        if len(ranked) > 1:
            chosen["possible_version_paths"] = [row["path"] for row in ranked[1:]]
            chosen["version_resolution"] = "provisional_latest_modified"
            exclusions["possible_version_siblings"] += len(ranked) - 1
        collapsed.append(chosen)

    # A numbered screenshot/page sequence is one source group candidate, not several independent cases.
    sequence_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singles: list[dict[str, Any]] = []
    for item in collapsed:
        key = item.get("possible_sequence_key")
        if item.get("container_type") == "image" and key:
            sequence_groups[str(key)].append(item)
        else:
            singles.append(item)
    for members in sequence_groups.values():
        if len(members) == 1:
            singles.extend(members)
            continue
        ordered = sorted(members, key=lambda row: str(row.get("path") or "").lower())
        grouped = dict(ordered[0])
        grouped["source_paths"] = [row["path"] for row in ordered]
        grouped["container_type"] = "image_group"
        grouped["provisional_analysis_unit"] = "image_sequence_candidate"
        grouped["sequence_resolution"] = "grouped_for_review"
        singles.append(grouped)
        exclusions["sequence_pages_grouped"] += len(ordered) - 1
    return singles, dict(sorted(exclusions.items()))


def canonical_articles(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    items, _ = selectable_sources(inventory, "article", {"content_text"})
    return items


def evenly_spaced(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count >= len(items):
        return items[:]
    if count == 1:
        return [items[len(items) // 2]]
    indices = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in dict.fromkeys(indices)]


def balanced_topic(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sorted(items, key=lambda row: (row.get("publish_date") or "", row.get("title") or ""), reverse=True):
        groups[str(item.get("category") or "其他")].append(item)
    order = sorted(groups, key=lambda key: (-len(groups[key]), key))
    selected: list[dict[str, Any]] = []
    cursor = 0
    while len(selected) < min(count, len(items)) and order:
        key = order[cursor % len(order)]
        if groups[key]:
            selected.append(groups[key].pop(0))
        if not groups[key]:
            order.remove(key)
            cursor = 0
        else:
            cursor += 1
    return selected


def stratified(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sorted(items, key=lambda row: (row.get("publish_date") or "", row.get("title") or ""), reverse=True):
        key = f"{item.get('evidence_role')}|{item.get('container_type')}|{item.get('category')}"
        groups[key].append(item)
    order = sorted(groups, key=lambda key: (-len(groups[key]), key))
    selected: list[dict[str, Any]] = []
    while order and len(selected) < min(count, len(items)):
        for key in list(order):
            if len(selected) >= min(count, len(items)):
                break
            selected.append(groups[key].pop(0))
            if not groups[key]:
                order.remove(key)
    return selected


def provisional_family(item: dict[str, Any]) -> str:
    if item.get("business_role"):
        return str(item["business_role"])
    role = str(item.get("evidence_role") or "unclassified")
    if role == "content_text":
        return str(item.get("category") or "其他正文")
    return {
        "performance_table": "表现数据",
        "tabular_data": "待筛查表格",
        "visual_layout": "视觉资产",
        "audience_voice": "评论与用户声音",
        "audio_video": "音视频课程或演示",
        "unclassified": "待识别资料",
    }.get(role, role)


def family_stratified(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    enriched = [{**item, "provisional_family": provisional_family(item)} for item in items]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    directory_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ordered_items = sorted(enriched, key=lambda row: (row.get("publish_date") or "", row.get("size_bytes") or 0, row.get("title") or ""), reverse=True)
    for item in ordered_items:
        groups[str(item["provisional_family"])].append(item)
        directory_groups[str(item.get("top_level_bucket") or "未识别目录")].append(item)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        source_id = str(item.get("source_container_id") or item.get("path"))
        if source_id not in selected_ids and len(selected) < min(count, len(items)):
            selected.append(item)
            selected_ids.add(source_id)

    # A mixed-corpus sample must not silently omit an explicitly supplied directory.
    for directory in sorted(directory_groups, key=lambda key: (-len(directory_groups[key]), key)):
        add(directory_groups[directory][0])

    # Then cover every business family before allocating the remaining budget by round robin.
    for family in sorted(groups, key=lambda key: (-len(groups[key]), key)):
        for item in groups[family]:
            if str(item.get("source_container_id") or item.get("path")) not in selected_ids:
                add(item)
                break

    active = sorted(groups, key=lambda key: (-len(groups[key]), key))
    while active and len(selected) < min(count, len(items)):
        for key in list(active):
            if len(selected) >= min(count, len(items)):
                break
            while groups[key] and str(groups[key][0].get("source_container_id") or groups[key][0].get("path")) in selected_ids:
                groups[key].pop(0)
            if groups[key]:
                add(groups[key].pop(0))
            if not groups[key]:
                active.remove(key)
    return selected


def performance_rows(matched: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    eligible: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for row in matched.get("records", []):
        match_type = row.get("source_match_type")
        level = row.get("source_evidence_level")
        readers = safe_number(row.get("total_readers"))
        if match_type != "exact":
            excluded[f"match_{match_type or 'missing'}"] += 1
        elif level != "confirmed_total":
            excluded[f"evidence_{level or 'missing'}"] += 1
        elif readers is None:
            excluded["total_readers_missing"] += 1
        else:
            eligible.append(
                {
                    "path": row.get("archive_path"),
                    "title": row.get("source_title") or row.get("archive_title"),
                    "publish_date": row.get("publish_date"),
                    "category": row.get("content_category") or classify_title(str(row.get("archive_title") or "")),
                    "total_readers": readers,
                }
            )
    eligible.sort(key=lambda item: (float(item["total_readers"]), item.get("publish_date") or "", item.get("title") or ""), reverse=True)
    return eligible, excluded


def contrast(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count >= len(items):
        result = []
        midpoint = (len(items) - 1) / 2
        for index, item in enumerate(items):
            band = "high" if index < midpoint else "low" if index > midpoint else "middle"
            result.append({**item, "selection_band": band})
        return result
    high_n = count // 2
    low_n = count // 2
    result = [{**item, "selection_band": "high"} for item in items[:high_n]]
    used = {item["path"] for item in result}
    if count % 2:
        middle = items[len(items) // 2]
        if middle["path"] not in used:
            result.append({**middle, "selection_band": "middle"})
            used.add(middle["path"])
    for item in reversed(items[-low_n:]):
        if item["path"] not in used:
            result.append({**item, "selection_band": "low"})
            used.add(item["path"])
    return result


def build_sample(
    inventory: dict[str, Any], strategy: str, count: int, matched: dict[str, Any] | None = None,
    analysis_unit: str = "auto", include_roles: set[str] | None = None,
    completed_units: set[str] | None = None,
) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    if count < 1:
        raise ValueError("count must be positive")
    sources, source_exclusions = selectable_sources(inventory, analysis_unit, include_roles, completed_units)
    articles = [item for item in sources if item.get("container_type") == "article_candidate"]
    warnings: list[str] = []
    exclusions: dict[str, int] = dict(source_exclusions)
    effective = strategy
    if strategy == "auto":
        effective = "performance_contrast" if matched else "balanced_topic" if sources and len(articles) == len(sources) else "stratified"

    if effective == "performance_contrast":
        if matched is None:
            raise ValueError("performance_contrast requires --matched")
        eligible, excluded = performance_rows(matched)
        selected = contrast(eligible, min(count, len(eligible)))
        exclusions.update(dict(sorted(excluded.items())))
        inclusion = "只纳入标题与日期精确匹配、且存在文章级总阅读人数的文章"
        warnings.append("高低表现对照只能产生内容线索，不能证明内容特征导致了表现差异")
        if len(eligible) < 12:
            warnings.append("可比较文章少于12篇，分组结果容易受单篇异常值影响")
    else:
        known = sorted(sources, key=lambda item: (item.get("publish_date") or "", item.get("title") or ""), reverse=True)
        if effective == "full_census":
            selected = known
            inclusion = "纳入去除确定重复后所有符合角色和容器条件的来源组"
        elif effective in {"pilot", "stratified", "family_stratified"}:
            selected = family_stratified(known, min(count, len(known))) if effective == "family_stratified" else stratified(known, min(count, len(known)))
            if effective == "family_stratified":
                inclusion = "先覆盖每个暂定资料家族，再在较大家族中轮换扩样；家族名必须在语义阅读后确认"
                warnings.append("资料家族来自轻量规则，只用于保证抽样覆盖，不能直接作为最终分析结论")
            else:
                inclusion = "按证据角色、来源容器和粗分类轮换选择" if effective == "stratified" else "未知类型先按来源角色和容器分层选择小样本试跑"
            if effective == "pilot":
                warnings.append("试跑样本只验证分析方法是否适配，不能代表整批资料")
        elif effective == "latest":
            selected = known[:count]
            inclusion = "按发布日期从新到旧选择"
            warnings.append("最近样本反映当前内容方向，不能代表作者长期稳定习惯")
        elif effective == "earliest":
            selected = list(reversed(known))[:count]
            inclusion = "按发布日期从旧到新选择"
            warnings.append("早期样本适合看起点，不代表当前内容能力")
        elif effective == "spread_time":
            selected = evenly_spaced(list(reversed(known)), min(count, len(known)))
            inclusion = "在可识别日期的文章序列中等距取样"
            warnings.append("时间等距不能自动平衡主题和文章表现")
        elif effective == "balanced_topic":
            selected = balanced_topic(known, count)
            inclusion = "先用标题规则粗分主题，再在各主题间轮换取样"
            warnings.append("主题分类来自标题规则，需在阅读正文后复核")
        else:
            raise ValueError(f"unsupported strategy: {effective}")

    category_counts = Counter(str(item.get("category") or "其他") for item in selected)
    if selected:
        top_category, top_count = category_counts.most_common(1)[0]
        if len(selected) >= 5 and top_count / len(selected) >= 0.6:
            warnings.append(f"样本中“{top_category}”占{top_count}/{len(selected)}，跨主题结论可能偏向这一类内容")
    missing_dates = sum(1 for item in sources if not item.get("publish_date"))
    if missing_dates:
        warnings.append(f"有{missing_dates}个来源容器无法识别发布日期，涉及时间排序时可能被放到末尾")
    if exclusions.get("possible_version_siblings"):
        warnings.append("检测到可能的版本文件；当前只临时选择最近修改的版本，正式分析前必须人工确认版本关系")
    if exclusions.get("sequence_pages_grouped"):
        warnings.append("编号相近的图片已按连续页候选合并，仍需确认它们是否属于同一分析对象")
    if any(item.get("capture_session_relation") == "same_capture_session_candidate" for item in selected):
        warnings.append("样本含同一时段连续截图；截图数量不得当作岗位、项目或页面数量，必须先做语义分组")

    unit_types = {str(item.get("provisional_analysis_unit")) for item in selected}
    resolved_unit = next(iter(unit_types)) if len(unit_types) == 1 else "mixed_source_container"
    eligible_family_counts = Counter(provisional_family(item) for item in sources)
    selected_family_counts = Counter(str(item.get("provisional_family") or provisional_family(item)) for item in selected)
    family_coverage = [
        {
            "family": family,
            "eligible_count": eligible_count,
            "selected_count": selected_family_counts.get(family, 0),
            "coverage_status": "full" if selected_family_counts.get(family, 0) == eligible_count else "partial" if selected_family_counts.get(family, 0) else "not_selected",
        }
        for family, eligible_count in sorted(eligible_family_counts.items())
    ]
    eligible_directory_counts = Counter(str(item.get("top_level_bucket") or "未识别目录") for item in sources)
    selected_directory_counts = Counter(str(item.get("top_level_bucket") or "未识别目录") for item in selected)
    directory_coverage = [
        {
            "directory": directory,
            "eligible_count": eligible_count,
            "selected_count": selected_directory_counts.get(directory, 0),
            "coverage_status": "covered" if selected_directory_counts.get(directory, 0) else "not_selected",
        }
        for directory, eligible_count in sorted(eligible_directory_counts.items())
    ]
    missed_directories = [item["directory"] for item in directory_coverage if item["coverage_status"] == "not_selected"]
    if missed_directories:
        warnings.append("以下明确输入目录没有样本：" + "、".join(missed_directories))

    return {
        "selection_version": "1.3",
        "strategy": effective,
        "requested_count": count,
        "eligible_count": len(eligible) if effective == "performance_contrast" else len(sources),
        "selected_count": len(selected),
        "analysis_unit": "article" if effective == "performance_contrast" else resolved_unit,
        "analysis_unit_status": "provisional_requires_semantic_confirmation",
        "source_container_count": len(sources),
        "inclusion_rule": inclusion,
        "exclusions": exclusions,
        "selected_category_counts": dict(sorted(category_counts.items())),
        "family_coverage": family_coverage,
        "directory_coverage": directory_coverage,
        "expansion_rule": "每个家族先完成小批语义阅读；若连续两个批次仍出现新的方法、条件、冲突或资料角色则继续扩样，否则记录稳定状态。全量很小时直接普查。",
        "bias_warnings": list(dict.fromkeys(warnings)),
        "selected": selected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Select and document a Data Lens sample without hiding sampling bias.")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="auto")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--matched", type=Path)
    parser.add_argument("--analysis-unit", choices=sorted(ANALYSIS_UNITS), default="auto")
    parser.add_argument("--include-role", action="append", dest="include_roles")
    parser.add_argument("--completed-units", type=Path, help="JSON array or object with completed source IDs/paths to skip")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    completed_units: set[str] | None = None
    if args.completed_units:
        payload = load_json(args.completed_units)
        values = payload if isinstance(payload, list) else payload.get("completed_units", [])
        completed_units = {str(value) for value in values}
    result = build_sample(
        load_json(args.inventory), args.strategy, args.count,
        load_json(args.matched) if args.matched else None,
        args.analysis_unit, set(args.include_roles) if args.include_roles else None,
        completed_units,
    )
    write_json(args.output, result)
    print(f"sample={args.output} strategy={result['strategy']} selected={result['selected_count']}/{result['eligible_count']}")


if __name__ == "__main__":
    main()
