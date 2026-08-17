# CodeGuard integration

## What CodeGuard is, here

[`cosai-oasis/project-codeguard`](https://github.com/cosai-oasis/project-codeguard)
is the rule corpus the Foundry Security Spec names as its own worked example
for FR-037 (rule-based detection) and FR-041 (a versioned rule corpus
maintained independently of agent code):

> "The seed authors use CodeGuard, an open-source rule format that predates
> this seed and was designed independently for exactly this dual deployment
> (evaluation-time detection and authoring-time prevention from one corpus)."
> — spec.md §5.4

It's also already installed on this machine as a Claude Code plugin
(`~/.claude/plugins/marketplaces/project-codeguard`) — that installation is
**not** what this harness depends on. The plugin is local to this Mac and
invisible to Colab; the harness fetches its own copy independently (see
below), so the Detector's rule corpus doesn't depend on the Claude Code
plugin system at all.

## How the corpus gets in

`scripts/fetch_codeguard_rules.py` clones the upstream repo at a **pinned
commit** (`7e19e207bd67abbd3d04ae664441595410df1157`, currently) and copies
`sources/rules/{core,owasp}` into `data/codeguard/rules/` (git-ignored —
fetched, not vendored-and-committed, per `data/codeguard/ATTRIBUTION.md`
which *is* committed).

Pinning matters: the Detector's rule-sweep should depend on a known,
reviewed corpus, not silently pick up upstream changes on every run. To
intentionally update, bump `PINNED_SHA` in the script and rerun it.

Current counts at the pinned commit: **23 `core/` rules**, **85 `owasp/`
rules**, 108 total.

## Rule format

Each rule is a markdown file with YAML frontmatter:

```yaml
---
description: No Hardcoded Credentials
alwaysApply: true
tags: [secrets]
---

rule_id: codeguard-1-hardcoded-credentials
# No Hardcoded Credentials
NEVER store secrets, passwords, API keys, tokens...
```

The official `codeguard-mcp` server (part of the upstream repo, not used by
this harness directly) turns each rule into a no-argument MCP tool that
returns the rule's guidance text — designed for *authoring-time* use, where
a coding assistant calls it while writing code.

## How the Detector uses it

Same underlying pattern, applied at *evaluation-time* instead of
authoring-time: the rule-sweep subagent (`build_detector_rule_sweep_subagent`
in `src/foundry/agents/detector.py`) has tools to list and fetch rules
(`list_rules`/`get_rule`) alongside the Indexer's query tools
(`get_function_body`/`get_callers`/`get_callees`), and reasons about each
function's body against whichever rules plausibly apply. This satisfies
spec.md FR-037 without hand-writing detection rules from scratch.

Rather than running the upstream `fastmcp` HTTP server (unnecessary
complexity for a Colab-executed notebook), `src/foundry/codeguard/loader.py`
parses the vendored markdown files directly (mirroring the upstream
`RuleProcessor`'s frontmatter-splitting logic) and
`src/foundry/codeguard/tools.py` exposes `list_rules`/`get_rule` as plain
LangChain tools. This can be swapped for the real MCP server later if the
harness runs as a persistent multi-agent fleet outside Colab.

**Not implemented, by design, for this toy target**: FR-049 (front-loading
each function's body/callers/callees directly into the detection call's
initial prompt, rather than relying on the model to fetch them via tools)
— the toy target has 5 functions, so the tool-call overhead this optimizes
away is negligible here; worth revisiting if a larger target makes rule-sweep
cost noticeably higher than it needs to be.

## Rule breadth: `core/` first

The Detector's rule-sweep defaults to `core/` (23 rules — matches the
official MCP server's own default) with `owasp/` (the larger ~85-rule
superset) available via `load_rules(rules_dir, categories=("core", "owasp"))`
once the pipeline is proven. This is a judgment call, not a spec
requirement — `data/toy_target/vulnerable_app.py`'s three seeded
vulnerabilities (SQL injection, hardcoded credential, path traversal) are
all `core` rules, so `core/` alone is sufficient to exercise the pipeline
end to end.

## The rule-gap loop (FR-042)

When the Detector's *exploratory* subagent is confident a finding is real
and can name why no CodeGuard rule would have produced it, it calls
`record_rule_gap` directly (`src/foundry/detector/tools.py`), writing to
the `rule_gaps` table that's existed in the schema since the Substrate
section. **A deliberate deviation from the spec's literal text**: FR-042
says "the Triager MUST record a rule-gap entry" — since no Triager exists
yet, this build lets the Detector's exploratory subagent record it
directly instead of waiting. Revisit once the Triager section lands:
either the Triager takes over this responsibility (matching the spec
exactly, gated on an actual `true-positive` verdict rather than the
Detector's own confidence) or the two responsibilities are deliberately
split, but that decision shouldn't be made silently — flagging it here.
This is the seam where a finding this harness discovers on its own could
eventually generalize into a new rule and contribute back upstream — the
spec's "detection investment compounds into prevention" argument
(spec.md §5.4).

## License

Rule content is reproduced under CC BY 4.0 from
`cosai-oasis/project-codeguard`. See `data/codeguard/ATTRIBUTION.md`
(regenerated by the fetch script) for the full notice. This project's own
loading and rule-sweep code is under this repository's own license, not
CC BY 4.0.
