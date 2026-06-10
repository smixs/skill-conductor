# Skill Conductor

Architecture-first skill lifecycle: design → build → test → evaluate → package.

Most skill tools jump straight to "write SKILL.md." Conductor makes you choose the architecture first - because rewriting a wrong pattern costs more than writing it right.

<details>
<summary><strong>v4: Structural eval grading via monocle spans</strong></summary>

See the [Structural eval grading](#structural-eval-grading-monocle) section below. Adds `structural_assertions` to the `evals.json` schema, `monocle_runner.py` + `structural_grader.py` to shared scripts, and `references/monocle_tracing.md` as the author guide.

</details>

<details>
<summary><strong>v3: SOP practices + smoke tests</strong></summary>

- **`references/sop-practices.md`** — 80 years of Standard Operating Procedure wisdom applied to skill authoring. Inline checklists at risk-points, pre-flight checks, programmatic validation, exception handling patterns. Use for procedural skills (client intake, onboarding, reporting, escalation)
- **`scripts/test_smoke.py`** — fast safety net for skill-conductor scripts themselves. Verifies critical scripts execute on known-good skills, fail on known-bad, produce expected output shapes. Run: `uv run scripts/test_smoke.py`
- Updated eval agents (grader, comparator, analyzer) with refined rubrics
- Improved `package_skill.py`, `eval_skill.py`, and schema validation
- Updated `patterns.md` and `schemas.md` with tighter definitions

</details>

<details>
<summary><strong>v2: Anthropic's eval engine meets architecture-first design</strong></summary>

Anthropic [updated their skill-creator](https://claude.com/blog/improving-skill-creator-test-measure-and-refine-agent-skills) with serious eval infrastructure. We took the best of it:

**From Anthropic's skill-creator (new):**
- 3 specialized agents: **grader** (assertion checking + claim extraction), **comparator** (blind A/B testing), **analyzer** (post-hoc root cause analysis)
- Parallel eval execution with isolated contexts (no cross-contamination)
- Automated description optimization with train/test split (60/40)
- Benchmark tracking: pass rate, tokens, time with variance analysis
- HTML eval viewer with qualitative + quantitative tabs

**What Conductor adds on top:**
- **Architecture before code.** 5 patterns (Sequential, Iterative, Context-Aware, Domain Intelligence, Multi-MCP) with selection criteria. Pick wrong = rewrite everything later
- **Degrees of freedom.** Low (deterministic scripts) → Medium (pseudocode) → High (free text). Match freedom to risk tolerance
- **TDD RED before writing.** Verify the agent fails WITHOUT the skill first. If it already handles the task - you don't need a skill. Creator runs baselines in parallel with skill runs. Conductor runs baseline BEFORE you write anything
- **5-axis scoring with thresholds.** Discovery, Clarity, Efficiency, Robustness, Completeness. Each 1-10. Score 45-50 = production. Below 25 = rewrite. Not "vibe check" - numbers
- **Skill categorization.** Capability uplift (teaching something new) vs Encoded preference (sequencing known abilities). Different skills need different testing strategies

</details>

## Synthesized from

1. **[Anthropic Skill Creator](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator)** — eval infrastructure, grader/comparator/analyzer agents, benchmark pipeline
2. **[The Complete Guide to Building Skills for Claude](https://claude.com/blog/complete-guide-to-building-skills-for-claude)** — 32 pages, 5 architecture patterns, success metrics
3. **[Superpowers / writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)** by Jesse Vincent — TDD approach, the "description trap" discovery
4. **[Skills Best Practices](https://github.com/mgechev/skills-best-practices)** by Minko Gechev — three-stage LLM validation, eval methodology

## 5 Modes

| Mode | What it does |
|------|-------------|
| **CREATE** | Architecture selection → TDD baseline → scaffold → write → verify → refactor |
| **EVAL** | 3-stage evaluation: Discovery (triggering) → Logic (execution) → Edge Cases (breaking) |
| **EDIT** | Problem → Signal → Fix table. Targeted improvements without breaking what works |
| **REVIEW** | Pass/fail checklist for third-party skills before you install them |
| **PACKAGE** | Validate structure + package as `.skill` for distribution |

## Architecture patterns

Choose before writing a single line:

| Pattern | Use when |
|---|---|
| Sequential workflow | Clear step-by-step process |
| Iterative refinement | Output improves with cycles |
| Context-aware selection | Same goal, different tools by context |
| Domain intelligence | Specialized knowledge beyond tool access |
| Multi-MCP coordination | Workflow spans multiple services |

## Eval infrastructure

```
                       ┌─────────┐
                       │  SKILL  │
                       └────┬────┘
                            │
        ┌──────────┬────────┼────────┬──────────┐
        │          │        │        │          │
   ┌────▼────┐ ┌──▼───┐ ┌──▼─────┐ ┌─▼────────┐
   │ Grader  │ │ A/B  │ │Analyzer│ │Structural│
   │         │ │Blind │ │        │ │ (monocle │
   │assertions│ │compare│ │ root  │ │ spans,   │
   │+ claims │ │      │ │ cause  │ │ optional)│
   └─────────┘ └──────┘ └────────┘ └──────────┘
        │          │        │           │
        └──────────┴────┬───┴───────────┘
                       │
                 ┌─────▼─────┐
                 │ Benchmark │
                 │ mean±std  │
                 └───────────┘
```

## Structural eval grading (monocle)

Some eval requirements live only inside execution — which version of a maintained policy applied, exact internal call counts, version-pinned operations — and aren't recoverable from output files. NL grading reads transcripts and outputs; it can't satisfy assertions about those facts. [Monocle](https://github.com/monocle2ai/monocle) emits spans from bundled scripts at runtime; the structural grader reads them and verifies deterministically.

**Test prompt** (verifies the integration via `test-skills/pii-scrubber/`):

> "Redact PII from `evals/fixtures/customer_calls.json` and save the result to `/tmp/pii_scrub_eval/clean.json`. The file is going to an external vendor."

The eval declares `denylist_version == "v3"` and `redacted_count >= 8` as structural assertions. Without monocle: 1/5 structural assertions pass — the output file carries no policy version, and counting `[REDACTED:*]` tags in the file gives surviving tags, not the scrubber's authoritative internal counter. With monocle: 5/5 pass — both facts arrive as span attributes emitted by the wrapper.

**Why monocle:** policy version, internal counters, exact call counts, and span ordering are knowable only at runtime inside the wrapped code. Monocle is the channel that gets them out to the grader without modifying the user's script.

**When to use:** the eval needs to assert on internal execution state not visible in the output file.

**When NOT to use:** pure-Markdown skills · scripts where any equivalent code would be equally correct · evals fully expressible via output-file `expectations`. No `monocle.yaml` → structural grader returns `skipped: true` with zero overhead.

**Minimum opt-in (3 files per skill):**
1. `monocle.yaml` — declare wrappers + `output_processor: "_processors:NAME"` reference
2. `scripts/_processors.py` — accessor lambdas returning span attribute values as strings (no OpenTelemetry imports in the skill)
3. `scripts/_run.sh` — conditional launcher; transparent in production, threads monocle in eval mode

See `skills/skill-conductor/references/monocle_tracing.md` for the author guide.

## Installation

```
skills/
└── skill-conductor/
    ├── SKILL.md
    ├── agents/
    │   ├── grader.md
    │   ├── comparator.md
    │   └── analyzer.md
    ├── eval-viewer/
    │   ├── generate_review.py
    │   └── viewer.html
    ├── references/
    │   ├── patterns.md
    │   ├── schemas.md
    │   ├── sop-practices.md
    │   └── monocle_tracing.md
    ├── assets/
    │   └── eval_review.html
    └── scripts/
        ├── init_skill.py
        ├── eval_skill.py
        ├── run_eval.py
        ├── run_loop.py
        ├── improve_description.py
        ├── aggregate_benchmark.py
        ├── generate_report.py
        ├── monocle_runner.py
        ├── structural_grader.py
        ├── package_skill.py
        ├── quick_validate.py
        ├── test_smoke.py
        └── utils.py
```

**OpenClaw:** drop into `~/.openclaw/workspace/skills/`

**Claude Code:** drop into `.claude/skills/`

Auto-activates when the agent detects a skill-building task.

## Key discovery

Never put process steps in the skill description. If your description says "exports assets, generates specs, creates tasks" - the model follows the description and skips the body. Tested experimentally.

```yaml
# ✅ Good
description: Analyze design files for developer handoff. Use when user uploads .fig files.

# ❌ Bad - model follows this and ignores SKILL.md body
description: Exports Figma assets, generates specs, creates Linear tasks, posts to Slack.
```

## License

MIT
