# Skill Conductor

> A skill that creates, evaluates, and improves other skills. Meta-level.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Built for [OpenClaw](https://openclaw.ai/) and [Claude Code](https://claude.ai/code), but the methodology works with any LLM that supports skills/instructions.

---

## The Problem

Writing an agent skill looks easy. It's just a markdown file, right?

In practice, most skills fail silently. The model reads the description, ignores the body, and hallucinates the rest. You think it's working until you check the output closely.

Good skills take weeks or months of iteration. They're the transfer of your own expertise into a format an AI can reliably execute. That's not a weekend project.

## Sources

Skill Conductor synthesizes four approaches to skill creation:

| Source | Author | What it contributes |
|--------|--------|-------------------|
| [**Skill Creator**](https://github.com/openclaw/openclaw/tree/main/skills) | OpenClaw | Base framework, scaffold scripts, validation, packaging |
| [**The Complete Guide to Building Skills for Claude**](https://claude.com/blog/complete-guide-to-building-skills-for-claude) | [Anthropic](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf?hsLang=en) | 32-page PDF: 5 architecture patterns, success metrics (90% triggering rate), three skill categories |
| [**Superpowers** — writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) | [Jesse Vincent (obra)](https://github.com/obra/superpowers) | TDD approach to skills, the "description trap" discovery |
| [**Skills Best Practices**](https://github.com/mgechev/skills-best-practices) | [Minko Gechev](https://blog.mgechev.com/2026/02/26/skill-eval/) (Angular team lead, Google) | Three-stage LLM validation, eval methodology |

### What all four share

- Progressive disclosure (three loading levels: metadata → body → references)
- No junk inside (README, CHANGELOG — not in the skill)
- Description = triggers, not process
- Scripts for fragile operations, text for judgment calls
- kebab-case, third person, imperative voice

### What Skill Conductor adds

- Built-in eval system with automatic scoring across 5 axes
- "Process leak" detector — catches workflow in description automatically
- Problem → Signal → Fix table for common failure modes
- Degrees of freedom: bridge (strict rules) vs. field (route freedom)

## 5 Modes

| Mode | What it does |
|------|-------------|
| **CREATE** | Build a new skill from scratch in 7 phases (with TDD) |
| **EVAL** | Score any skill against 10 criteria, max 50 points |
| **EDIT** | Targeted improvements without breaking what works |
| **REVIEW** | Audit third-party skills before installing them |
| **PACKAGE** | Validate and prepare for ClawHub / distribution |

## The TDD Approach

The key insight from [obra/superpowers](https://github.com/obra/superpowers):

> **Verify the agent fails without your skill first.**

1. Take a real use case
2. Run it in a clean session — no skill loaded
3. Watch the agent struggle. Document what went wrong
4. Write the skill to fix exactly those failures
5. Run the same test again. Compare

If the agent already handles the task perfectly, you don't need the skill. Save your tokens.

## Key Discovery

**Never put process steps in the skill description.**

If your `description` says "Exports assets, generates specs, creates tasks" — the model follows the description and skips the body entirely. Tested experimentally.

```yaml
# ✅ Good — purpose + triggers
description: Analyze design files for developer handoff. Use when user uploads .fig files.

# ❌ Bad — process in description (model skips SKILL.md body!)
description: Exports Figma assets, generates specs, creates Linear tasks, posts to Slack.
```

## What's Inside

```
skill-conductor/
├── SKILL.md              # The main skill file — drop this into your agent
├── references/
│   └── patterns.md       # Architecture patterns and degrees of freedom
├── scripts/
│   ├── init_skill.py     # Scaffold a new skill structure
│   ├── eval_skill.py     # Run evaluation against 10 criteria
│   ├── package_skill.py  # Validate and package for distribution
│   └── quick_validate.py # Fast frontmatter + structure check
└── LICENSE
```

## Quick Start

### OpenClaw

Download ZIP (green button ↑) → unpack into skills folder:

```bash
# Option A: Download ZIP and unpack
# Click "Code" → "Download ZIP" → unpack to:
~/.openclaw/workspace/skills/skill-conductor/

# Option B: Clone
git clone https://github.com/smixs/skill-conductor.git \
  ~/.openclaw/workspace/skills/skill-conductor
```

The skill auto-activates when the agent detects a skill-building task.

### Claude Code

Drop into your project's skills directory:

```bash
mkdir -p .claude/skills/skill-conductor
cp SKILL.md .claude/skills/skill-conductor/
cp -r references scripts .claude/skills/skill-conductor/
```

### Other Agents

The `SKILL.md` is standalone. Feed it to any LLM that accepts system instructions. The methodology (TDD, progressive disclosure, concrete templates over prose) is universal.

## Real Results

Tested on production skills:

| Skill | Before | After | What changed |
|-------|--------|-------|-------------|
| OSINT research | 42/50 | 45/50 | Vague Phase 3 instructions → concrete 4-step sequences |
| Autograph (vault engine) | 33/50 | 36/50 | Missing negative triggers, oversized body |

## Related

- [Agent Second Brain](https://github.com/smixs/agent-second-brain) — complete second brain system with persistent memory, where these skills run in production
- [ClawHub](https://clawhub.ai/) — official OpenClaw skill registry (700+ skills)
- [awesome-claude-skills](https://github.com/travisvn/awesome-claude-skills) — curated list of Claude skills

## License

[MIT](LICENSE) — do whatever you want with it.

## Author

[Serge Shima](https://shima.me) — 30+ production skills across 5 AI agents. Teaching businesses to work with AI at [aimasters.me](https://aimasters.me).
