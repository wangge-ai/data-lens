from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analyze_operational_facts import analyze  # noqa: E402
from baseline_preservation import build_final_review  # noqa: E402
from build_run_manifest import build_manifest  # noqa: E402
from render_report import render_findings  # noqa: E402
from validate_run_manifest import validate_manifest  # noqa: E402


class CoverageAndFinalizationRegressionTests(unittest.TestCase):
    def minimal_operational_facts(self) -> dict:
        return {
            "contract": "corpus_lens_operational_facts/1.0",
            "time_contract": {"platform_daily": "business_date"},
            "periods": [
                {"id": "before", "start": "2026-01-01", "end": "2026-01-01"},
                {"id": "after", "start": "2026-01-02", "end": "2026-01-02"},
            ],
            "platform_daily": [
                {"business_date": "2026-01-01", "platform": "shop", "orders": 10, "paid_amount": 200},
                {"business_date": "2026-01-02", "platform": "shop", "orders": 12, "paid_amount": 180},
            ],
            "coverage": [
                {
                    "collection_date": "2026-08-16",
                    "family": "category",
                    "analysis_unit": "primary_category_row",
                    "file_count": 7,
                    "row_count": 21,
                    "schema_fingerprint": "category-v1",
                },
                {
                    "collection_date": "2026-08-16",
                    "family": "category",
                    "analysis_unit": "leaf_category_row",
                    "file_count": 7,
                    "row_count": 106,
                    "schema_fingerprint": "category-v1",
                },
            ],
        }

    def test_coverage_counts_remain_separate_by_analysis_unit(self) -> None:
        analysis, quality = analyze(self.minimal_operational_facts())
        self.assertEqual(quality["gate_status"], "pass")
        self.assertEqual(quality["checks"]["coverage_claim_rows"], 2)
        counts = {
            row["analysis_unit"]: row["row_count"]
            for row in analysis["coverage_summary"]
        }
        self.assertEqual(counts, {
            "primary_category_row": 21,
            "leaf_category_row": 106,
        })
        self.assertEqual(analysis["coverage_break_candidates"], [])

    def test_repeated_snapshot_coverage_is_summed_for_reader_claims(self) -> None:
        facts = self.minimal_operational_facts()
        facts["coverage"] = [
            {
                "collection_date": "2026-01-01",
                "family": "price_band",
                "analysis_unit": "business_date_x_price_band",
                "file_count": 1,
                "row_count": 4,
            },
            {
                "collection_date": "2026-01-02",
                "family": "price_band",
                "analysis_unit": "business_date_x_price_band",
                "file_count": 1,
                "row_count": 5,
            },
            {
                "collection_date": "2026-01-01",
                "family": "category",
                "analysis_unit": "leaf_category_row",
                "file_count": 1,
                "row_count": 15,
            },
        ]
        analysis, quality = analyze(facts)
        self.assertEqual(quality["gate_status"], "pass")
        self.assertEqual(quality["checks"]["coverage_claim_rows"], 2)
        claims = {
            (row["family"], row["analysis_unit"]): row
            for row in analysis["coverage_summary"]
        }
        price = claims[("price_band", "business_date_x_price_band")]
        self.assertEqual(price["file_count"], 2)
        self.assertEqual(price["row_count"], 9)
        self.assertEqual(price["collection_periods"], 2)
        leaf = claims[("category", "leaf_category_row")]
        self.assertEqual(leaf["row_count"], 15)

    def test_one_advisory_final_review_reuses_e0_and_coverage(self) -> None:
        analysis, _ = analyze(self.minimal_operational_facts())
        review = build_final_review(
            {"retained_findings": ["保留金额链", "保留后段第二次换挡"]},
            operational_analysis=analysis,
            single_first_stop_point=True,
        )
        self.assertEqual(review["review_mode"], "single_advisory_edit_not_a_gate")
        self.assertEqual(len(review["required_findings"]), 2)
        self.assertEqual(len(review["deterministic_coverage_claims"]), 2)
        self.assertIn("exactly one first stop point", "\n".join(review["instructions"]))

    def test_advisory_review_reads_standard_nested_baseline_contract(self) -> None:
        review = build_final_review(
            {
                "contract_version": "data-lens-incremental-discovery-baseline/0.1",
                "decision_question": "为什么结果反复归零？",
                "native_first_pass": {
                    "retained_findings": ["保留普通解释", "保留关键反例"]
                },
            }
        )
        self.assertEqual(
            [item["text"] for item in review["required_findings"]],
            ["保留普通解释", "保留关键反例"],
        )

    def test_finding_keeps_action_link_out_of_reader_record(self) -> None:
        rendered = render_findings(
            [
                {
                    "title": "一个判断",
                    "fact": "一个事实",
                    "explanation": "一个解释",
                    "counterexamples": ["一个反例"],
                    "boundaries": ["一个边界"],
                    "evidence_ids": [],
                    "recommendation_ids": ["R01"],
                }
            ],
            {},
            {"R01": {"title": "第一步：只做一次验证"}},
        )
        self.assertNotIn("接下来做", rendered)
        self.assertNotIn("第一步：只做一次验证", rendered)


class CanonicalManifestBuilderRegressionTests(unittest.TestCase):
    def test_builder_output_passes_existing_manifest_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.xlsx"
            artifact = root / "analysis.json"
            implementation = root / "analysis.py"
            deliverable = root / "report.md"
            for path, content in (
                (source, "source"),
                (artifact, "{}"),
                (implementation, "print('ok')"),
                (deliverable, "# report"),
            ):
                path.write_text(content, encoding="utf-8")
            manifest = build_manifest(
                root,
                {
                    "sources": [source],
                    "deterministic_artifacts": [artifact],
                    "ledgers": [],
                    "deliverables": [deliverable],
                    "implementations": [implementation],
                    "historical_artifacts": [],
                },
                ["repeated-operational-tables@1.0"],
            )
            manifest_path = root / "run_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = validate_manifest(manifest_path)
            self.assertTrue(result["valid"], result["errors"])
            self.assertEqual(result["checks"]["bound_files_recomputed"], 4)


if __name__ == "__main__":
    unittest.main()
