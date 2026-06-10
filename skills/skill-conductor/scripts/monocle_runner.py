#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "monocle_apptrace>=0.8.4",
#   "pyyaml>=6.0",
# ]
# ///
"""Run a target Python script under monocle instrumentation.

Reads a monocle.yaml spec, registers custom wrapper_methods, sets up the
file exporter, then exec's the target script via runpy with its argv
preserved. Returns the target script's exit code.

Usage:
    monocle_runner.py --config <skill>/monocle.yaml <target.py> [args...]

Environment:
    MONOCLE_TRACE_OUTPUT_PATH  Directory for span JSON files (required to enable tracing)
    MONOCLE_WORKFLOW_NAME      Optional service-name override; defaults to skill folder name

When MONOCLE_TRACE_OUTPUT_PATH is unset, this still runs the target — but
without instrumentation overhead. The launcher decides whether to invoke
this wrapper at all; the wrapper itself doesn't enforce opt-in.

monocle.yaml format (subset of WrapperMethod fields):

    workflow_name: pii-scrubber   # optional, defaults to MONOCLE_WORKFLOW_NAME or script name
    wrappers:
      - package: scripts.scrub
        object: ""
        method: scrub_file
        span_name: pii.scrub_file
        span_type: workflow
"""

import argparse
import importlib
import os
import sys
from pathlib import Path


def load_config(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text()) or {}


def _resolve_processor(ref: str):
    """Resolve a 'module:ATTR' reference to a Python object.

    The module is imported via importlib; ATTR is fetched by getattr.
    Used for output_processor so the user can declare attribute extractors
    in a sidecar .py file (lambdas can't live in YAML).
    """
    if not ref:
        return None
    if ":" not in ref:
        raise ValueError(f"output_processor must be 'module:ATTR', got {ref!r}")
    module_name, attr = ref.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def to_wrapper_methods(wrappers: list[dict]) -> list:
    """Translate our compact YAML form into monocle WrapperMethod objects.

    Using WrapperMethod objects (not raw dicts) ensures the default
    `task_wrapper` callable is attached — raw dicts pass through to the
    instrumentor as-is and its `wrapped_by(...)` call fails when
    `wrapper_method` is missing.
    """
    from monocle_apptrace.instrumentation.common.wrapper_method import WrapperMethod
    out = []
    for w in wrappers:
        out.append(WrapperMethod(
            package=w["package"],
            object_name=w.get("object", ""),
            method=w["method"],
            span_name=w.get("span_name"),
            span_type=w.get("span_type"),
            output_processor=_resolve_processor(w.get("output_processor")),
        ))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True, type=Path)
    args, rest = parser.parse_known_args()

    if not rest or not rest[0].endswith(".py"):
        print("Usage: monocle_runner.py --config <yaml> <target.py> [args...]", file=sys.stderr)
        return 2

    target = Path(rest[0]).resolve()
    target_argv = rest

    config = load_config(args.config)
    workflow_name = (
        config.get("workflow_name")
        or os.environ.get("MONOCLE_WORKFLOW_NAME")
        or target.stem
    )

    # Path setup MUST happen before to_wrapper_methods — it resolves
    # `output_processor: "module:ATTR"` references via importlib, and
    # those modules typically live next to the target script.
    skill_root = args.config.resolve().parent
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))
    target_dir = str(target.parent)
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)

    wrapper_methods = to_wrapper_methods(config.get("wrappers", []))

    # Lazy import so a missing dependency surfaces with a clear error
    # message at the launcher level rather than at module import.
    from monocle_apptrace import setup_monocle_telemetry

    setup_monocle_telemetry(
        workflow_name=workflow_name,
        wrapper_methods=wrapper_methods,
        monocle_exporters_list="file",
        union_with_default_methods=False,
    )

    # Import the target as a real module so the wrapped function IS the
    # one that runs. runpy.run_path would execute it as __main__, which is
    # a separate module object and would bypass the wrappers.
    sys.argv = target_argv
    module_name = target.stem
    module = importlib.import_module(module_name)
    if not hasattr(module, "main"):
        print(f"target module '{module_name}' has no main() function", file=sys.stderr)
        return 2
    try:
        result = module.main()
        return result if isinstance(result, int) else 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
