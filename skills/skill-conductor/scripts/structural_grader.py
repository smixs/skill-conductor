#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Deterministic structural grader for monocle-instrumented skill runs.

Reads spans emitted by monocle's FileSpanExporter (one JSON file per trace
in MONOCLE_TRACE_OUTPUT_PATH), evaluates a list of structural assertions
from evals.json, and writes a JSON result.

Usage:
    structural_grader.py \\
        --spans-dir <run-dir>/spans \\
        --assertions <skill>/evals/evals.json \\
        --eval-id 1 \\
        --output <run-dir>/structural.json

If the spans dir is missing or empty, the grader writes a result with
skipped=true rather than failing — this is the graceful no-op path for
skills that don't opt into monocle tracing.

Assertion grammar (each entry in evals[].structural_assertions):

    {kind: "span_present", name: "pii.scrub_file"}
    {kind: "span_absent",  name: "pii.scrub_file"}
    {kind: "span_count",   name: "pii.scrub_file", op: ">=", value: 1}
    {kind: "span_attribute", name: "pii.scrub_file", key: "denylist_version", op: "==", value: "v3"}
    {kind: "span_order",   before: "validate.run", after: "deploy.run"}
    {kind: "no_error_spans"}

`name` matches against the span's `name` field. Attributes are looked up
inside `span.attributes`. Comparisons use standard Python operators on the
extracted value.
"""

import argparse
import glob
import json
import operator
import sys
from pathlib import Path
from typing import Any


OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">":  operator.gt,
    ">=": operator.ge,
    "<":  operator.lt,
    "<=": operator.le,
}


def load_spans(spans_dir: Path) -> list[dict]:
    """Load every span from every monocle_trace_*.json in the directory.

    monocle's FileSpanExporter writes one JSON file per trace. Each file
    contains either a single span dict or a list of span dicts depending
    on flush timing. We accept both.
    """
    spans: list[dict] = []
    if not spans_dir.is_dir():
        return spans
    for path in sorted(spans_dir.glob("monocle_trace_*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            spans.extend(data)
        elif isinstance(data, dict):
            spans.append(data)
    return spans


def find_spans(spans: list[dict], name: str) -> list[dict]:
    return [s for s in spans if s.get("name") == name]


def get_attribute(span: dict, key: str) -> Any:
    """Return the span attribute matching `key`.

    Monocle output_processors store attributes under `entity.<N>.<key>`
    where N is a per-span counter. We accept either the exact key or any
    `entity.*.<key>` suffix match.
    """
    attrs = span.get("attributes", {}) or {}
    if key in attrs:
        return attrs[key]
    suffix = f".{key}"
    for k, v in attrs.items():
        if k.startswith("entity.") and k.endswith(suffix):
            return v
    return None


def _coerce_for_compare(value: Any, target: Any) -> Any:
    """If target is numeric and value is a numeric string, coerce.

    monocle requires accessor return values to be str or list, so authors
    stringify ints. Numeric assertions still want to compare as numbers.
    """
    if isinstance(value, str) and isinstance(target, (int, float)):
        try:
            return type(target)(value) if "." in value or isinstance(target, float) else int(value)
        except ValueError:
            return value
    return value


def evaluate(assertion: dict, spans: list[dict]) -> dict:
    kind = assertion.get("kind")

    if kind == "span_present":
        matches = find_spans(spans, assertion["name"])
        return {
            "passed": len(matches) > 0,
            "evidence": f"found {len(matches)} span(s) named '{assertion['name']}'",
        }

    if kind == "span_absent":
        matches = find_spans(spans, assertion["name"])
        return {
            "passed": len(matches) == 0,
            "evidence": f"found {len(matches)} span(s) named '{assertion['name']}' (expected 0)",
        }

    if kind == "span_count":
        matches = find_spans(spans, assertion["name"])
        op = OPS[assertion["op"]]
        ok = op(len(matches), assertion["value"])
        return {
            "passed": ok,
            "evidence": f"count={len(matches)} {assertion['op']} {assertion['value']}",
        }

    if kind == "span_attribute":
        matches = find_spans(spans, assertion["name"])
        if not matches:
            return {"passed": False, "evidence": f"no span named '{assertion['name']}'"}
        key, want, op = assertion["key"], assertion["value"], OPS[assertion["op"]]
        raw_values = [get_attribute(s, key) for s in matches]
        coerced = [_coerce_for_compare(v, want) for v in raw_values]
        ok = any(v is not None and op(v, want) for v in coerced)
        return {
            "passed": ok,
            "evidence": f"attribute '{key}' values={raw_values}, expected {assertion['op']} {want}",
        }

    if kind == "span_order":
        before = find_spans(spans, assertion["before"])
        after = find_spans(spans, assertion["after"])
        if not before or not after:
            return {
                "passed": False,
                "evidence": f"missing spans: before={len(before)} after={len(after)}",
            }
        b_end = min(s.get("end_time", "") for s in before)
        a_start = min(s.get("start_time", "") for s in after)
        return {
            "passed": b_end <= a_start,
            "evidence": f"before ends at {b_end}, after starts at {a_start}",
        }

    if kind == "no_error_spans":
        errored = [s for s in spans if (s.get("status") or {}).get("status_code") == "ERROR"]
        return {
            "passed": len(errored) == 0,
            "evidence": f"{len(errored)} error span(s)",
        }

    return {"passed": False, "evidence": f"unknown assertion kind: {kind!r}"}


def load_assertions(path: Path, eval_id: int | None) -> list[dict]:
    data = json.loads(path.read_text())
    evals = data.get("evals", [])
    if eval_id is None:
        # Flatten across all evals
        out = []
        for e in evals:
            out.extend(e.get("structural_assertions") or [])
        return out
    for e in evals:
        if e.get("id") == eval_id:
            return e.get("structural_assertions") or []
    return []


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--spans-dir", required=True, type=Path)
    p.add_argument("--assertions", required=True, type=Path)
    p.add_argument("--eval-id", type=int, default=None)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    assertions = load_assertions(args.assertions, args.eval_id)
    spans = load_spans(args.spans_dir)

    # Only skip when the eval itself declares no structural requirements
    # (genuine markdown-skill case). When assertions are declared but no
    # spans exist, evaluate normally — each assertion fails with clear
    # evidence. The eval is then incomplete and the skill's quality bar
    # isn't met. This forces adoption: if you declare structural
    # requirements, you must wire monocle to satisfy them.
    if not assertions:
        result = {
            "skipped": True,
            "reason": "no structural_assertions declared for this eval",
            "summary": {"passed": 0, "failed": 0, "total": 0, "pass_rate": None},
        }
    else:
        results = []
        for a in assertions:
            r = evaluate(a, spans)
            results.append({**a, **r})
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        result = {
            "skipped": False,
            "assertions": results,
            "summary": {
                "passed": passed,
                "failed": total - passed,
                "total": total,
                "pass_rate": passed / total if total else None,
            },
            "spans_loaded": len(spans),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result.get("skipped") or result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
