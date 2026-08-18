"use client";

import type { AssessmentEvent } from "@/lib/types";

const KIND_LABEL: Record<AssessmentEvent["kind"], string> = {
  agent_start: "started",
  tool_call: "called",
  tool_result: "returned",
};

export default function LiveEventFeed({
  targetSummary,
  events,
}: {
  targetSummary: string;
  events: AssessmentEvent[];
}) {
  return (
    <div className="flex flex-col gap-3 max-w-2xl w-full">
      <div className="flex items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
        <p className="text-sm text-black/60 dark:text-white/60">
          Running against {targetSummary}
        </p>
      </div>
      <ol className="flex flex-col-reverse gap-1.5 max-h-[28rem] overflow-y-auto font-mono text-xs border border-black/10 dark:border-white/15 rounded-md p-3">
        {events.length === 0 && (
          <li className="text-black/40 dark:text-white/40">Waiting for the first agent to start...</li>
        )}
        {[...events].reverse().map((event) => (
          <li key={event.seq} className="flex gap-2">
            <span className="text-black/40 dark:text-white/40 shrink-0">{event.timestamp}</span>
            <span className="font-semibold shrink-0">{event.role}</span>
            <span className="text-black/50 dark:text-white/50 shrink-0">{KIND_LABEL[event.kind]}</span>
            <span className="truncate">{event.detail}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
