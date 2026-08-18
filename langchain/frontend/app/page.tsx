"use client";

import { useCallback, useRef, useState } from "react";

import ConfigForm, { type ConfigFormValues } from "@/components/ConfigForm";
import LiveEventFeed from "@/components/LiveEventFeed";
import ResultsSummary from "@/components/ResultsSummary";
import { createAssessment, getStatus, reportUrl, subscribeToEvents } from "@/lib/api";
import type { AssessmentEvent, AssessmentResult } from "@/lib/types";

type Phase = "idle" | "starting" | "running" | "complete" | "failed";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [assessmentId, setAssessmentId] = useState<string | null>(null);
  const [targetSummary, setTargetSummary] = useState<string>("");
  const [events, setEvents] = useState<AssessmentEvent[]>([]);
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [galileoRequested, setGalileoRequested] = useState(false);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  const reset = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    setPhase("idle");
    setAssessmentId(null);
    setTargetSummary("");
    setEvents([]);
    setResult(null);
    setError(null);
    setGalileoRequested(false);
  }, []);

  async function handleSubmit(values: ConfigFormValues) {
    setPhase("starting");
    setError(null);
    setGalileoRequested(Boolean(values.galileoApiKey));
    try {
      const response = await createAssessment({
        openaiApiKey: values.openaiApiKey,
        operatorGoals: values.operatorGoals,
        model: values.model,
        githubUrl: values.targetMode === "github" ? values.githubUrl : undefined,
        files: values.targetMode === "files" ? values.files : undefined,
        galileoApiKey: values.galileoApiKey || undefined,
        galileoProject: values.galileoProject || undefined,
        maxDirectedWorkers: values.maxDirectedWorkers,
        maxConcurrent: values.maxConcurrent,
        maxCycles: values.maxCycles,
      });

      setAssessmentId(response.assessment_id);
      setTargetSummary(response.target_summary);
      setEvents([]);
      setPhase("running");

      unsubscribeRef.current = subscribeToEvents(
        response.assessment_id,
        (event) => setEvents((prev) => [...prev, event]),
        async (status) => {
          const finalStatus = await getStatus(response.assessment_id);
          if (status === "complete" && finalStatus.result) {
            setResult(finalStatus.result);
            setPhase("complete");
          } else {
            setError(finalStatus.error ?? "The assessment failed for an unknown reason.");
            setPhase("failed");
          }
        },
        (message) => {
          setError(message);
          setPhase("failed");
        },
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start the assessment.");
      setPhase("idle");
    }
  }

  return (
    <div className="flex flex-col items-center gap-8 px-6 py-16 sm:py-24">
      <header className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-semibold">Foundry Harness</h1>
        <p className="text-sm text-black/60 dark:text-white/60 max-w-md">
          Agentic security assessment: upload code or a GitHub repo, watch the agents work, download a report.
        </p>
      </header>

      {(phase === "idle" || phase === "starting") && (
        <ConfigForm onSubmit={handleSubmit} submitting={phase === "starting"} submitError={error} />
      )}

      {phase === "running" && <LiveEventFeed targetSummary={targetSummary} events={events} />}

      {phase === "complete" && assessmentId && result && (
        <ResultsSummary
          targetSummary={targetSummary}
          result={result}
          reportUrl={reportUrl(assessmentId)}
          galileoRequested={galileoRequested}
          onReset={reset}
        />
      )}

      {phase === "failed" && (
        <div className="flex flex-col gap-4 max-w-xl w-full">
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error ?? "The assessment failed."}
          </p>
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-black/15 dark:border-white/20 px-4 py-2 text-sm font-medium w-fit"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
