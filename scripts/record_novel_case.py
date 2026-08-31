from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from _common import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an experimental Data Lens novel-route case record.")
    parser.add_argument("--user-goal", required=True)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--dimension", action="append", default=[])
    parser.add_argument("--evidence-role", action="append", default=[])
    parser.add_argument("--nearest-route", action="append", default=[])
    parser.add_argument("--why-not-fit", action="append", default=[])
    parser.add_argument("--pilot-method", required=True)
    parser.add_argument("--pilot-scope", default="3–5 items")
    parser.add_argument("--comparison-unit", required=True)
    parser.add_argument("--sampling-reason", required=True)
    parser.add_argument("--missing-evidence", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now().astimezone()
    payload = {
        "case_id": f"novel-{now.strftime('%Y%m%d-%H%M%S')}",
        "status": "experimental",
        "created_at": now.isoformat(),
        "user_goal": args.user_goal,
        "requested_dimensions": args.dimension,
        "input_combination": args.input,
        "evidence_roles": args.evidence_role,
        "nearest_routes": args.nearest_route,
        "why_existing_routes_do_not_fit": args.why_not_fit,
        "pilot_method": args.pilot_method,
        "pilot_scope": args.pilot_scope,
        "comparison_unit": args.comparison_unit,
        "sampling_reason": args.sampling_reason,
        "what_worked": [],
        "what_failed": [],
        "missing_evidence": args.missing_evidence,
        "user_accepted": None,
        "promotion_recommendation": "hold",
    }
    write_json(args.output, payload)
    print(f"novel_case={args.output}")


if __name__ == "__main__":
    main()
