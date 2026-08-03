# foundry-harness

An architecture scaffold for an agentic security evaluation harness,
built from Cisco's open-source [Foundry Security
Spec](https://github.com/CiscoDevNet/foundry-security-spec)
(`CiscoDevNet/foundry-security-spec`, CC BY 4.0).

**Status:** scaffold only. Role interfaces, guardrail definitions, and
finding-lifecycle data models are in place; no detection, triage, or
validation logic is implemented. Every agent's `run()` raises
`NotImplementedError` by design — see `docs/INTEGRATION.md` for why that
should stay true until this project's `spec.md` has been through
`/speckit.clarify`.

## What's here

| Path | Contents |
|---|---|
| `.specify/memory/constitution.md` | Upstream constitution, unmodified. 11 inviolable principles. |
| `specs/001-foundry/spec.md` | Upstream seed spec, unmodified. 8 core roles, 5 extension roles, ~130 FRs. |
| `src/foundry_harness/agents/` | The 8 core role interfaces + `agents/extensions/` for the 5 optional roles |
| `src/foundry_harness/guardrails/` | `Constitution` — the 11 principles as an importable, versioned object |
| `src/foundry_harness/models/` | `Finding`, `Verdict`, `EvidenceGate`, `Fingerprint` — the Finding Lifecycle (spec.md §7) as Pydantic models |
| `src/foundry_harness/orchestration/` | `Protocol` contracts for the substrate (work queue, finding store, sandbox, budget governor, dashboard) |
| `docs/ARCHITECTURE.md` | Full architecture writeup: shape, roles, finding lifecycle, repo layout |
| `docs/INTEGRATION.md` | spec-kit workflow status, human-in-the-loop enforcement points |
| `streamlit_app.py` | A **demo app**, not the harness — see below |

## Quickstart

```sh
pip install -e ".[dev]"
python -c "from foundry_harness.guardrails import CONSTITUTION; print([p.title for p in CONSTITUTION.principles])"
python -c "from foundry_harness.models import Finding, Verdict; print(Finding.model_json_schema()['title'])"
```

Both should run without needing any of the open integration questions
(LLM provider, datastore, issue tracker) answered — the models and
guardrails are pure data, independent of any stack decision.

## Demo app (`streamlit_app.py`)

A small Streamlit app to make the guardrails tangible without waiting on
the real harness:

1. **Architecture Explorer** — browse the 11 principles and 8 roles;
   build a `Finding` through a form and watch the real Pydantic
   validators (FR-052, FR-088, FR-089) accept or reject it. No LLM calls.
2. **Guarded Triage** — a small real agentic loop: an LLM (OpenAI, key
   entered in the UI) given tools, that can only claim `true-positive` by
   citing evidence the app then mechanically checks against the pasted
   code — the smallest honest illustration of what `Triager.investigate()`
   would enforce.
3. **Raw LLM (ungated)** — the same question, no tools, no evidence
   check, for direct contrast with (2).

This app does **not** run the real role classes in `agents/` — those
still raise `NotImplementedError`. It's a standalone illustration of the
mechanism, built directly against an LLM API.

Run locally (no Docker needed — Streamlit is just a Python web server):

```sh
pip install -e ".[app]"
streamlit run streamlit_app.py
```

No API key is read from the environment; each visitor enters their own
OpenAI key in the UI, used only for that session.

### Deploying to Streamlit Cloud

Streamlit Cloud runs one stateless web process — fine for this demo app,
not suitable for the real multi-agent fleet (no persistent work queue,
no sandboxed egress per Constitution IX). To deploy:

1. Push this repo to GitHub (`requirements.txt` and `streamlit_app.py`
   are already at the repo root, which is what Streamlit Cloud expects).
2. At [share.streamlit.io](https://share.streamlit.io), create a new app
   pointing at the repo, branch, and `streamlit_app.py` as the main file.
3. No secrets to configure — the app takes the OpenAI key as user input,
   not a stored secret.

## Next step

This project has **not yet** installed spec-kit or run
`/speckit.clarify`. That's the actual next step, not writing more Python:
`spec.md` carries ~30 `[NEEDS CLARIFICATION: ...]` markers (system name,
LLM provider, datastore, issue tracker, severity scheme, testbed
availability, extension-role scope, ...) that materially change what each
role in `agents/` should actually do. See `docs/INTEGRATION.md` for the
full checklist and where this repo currently stands against it.

## Attribution

`spec.md` and `constitution.md` are reproduced unmodified from
[CiscoDevNet/foundry-security-spec](https://github.com/CiscoDevNet/foundry-security-spec),
© 2026 Cisco Systems, Inc., licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See that
repository's `MAINTAINERS.md` for the original spec and constitution
authors. Everything under `src/` and `docs/` is this project's own
scaffold, not upstream content.
