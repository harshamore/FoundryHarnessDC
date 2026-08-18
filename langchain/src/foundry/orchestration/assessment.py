"""The real "index -> map -> detect -> triage -> check coverage -> detect
the gaps -> re-triage -> report" sequence (Phase 2), run for real: Indexer
and Cartographer's deterministic fallback need no model at all (FR-020,
FR-036a); concurrent Detector passes and directed-detection workers use
`foundry.orchestration.detection`; the loop's stop/continue decision uses
`foundry.orchestration.loop_control`; Cartographer/Triager/Reporter are
each one real, sequential subagent call -- concurrency isn't asked for
single, non-parallelizable steps, only for the Detector halves and the
directed-worker pool.

This is also where the pipeline-reordering question paused earlier in this
build resolves: directed detection runs right after Coverage-Guide
identifies gaps, in a real loop, not stuck after Reporter in a
single-pass demo -- and Reporter always runs last, once the loop actually
stops.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundry.agents.reporter import build_reporter_subagent
from foundry.agents.triager import build_triager_subagent
from foundry.cartographer.fallback import (
    fallback_architecture_overview,
    fallback_attack_surface,
    fallback_data_flows,
    fallback_threat_model,
    fallback_trust_boundaries,
)
from foundry.cartographer.store import SecurityMapStore
from foundry.codeguard.loader import load_rules
from foundry.coverage.store import CoverageStore
from foundry.indexer.parser import index_file
from foundry.indexer.store import IndexStore
from foundry.orchestration.agent_runner import run_single_subagent
from foundry.orchestration.detection import (
    WorkerResult,
    run_broad_detection_concurrently,
    run_directed_workers_concurrently,
)
from foundry.orchestration.events import AssessmentEvent
from foundry.orchestration.loop_control import evaluate_cycle, has_directed_work_available
from foundry.reporter.store import ReporterStore
from foundry.substrate.budget import BudgetCaps, BudgetGovernor
from foundry.substrate.db import connect
from foundry.substrate.finding_store import FindingStore
from foundry.substrate.work_queue import WorkQueue
from foundry.target.repo import TargetRepo

DEFAULT_MODEL = "openai:gpt-5.6-luna"


@dataclass
class AssessmentConfig:
    target: TargetRepo
    db_path: Path
    reports_dir: Path
    operator_goals: list[str]
    rules_dir: Path
    model: str | Any = DEFAULT_MODEL
    max_directed_workers: int = 4
    max_concurrent: int = 4
    max_cycles: int = 5
    budget_caps: BudgetCaps = field(default_factory=BudgetCaps)
    galileo_callback: Any = None
    run_cartographer_agent: bool = True
    run_triager_agent: bool = True
    run_reporter_agent: bool = True
    on_event: Callable[[AssessmentEvent], None] | None = None


@dataclass(frozen=True)
class AssessmentResult:
    cycles_run: int
    coverage_complete: bool
    stop_reason: str
    published_reports: int
    security_map_digest: str
    detection_results: list[WorkerResult]
    rollup: str


async def run_assessment(config: AssessmentConfig) -> AssessmentResult:
    conn = connect(config.db_path)
    try:
        index_store = IndexStore(conn)
        finding_store = FindingStore(conn)
        security_map = SecurityMapStore(conn)
        coverage_store = CoverageStore(conn)
        work_queue = WorkQueue(conn)
        reporter_store = ReporterStore(conn, config.reports_dir)
        budget_governor = BudgetGovernor(conn, config.budget_caps)

        # 1. Index -- deterministic, no model (FR-020). Every supported
        # file in the target, regardless of language.
        for target_file in config.target.files:
            if target_file.language is None:
                continue
            result = index_file(target_file.path, config.target.root)
            index_store.write_index(target_file.normalized_path, result.functions, result.call_edges)

        # 2. Map -- the deterministic fallback always lands first (FR-036a:
        # "an empty security map is a Cartographer failure, not graceful
        # degradation"), using the first indexed file as the representative
        # target path (Cartographer's fallback generators are still
        # single-target-path-shaped; Phase 2 doesn't change that).
        representative_path = config.target.files[0].normalized_path if config.target.files else ""
        security_map.write_section(
            "architecture_overview", fallback_architecture_overview(representative_path, index_store), source="fallback"
        )
        security_map.write_section(
            "attack_surface", fallback_attack_surface(representative_path, index_store), source="fallback"
        )
        security_map.write_section("trust_boundaries", fallback_trust_boundaries(), source="fallback")
        security_map.write_section("data_flows", fallback_data_flows(), source="fallback")
        security_map.write_section("threat_model", fallback_threat_model(), source="fallback")

        if config.run_cartographer_agent:
            from foundry.agents.cartographer import build_cartographer_subagent

            cartographer_subagent = build_cartographer_subagent(security_map, index_store)
            await run_single_subagent(
                model=config.model,
                subagent=cartographer_subagent,
                main_system_prompt=(
                    "You are the harness main agent. Delegate to the 'cartographer' subagent "
                    "to produce the security map for the target."
                ),
                user_message=(
                    "Using the cartographer, read the target's functions and produce the full "
                    "security map: architecture overview, attack-surface enumeration, "
                    "trust-boundary map, data-flow description, and a threat model."
                ),
                galileo_callback=config.galileo_callback,
                run_name="cartographer",
                on_event=config.on_event,
            )
        security_map_digest = security_map.digest()

        # 3. Coverage-Guide's checklist, from the operator's real stated
        # goals (FR-068) against every indexed function.
        areas = index_store.list_functions()
        if areas and config.operator_goals:
            coverage_store.build_checklist(
                areas=areas,
                goals=config.operator_goals,
                bar_template="A rule-sweep, exploratory, or directed Detector pass has checked "
                "{area} for {goal}, and the result (finding or clean) is recorded.",
            )

        # 4. Detect, broad -- rule-sweep and exploratory, genuinely
        # concurrent (see foundry.orchestration.detection).
        rules = load_rules(config.rules_dir, categories=("core",), languages=tuple(config.target.languages) or None)
        detection_results = list(
            await run_broad_detection_concurrently(
                db_path=config.db_path,
                rules=rules,
                security_map_digest=security_map_digest,
                model=config.model,
                galileo_callback=config.galileo_callback,
                on_event=config.on_event,
            )
        )

        # 5. Triage whatever the broad sweep queued.
        if config.run_triager_agent:
            await _run_triager_pass(config, security_map_digest)

        # 6. The real loop: check coverage, direct the Detector at the
        # gaps, re-triage, repeat -- until the budget says stop, coverage
        # is complete, or nothing more can be productively directed.
        cycle = 0
        outcome = evaluate_cycle(coverage_store, budget_governor, cycle)
        while cycle < config.max_cycles:
            if outcome.coverage_complete or outcome.should_stop:
                break
            if cycle > 0 and outcome.closed_this_cycle == 0:
                # A full cycle closed nothing -- continuing would spin
                # forever against gaps no available technique can close.
                break
            if not has_directed_work_available(coverage_store):
                break
            queued = coverage_store.queue_directed_tasks(work_queue)
            if queued == 0 and cycle == 0:
                # Nothing was ever queued and coverage isn't complete --
                # genuinely nothing left to direct a worker at.
                break

            cycle += 1
            directed_results = await run_directed_workers_concurrently(
                db_path=config.db_path,
                n_workers=config.max_directed_workers,
                max_concurrent=config.max_concurrent,
                model=config.model,
                galileo_callback=config.galileo_callback,
                on_event=config.on_event,
            )
            detection_results.extend(directed_results)

            if config.run_triager_agent:
                await _run_triager_pass(config, security_map_digest)

            outcome = evaluate_cycle(coverage_store, budget_governor, cycle)

        # 7. Report -- always last, only once the loop has actually
        # stopped. Only true-positive findings are ever eligible
        # (Constitution II, FR-079) -- enforced by ReporterStore itself,
        # not by anything checked here.
        published_reports = 0
        if config.run_reporter_agent:
            reporter_subagent = build_reporter_subagent(finding_store, reporter_store, index_store)
            await run_single_subagent(
                model=config.model,
                subagent=reporter_subagent,
                main_system_prompt=(
                    "You are the harness main agent. Delegate to the 'reporter' subagent to "
                    "publish a report for every true-positive finding."
                ),
                user_message=(
                    "Using the reporter, publish a self-contained report for every "
                    "true-positive finding, with an appropriate severity and weakness "
                    "classification for each."
                ),
                galileo_callback=config.galileo_callback,
                run_name="reporter",
                on_event=config.on_event,
            )
            published_reports = len(reporter_store.list_published())

        # FR-081's rollup: entirely deterministic aggregation, no LLM
        # needed, so it always runs -- even if run_reporter_agent is False,
        # an honest "0 confirmed findings published" rollup is still a
        # real, correct summary of that state, not an error.
        rollup = reporter_store.build_rollup(coverage_store)

        return AssessmentResult(
            cycles_run=cycle,
            coverage_complete=outcome.coverage_complete,
            stop_reason=outcome.stop_reason,
            published_reports=published_reports,
            security_map_digest=security_map_digest,
            detection_results=detection_results,
            rollup=rollup,
        )
    finally:
        conn.close()


async def _run_triager_pass(config: AssessmentConfig, security_map_digest: str) -> None:
    conn = connect(config.db_path)
    try:
        triager_subagent = build_triager_subagent(FindingStore(conn), IndexStore(conn), security_map_digest)
        await run_single_subagent(
            model=config.model,
            subagent=triager_subagent,
            main_system_prompt=(
                "You are the harness main agent. Delegate to the 'triager' subagent to "
                "investigate and assign a verdict to every untriaged candidate."
            ),
            user_message=(
                "Using the triager, investigate every untriaged candidate and assign each "
                "one a verdict with citations and a real investigation report."
            ),
            galileo_callback=config.galileo_callback,
            run_name="triager",
            on_event=config.on_event,
        )
    finally:
        conn.close()
