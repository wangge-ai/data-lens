from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _common import guard_cli_output, load_json, write_json
from validate_finding_ledger import validate


def build_context(ledger: dict[str, Any], max_findings: int = 6, max_cards: int = 36, max_chars: int = 36_000) -> dict[str, Any]:
    errors = validate(ledger)
    if errors:
        raise ValueError("invalid finding ledger: " + "; ".join(errors))
    if max_findings < 1 or max_cards < 1 or max_chars < 500:
        raise ValueError("finding/card limits must be positive and max_chars must be at least 500")
    adopted = [item for item in ledger.get("candidates", []) if item.get("adopted") is True]
    adopted.sort(key=lambda item: (not item.get("anchor_eligible", False), str(item.get("finding_id"))))
    evidence = ledger.get("evidence_index") or {}
    included_findings: list[dict[str, Any]] = []
    included_cards: dict[str, dict[str, Any]] = {}
    omitted: list[dict[str, str]] = []
    used_chars = 0
    for candidate in adopted:
        finding_id = str(candidate.get("finding_id"))
        if len(included_findings) >= max_findings:
            omitted.append({"item_id": finding_id, "reason": "finding_budget"})
            continue
        finding = candidate.get("finding") or {}
        role_refs: dict[str, list[str]] = {
            "supporting": list(finding.get("supporting_evidence_refs") or []),
            "counter": list((finding.get("counterexample_search") or {}).get("evidence_refs") or []),
            "alternative": [],
            "discriminating": [],
            "robustness": [],
        }
        for alternative in finding.get("alternative_explanations") or []:
            role_refs["alternative"].extend(alternative.get("evidence_refs") or [])
            role_refs["discriminating"].extend(alternative.get("discriminating_evidence_refs") or [])
        for check in finding.get("robustness_checks") or []:
            role_refs["robustness"].extend(check.get("evidence_refs") or [])
        finding_packet = {
            "finding_id": finding_id,
            "anchor_eligible": candidate.get("anchor_eligible"),
            **finding,
            "evidence_roles": role_refs,
        }
        serialized_finding = json.dumps(finding_packet, ensure_ascii=False, separators=(",", ":"))
        new_refs = list(dict.fromkeys(ref for refs in role_refs.values() for ref in refs if ref not in included_cards))
        new_cards: list[tuple[str, dict[str, Any], int]] = []
        card_chars = 0
        for ref in new_refs:
            card = evidence[ref]
            packet = {
                "evidence_id": ref,
                "claim": card.get("claim"),
                "source": card.get("source"),
                "source_sha256": card.get("source_sha256"),
                "locator": card.get("locator"),
                "unit_id": card.get("unit_id"),
                "independence_group": card.get("independence_group"),
                "family_id": card.get("family_id"),
                "lane": card.get("lane"),
                "directness": card.get("directness"),
                "caveat": card.get("caveat"),
            }
            size = len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")))
            new_cards.append((ref, packet, size))
            card_chars += size
        if len(included_cards) + len(new_cards) > max_cards:
            omitted.append({"item_id": finding_id, "reason": "card_budget"})
            continue
        if used_chars + len(serialized_finding) + card_chars > max_chars:
            omitted.append({"item_id": finding_id, "reason": "character_budget"})
            continue
        included_findings.append(finding_packet)
        used_chars += len(serialized_finding) + card_chars
        for ref, packet, _ in new_cards:
            included_cards[ref] = packet
    if not included_findings:
        raise ValueError("no adopted finding fits the synthesis budget")
    if not any(item.get("anchor_eligible") for item in included_findings):
        raise ValueError("synthesis budget omitted every anchor finding")
    return {
        "contract_version": "data-lens-deep-synthesis-context/1.0",
        "decision_question": ledger.get("decision_question"),
        "scope_gate": ledger.get("scope_gate"),
        "adopted_findings": included_findings,
        "verified_evidence_cards": list(included_cards.values()),
        "budget": {
            "max_findings": max_findings,
            "max_cards": max_cards,
            "max_chars": max_chars,
            "used_findings": len(included_findings),
            "used_cards": len(included_cards),
            "used_chars": used_chars,
        },
        "omitted": omitted,
        "instructions": [
            "Synthesize only adopted_findings and verified_evidence_cards.",
            "Preserve support, counterexample, alternative, discriminating, and robustness roles.",
            "Do not strengthen claim_level or confidence beyond the adopted finding.",
            "A mechanism_hypothesis is not a causal conclusion.",
            "Keep every boundary and unresolved alternative visible.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a bounded synthesis packet from adopted deep findings and their verified evidence only.")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-findings", type=int, default=6)
    parser.add_argument("--max-cards", type=int, default=36)
    parser.add_argument("--max-chars", type=int, default=36_000)
    args = parser.parse_args()
    guard_cli_output(parser, args.output, [args.ledger])
    result = build_context(load_json(args.ledger), args.max_findings, args.max_cards, args.max_chars)
    write_json(args.output, result)
    print(json.dumps({"output": str(args.output.resolve()), "budget": result["budget"], "omitted": len(result["omitted"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
