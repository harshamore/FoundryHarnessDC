"use client";

import type { AssessmentResult } from "@/lib/types";

export default function ResultsSummary({
  targetSummary,
  result,
  reportUrl,
  galileoRequested,
  onReset,
}: {
  targetSummary: string;
  result: AssessmentResult;
  reportUrl: string;
  galileoRequested: boolean;
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

      {result.galileo_console_url && (
        <p className="text-sm">
          <a
            href={result.galileo_console_url}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2"
          >
            View Galileo trace &rarr;
          </a>
        </p>
      )}
      {!result.galileo_console_url && galileoRequested && (
        <p role="alert" className="text-sm text-amber-600 dark:text-amber-400">
          Galileo tracing was requested but did not activate for this run. Check the backend
          terminal for a message starting with &quot;Galileo tracing unavailable&quot; or
          &quot;GALILEO_API_KEY is set but the galileo package isn&apos;t installed&quot; —
          the latter means the backend needs <code>pip install -e &quot;.[observability]&quot;</code>.
        </p>
      )}

      <div className="flex gap-3">
        <a
          href={reportUrl}
          download="ciso_report.md"
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
