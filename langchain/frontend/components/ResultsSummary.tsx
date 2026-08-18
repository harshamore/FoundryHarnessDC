"use client";

import type { AssessmentResult } from "@/lib/types";

export default function ResultsSummary({
  targetSummary,
  result,
  reportUrl,
  onReset,
}: {
  targetSummary: string;
  result: AssessmentResult;
  reportUrl: string;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-col gap-6 max-w-2xl w-full">
      <div>
        <h2 className="text-lg font-semibold">Assessment complete</h2>
        <p className="text-sm text-black/60 dark:text-white/60">{targetSummary}</p>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <div>
          <dt className="text-black/50 dark:text-white/50">Cycles run</dt>
          <dd className="font-medium">{result.cycles_run}</dd>
        </div>
        <div>
          <dt className="text-black/50 dark:text-white/50">Coverage</dt>
          <dd className="font-medium">{result.coverage_complete ? "Complete" : "Partial"}</dd>
        </div>
        <div>
          <dt className="text-black/50 dark:text-white/50">Reports published</dt>
          <dd className="font-medium">{result.published_reports}</dd>
        </div>
        <div>
          <dt className="text-black/50 dark:text-white/50">Stop reason</dt>
          <dd className="font-medium">{result.stop_reason}</dd>
        </div>
      </dl>

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Rollup</h3>
        <pre className="whitespace-pre-wrap text-xs border border-black/10 dark:border-white/15 rounded-md p-3 max-h-96 overflow-y-auto">
          {result.rollup}
        </pre>
      </div>

      <div className="flex gap-3">
        <a
          href={reportUrl}
          download="rollup.md"
          className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium w-fit"
        >
          Download CISO report
        </a>
        <button
          type="button"
          onClick={onReset}
          className="rounded-md border border-black/15 dark:border-white/20 px-4 py-2 text-sm font-medium w-fit"
        >
          Start another assessment
        </button>
      </div>
    </div>
  );
}
