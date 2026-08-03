"""Foundry Harness Explorer — a Streamlit demo, not the harness itself.

Three tabs:
  1. Architecture Explorer  -- browse the Constitution and the 8 roles;
     build a Finding by hand and watch the real Pydantic validators
     (FR-052, FR-088, FR-089) accept or reject it. No LLM calls.
  2. Guarded Triage          -- an actual small agentic loop: an LLM given
     tools, in a loop, that may only claim true-positive by citing
     evidence this app then mechanically checks against the pasted code
     (a stand-in for FR-088's "citation must resolve to real code").
  3. Raw LLM (ungated)       -- the same question asked with no tools and
     no evidence requirement, for direct comparison. This is Constitution
     I's "assertion" side: fluent, maybe even right, but unverified.

This app deliberately does not run the real Foundry role classes in
src/foundry_harness/agents/ -- their run() methods still raise
NotImplementedError (see docs/INTEGRATION.md for why). Tab 2 is a
minimal, honest illustration of the *mechanism* a real Triager.investigate()
would use, built directly against an LLM API rather than against the
still-unimplemented harness.

Run locally:
    pip install -e ".[app]"
    streamlit run streamlit_app.py

No API key is read from the environment or from Streamlit secrets --
each visitor supplies their own OpenAI key in the UI, used only for that
session's requests.
"""

from __future__ import annotations

import json

import streamlit as st
from openai import OpenAI
from pydantic import ValidationError

from foundry_harness.agents.cartographer import Cartographer
from foundry_harness.agents.coverage_guide import CoverageGuide
from foundry_harness.agents.detector import Detector
from foundry_harness.agents.indexer import Indexer
from foundry_harness.agents.orchestrator import Orchestrator
from foundry_harness.agents.reporter import Reporter
from foundry_harness.agents.triager import Triager
from foundry_harness.agents.validator import Validator
from foundry_harness.guardrails import CONSTITUTION
from foundry_harness.models import (
    EvidenceCitation,
    EvidenceGate,
    Finding,
    Fingerprint,
    InvestigationReport,
    Verdict,
)

CORE_ROLES = [
    Orchestrator,
    Indexer,
    Cartographer,
    Detector,
    Triager,
    Validator,
    CoverageGuide,
    Reporter,
]

EXAMPLE_SNIPPET = '''def get_user(request):
    user_id = request.args.get("id")
    query = "SELECT * FROM users WHERE id = " + user_id
    return db.execute(query).fetchone()
'''

TRIAGER_SYSTEM_PROMPT = """You are a security Triager investigating one candidate finding.

You may ONLY conclude true-positive by calling cite_evidence exactly three
times, once per leg: reachability, trust_boundary, impact. Each citation's
`excerpt` MUST be an exact, verbatim substring of the code you were given --
not paraphrased, not reconstructed from memory -- because it will be
mechanically checked against the original text and rejected if it does not
match exactly. If you cannot produce a real, verbatim citation for a leg, do
not invent one: call submit_verdict with needs-review or false-positive
instead. When your investigation is complete, call submit_verdict exactly
once."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cite_evidence",
            "description": (
                "Cite one leg of the evidence gate. `excerpt` must be copied "
                "verbatim from the code snippet you were given."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "leg": {
                        "type": "string",
                        "enum": ["reachability", "trust_boundary", "impact"],
                    },
                    "excerpt": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["leg", "excerpt", "explanation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_verdict",
            "description": "Submit the final verdict once the investigation is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["true-positive", "false-positive", "needs-review"],
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["verdict", "reasoning"],
            },
        },
    },
]


def run_guarded_triage(api_key: str, model: str, code: str, question: str) -> tuple[list[dict], dict]:
    """The agentic loop: call the LLM with tools, execute whatever it calls,
    feed the result back, repeat. The verdict it *claims* is never trusted
    directly -- citations are re-checked against `code` in Python, after
    the loop ends, before any true-positive is accepted. That check is the
    harness's job, not the model's, exactly as Constitution I requires.
    """
    client = OpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": TRIAGER_SYSTEM_PROMPT},
        {"role": "user", "content": f"CODE:\n```\n{code}\n```\n\nQUESTION: {question}"},
    ]
    citations: dict[str, dict] = {}
    verdict_call: dict | None = None
    transcript: list[dict] = []

    for _ in range(6):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS, tool_choice="auto",
        )
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if msg.content:
            transcript.append({"label": "model", "content": msg.content})

        if not msg.tool_calls:
            break

        stop = False
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)

            if tc.function.name == "cite_evidence":
                leg = args["leg"]
                excerpt = args.get("excerpt", "")
                resolved = bool(excerpt.strip()) and excerpt in code
                citations[leg] = {
                    "excerpt": excerpt,
                    "explanation": args.get("explanation", ""),
                    "resolved": resolved,
                }
                transcript.append(
                    {"label": f"tool call: cite_evidence({leg})", "content": json.dumps(citations[leg], indent=2)}
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"resolved": resolved})}
                )

            elif tc.function.name == "submit_verdict":
                verdict_call = args
                transcript.append({"label": "tool call: submit_verdict", "content": json.dumps(args, indent=2)})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "recorded"})
                stop = True

        if stop:
            break

    legs_ok = all(citations.get(leg, {}).get("resolved") for leg in ("reachability", "trust_boundary", "impact"))
    claimed_verdict = verdict_call["verdict"] if verdict_call else "needs-review"

    if claimed_verdict == "true-positive" and not legs_ok:
        final_verdict = "needs-review"
        gate_passed = False
        reason = "at least one evidence citation did not resolve as a verbatim match in the pasted code (FR-088)"
    else:
        final_verdict = claimed_verdict
        gate_passed = True
        reason = ""

    return transcript, {
        "claimed_verdict": claimed_verdict,
        "final_verdict": final_verdict,
        "citations": citations,
        "gate_passed": gate_passed,
        "demotion_reason": reason,
    }


st.set_page_config(page_title="Foundry Harness Explorer", layout="wide")
st.title("Foundry Harness Explorer")
st.caption(
    "A demo, not the harness. Scaffolded from Cisco's open-source "
    "[Foundry Security Spec](https://github.com/CiscoDevNet/foundry-security-spec). "
    "See README.md / docs/ARCHITECTURE.md for what's real vs. illustrative here."
)

tab1, tab2, tab3 = st.tabs(
    ["1. Architecture Explorer", "2. Guarded Triage (agentic)", "3. Raw LLM (ungated)"]
)

with tab1:
    st.header("The Constitution — 11 inviolable principles")
    for p in CONSTITUTION.principles:
        with st.expander(f"{p.numeral}. {p.title}"):
            st.markdown(f"**Statement:** {p.statement}")
            st.markdown(f"**Why inviolable:** {p.rationale}")

    st.header("The eight core roles")
    for role in CORE_ROLES:
        with st.expander(f"{role.role_name}  ·  {role.spec_section}"):
            st.write(role.purpose)

    st.header("Build a Finding and watch the guardrails fire")
    st.caption(
        "This constructs a real `foundry_harness.models.finding.Finding`. "
        "Set verdict to true-positive but leave a citation's 'resolved' "
        "box unchecked, or skip filling one in — it will be rejected the "
        "same way a real Triager's output would be (FR-052, FR-088)."
    )

    with st.form("finding_form"):
        title = st.text_input("Title", "SQL injection in login handler")
        description = st.text_area(
            "Description", "User-controlled input reaches a raw SQL query without parameterization."
        )
        path = st.text_input("File path", "src/auth.py")
        symbol = st.text_input("Symbol", "login")
        vuln_class = st.text_input("Vulnerability class", "CWE-89")
        verdict_choice = st.selectbox("Verdict", ["(none)"] + [v.value for v in Verdict])

        st.markdown("**Evidence gate** — only enforced if verdict = true-positive")
        leg_specs = [
            ("reachability", "Attacker-controlled entry point the sink is reachable from"),
            ("trust_boundary", "Where untrusted data crosses into trusted processing"),
            ("impact", "The concrete security consequence at the sink"),
        ]
        leg_inputs = {}
        cols = st.columns(3)
        for col, (key, label) in zip(cols, leg_specs):
            with col:
                st.markdown(f"*{label}*")
                f = st.text_input("file_path", path, key=f"{key}_file")
                s = st.text_input("symbol", symbol, key=f"{key}_symbol")
                resolved = st.checkbox("resolved", value=True, key=f"{key}_resolved")
                leg_inputs[key] = (f, s, resolved)

        submitted = st.form_submit_button("Validate")

    if submitted:
        try:
            fingerprint = Fingerprint(normalized_path=path, symbol=symbol, vulnerability_class=vuln_class)
            verdict = None if verdict_choice == "(none)" else Verdict(verdict_choice)
            investigation = None
            if verdict == Verdict.TRUE_POSITIVE:
                gate = EvidenceGate(
                    reachability=EvidenceCitation(
                        file_path=leg_inputs["reachability"][0],
                        symbol=leg_inputs["reachability"][1],
                        resolved=leg_inputs["reachability"][2],
                    ),
                    trust_boundary=EvidenceCitation(
                        file_path=leg_inputs["trust_boundary"][0],
                        symbol=leg_inputs["trust_boundary"][1],
                        resolved=leg_inputs["trust_boundary"][2],
                    ),
                    impact=EvidenceCitation(
                        file_path=leg_inputs["impact"][0],
                        symbol=leg_inputs["impact"][1],
                        resolved=leg_inputs["impact"][2],
                    ),
                )
                investigation = InvestigationReport(
                    reasoning="Constructed via the Streamlit form.", evidence_gate=gate
                )
            finding = Finding(
                id="demo-1",
                fingerprint=fingerprint,
                title=title,
                description=description,
                scope_location=EvidenceCitation(file_path=path, symbol=symbol),
                detection_technique="manual-demo",
                verdict=verdict,
                investigation=investigation,
            )
            st.success("Accepted by the Finding model.")
            st.json(json.loads(finding.model_dump_json()))
        except ValidationError as e:
            st.error("Rejected by the guardrails:")
            st.code(str(e))

with tab2:
    st.header("Guarded Triage — a real agentic loop")
    st.markdown(
        "This is the smallest honest version of what `Triager.investigate()` "
        "would do: an LLM in a tool-calling loop that can only claim "
        "`true-positive` by citing evidence via a tool call. After the loop "
        "ends, **this app — not the model — mechanically checks** whether "
        "each cited excerpt is an actual verbatim substring of the pasted "
        "code, standing in for FR-088's 'citations must resolve to real "
        "code' check. If any citation fails, the verdict is demoted to "
        "`needs-review` regardless of what the model claimed. That split — "
        "model proposes, deterministic code verifies — is Constitution I "
        "('Evidence Over Assertion') in practice, and it's what makes this "
        "an *agent with a guardrail* rather than just a chatbot."
    )

    api_key = st.text_input("OpenAI API key", type="password", key="key2", help="Used only for this session; never stored.")
    model = st.text_input("Model", "gpt-4o-mini", key="model2")
    code = st.text_area("Code snippet", value=EXAMPLE_SNIPPET, height=180, key="code2")
    question = st.text_input("What should the Triager check for?", "Is there a SQL injection vulnerability?", key="q2")

    if st.button("Run guarded triage", disabled=not api_key):
        with st.spinner("Running the tool-calling loop..."):
            try:
                transcript, result = run_guarded_triage(api_key, model, code, question)
            except Exception as e:  # noqa: BLE001 -- surfaced to the user, not swallowed
                st.error(f"Request failed: {e}")
            else:
                st.subheader("Tool-call transcript")
                for turn in transcript:
                    with st.expander(turn["label"]):
                        st.code(turn["content"])

                st.subheader("Result")
                if result["gate_passed"] and result["final_verdict"] == "true-positive":
                    st.success(f"Verdict: **{result['final_verdict']}** — all three citations resolved.")
                elif result["final_verdict"] != result["claimed_verdict"]:
                    st.warning(
                        f"Model claimed **{result['claimed_verdict']}**, demoted to "
                        f"**{result['final_verdict']}** — {result['demotion_reason']}"
                    )
                else:
                    st.info(f"Verdict: **{result['final_verdict']}**")
                st.json(result)

with tab3:
    st.header("Raw LLM response — no tools, no evidence gate")
    st.markdown(
        "Same question, no harness. This is Constitution I's *assertion* "
        "side: fluent, maybe even correct, but **nothing here is checked "
        "against the actual code**. Compare its confidence against tab 2's "
        "citation check."
    )

    api_key3 = st.text_input("OpenAI API key", type="password", key="key3")
    model3 = st.text_input("Model", "gpt-4o-mini", key="model3")
    code3 = st.text_area("Code snippet", value=EXAMPLE_SNIPPET, height=180, key="code3")
    question3 = st.text_input(
        "Question", "Is there a SQL injection vulnerability? Answer and explain.", key="q3"
    )

    if st.button("Ask the raw model", disabled=not api_key3):
        with st.spinner("Asking..."):
            try:
                client = OpenAI(api_key=api_key3)
                response = client.chat.completions.create(
                    model=model3,
                    messages=[{"role": "user", "content": f"CODE:\n```\n{code3}\n```\n\n{question3}"}],
                )
            except Exception as e:  # noqa: BLE001
                st.error(f"Request failed: {e}")
            else:
                st.markdown(response.choices[0].message.content)
                st.caption("Nothing above was verified against the code.")
