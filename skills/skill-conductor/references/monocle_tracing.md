# Monocle Structural Tracing for Skills

Some eval requirements cannot be checked from output files alone. Which version of a maintained denylist applied · the exact internal redaction counter · whether a version-pinned helper was called rather than an inline equivalent — those facts live only inside the running code. NL grading reads transcripts and outputs; it cannot recover them. Monocle emits spans from the bundled scripts at runtime so the structural grader can assert on them deterministically.

## When to opt in

Add monocle ONLY when both apply:

1. The skill bundles a Python script encoding correctness-critical behavior (version pins, maintained denylists, idempotency, ordering).
2. The eval needs to assert on an internal execution fact (call count, attribute value, span ordering) that is **not** recoverable from output files.

## When NOT to use

- Pure-Markdown skills.
- Skills where the bundled script is convenience-only and any equivalent code would be equally correct.
- Evals whose quality bar is fully expressible via `expectations` (file content, transcript narration). The LLM grader is sufficient; monocle adds wiring with no signal.

When you skip, drop `monocle.yaml` and omit `structural_assertions` from `evals.json`. The structural grader returns `skipped: true` with zero overhead.

## What you add

Three files per skill that opts in:

```
<skill>/
├── monocle.yaml                 # wrapper spec (this is the opt-in signal)
├── scripts/_run.sh              # launcher that conditionally invokes monocle
└── evals/evals.json             # gains a structural_assertions field per eval
```

## monocle.yaml format

```yaml
workflow_name: pii-scrubber          # optional, defaults to skill folder name
wrappers:
  - package: scripts.scrub           # Python module path relative to skill root
    object: ""                       # empty for module-level functions; class name otherwise
    method: scrub_file               # function name to wrap
    span_name: pii.scrub_file        # name structural_assertions will match on
    span_type: workflow              # optional — "workflow" marks the root span
```

One entry per function you want assertable. Keep span names stable — assertions reference them by exact match.

## Launcher pattern (`scripts/_run.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SC_DIR="${SKILL_CONDUCTOR_DIR:-$HOME/.zeroclaw/workspace/skills/skill-conductor}"

if [ -n "${MONOCLE_TRACE_OUTPUT_PATH:-}" ] && [ -f "$SKILL_DIR/monocle.yaml" ]; then
    exec uv run "$SC_DIR/scripts/monocle_runner.py" --config "$SKILL_DIR/monocle.yaml" "$@"
else
    exec uv run "$@"
fi
```

Skill instructs the agent to call bundled scripts via `scripts/_run.sh scripts/scrub.py ...`. When `MONOCLE_TRACE_OUTPUT_PATH` is unset (production, normal use), the launcher is transparent — no monocle overhead, no extra processes. The eval harness sets the env var only when running evals.

## structural_assertions in evals.json

Add a `structural_assertions` array alongside the existing `expectations`:

```json
{
  "id": 1,
  "prompt": "Redact /tmp/customer_calls.json and write to /tmp/clean.json",
  "expectations": ["No emails appear in /tmp/clean.json"],
  "structural_assertions": [
    {"kind": "span_present", "name": "pii.scrub_file"},
    {"kind": "span_attribute", "name": "pii.scrub_file", "key": "denylist_version", "op": "==", "value": "v3"}
  ]
}
```

### Assertion kinds

| Kind | Required keys | Passes when |
|---|---|---|
| `span_present` | `name` | At least one span with this name was emitted |
| `span_absent` | `name` | No span with this name was emitted |
| `span_count` | `name`, `op`, `value` | Span count satisfies the comparison |
| `span_attribute` | `name`, `key`, `op`, `value` | At least one matching span has an attribute satisfying the comparison |
| `span_order` | `before`, `after` | Latest `before.end_time` ≤ earliest `after.start_time` |
| `no_error_spans` | — | No span has status_code == ERROR |

Operators: `==`, `!=`, `>`, `>=`, `<`, `<=`.

## How the eval harness invokes it

When running an eval for a skill that has `monocle.yaml`:

1. Create `<run_dir>/spans/` and export `MONOCLE_TRACE_OUTPUT_PATH=<run_dir>/spans/`
2. Spawn the executor as normal
3. After the executor finishes, run:

```bash
uv run scripts/structural_grader.py \
    --spans-dir <run_dir>/spans \
    --assertions <skill>/evals/evals.json \
    --eval-id <id> \
    --output <run_dir>/structural.json
```

4. `aggregate_benchmark.py` merges `structural.json` into `benchmark.json` under a `structural` key per run

When `monocle.yaml` is absent, step 1 is skipped, step 3 is also skipped, and `aggregate_benchmark.py` simply doesn't add a `structural` key. The viewer's structural column shows "—" for those runs.

## Wrapping a function — minimal example

`scripts/scrub.py`:

```python
def scrub_file(input_path: str, output_path: str, denylist_version: str = "v3") -> int:
    # ... actual scrubbing ...
    return redacted_count
```

`monocle.yaml`:

```yaml
workflow_name: pii-scrubber
wrappers:
  - package: scripts.scrub
    object: ""
    method: scrub_file
    span_name: pii.scrub_file
    span_type: workflow
```

eval entry:

```json
{
  "kind": "span_present",
  "name": "pii.scrub_file"
}
```

After running, monocle writes `<run_dir>/spans/monocle_trace_pii-scrubber_<traceid>_<ts>.json`. The structural grader matches `pii.scrub_file` and reports pass.

## Adding attributes to spans

Span attributes are declared via monocle's `output_processor` pattern — a Python dict of accessor lambdas that read function args/kwargs/return value. Keep this in a sidecar `.py` file next to your script so user code stays free of OTel imports.

### Why not call `trace.set_attribute` from inside the function?

Monocle isolates user spans from instrumentation spans by default, so `trace.get_current_span()` inside the wrapped function returns a NonRecordingSpan — attributes are silently dropped. The escape hatch (`MONOCLE_ISOLATE_SPANS=false`) is bugged in monocle 0.8.4. Use `output_processor`.

### Pattern

`scripts/_processors.py`:

```python
SCRUB_FILE_PROCESSOR = {
    "type": "workflow",
    "attributes": [[
        {"attribute": "denylist_version", "accessor": lambda a: read_version(a["args"][0])},
        {"attribute": "input_path",       "accessor": lambda a: str(a["args"][0])},
        {"attribute": "redacted_count",   "accessor": lambda a: str(a["result"]),
         "phase": "post_execution"},
    ]],
}
```

`monocle.yaml`:

```yaml
wrappers:
  - package: scrub
    method: scrub_file
    span_name: pii.scrub_file
    span_type: workflow
    output_processor: "_processors:SCRUB_FILE_PROCESSOR"
```

### Accessor contract

Each accessor receives an `arguments` dict:

```python
{
    "instance": <self or None>,
    "args":     <positional args tuple>,
    "kwargs":   <kwargs dict>,
    "result":   <return value — only available when phase == "post_execution">,
    "parent_span": <parent Span>,
    "span":     <current Span>,
}
```

Two important rules:

1. **Accessor return values MUST be `str` or `list`.** Monocle drops other types silently. Stringify ints/floats/bools; the structural grader's `span_attribute` coerces numeric strings back to numbers for comparisons.
2. **Use `"phase": "post_execution"` for accessors that read `result`.** Without it, the accessor runs before the function executes and `result` is `None`.

### How attributes appear on the span

Monocle prefixes every user-declared attribute as `entity.<N>.<your_name>`, where N is a per-span counter. The structural grader auto-strips this prefix — `{"kind": "span_attribute", "key": "denylist_version"}` matches `entity.1.denylist_version` without you having to write the prefix.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `structural.json` says `skipped: true` with "no spans directory" | Launcher didn't invoke monocle_runner.py | Check `MONOCLE_TRACE_OUTPUT_PATH` is exported before the executor spawns |
| Spans dir exists but is empty | Wrapper package can't be imported | Ensure `package:` field in monocle.yaml matches actual import path; check spaces/typos |
| Span present but attribute always None | The wrapped function isn't setting attributes via the OTel API | Add `span.set_attribute(...)` calls inside the function |
| Assertion fails despite obvious-correct behavior | Span name in assertion doesn't match `span_name:` in monocle.yaml | Verify exact string match — case-sensitive, no whitespace |
