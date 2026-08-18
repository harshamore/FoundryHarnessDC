// Mirrors the backend's own types exactly -- see, respectively,
// src/foundry/orchestration/events.py::AssessmentEvent,
// src/foundry/orchestration/detection.py::WorkerResult,
// src/foundry/orchestration/assessment.py::AssessmentResult, and
// src/foundry/api/store.py::AssessmentStatus. Kept as one small file, not
// generated, since the backend has no OpenAPI-schema-export step yet --
// if these two ever drift, docs/API.md is the source of truth to check
// against, not this file's own history.

export type AssessmentStatus = "pending" | "running" | "complete" | "failed";

export type EventKind = "agent_start" | "tool_call" | "tool_result";

export interface AssessmentEvent {
  seq: number;
  timestamp: string;
  kind: EventKind;
  role: string;
  detail: string;
}

export interface WorkerResult {
  run_name: string;
  response_text: string;
}

export interface AssessmentResult {
  cycles_run: number;
  coverage_complete: boolean;
  stop_reason: string;
  published_reports: number;
  security_map_digest: string;
  detection_results: WorkerResult[];
  rollup: string;
}

export interface CreateAssessmentResponse {
  assessment_id: string;
  status: AssessmentStatus;
  target_summary: string;
}

export interface StatusResponse {
  assessment_id: string;
  status: AssessmentStatus;
  created_at: string;
  target_summary: string;
  event_count: number;
  result?: AssessmentResult;
  error?: string;
}
