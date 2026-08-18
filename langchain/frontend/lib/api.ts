import type {
  AssessmentEvent,
  CreateAssessmentResponse,
  StatusResponse,
} from "./types";

// Overridable at build/run time (see frontend/.env.local.example) for
// anyone serving the backend from somewhere other than the default local
// dev port -- matches src/foundry/api/app.py's own FOUNDRY_CORS_ORIGINS
// escape hatch on the other side of this same boundary.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface CreateAssessmentInput {
  openaiApiKey: string;
  operatorGoals: string;
  model?: string;
  githubUrl?: string;
  files?: File[];
  galileoApiKey?: string;
  galileoProject?: string;
  maxDirectedWorkers?: number;
  maxConcurrent?: number;
  maxCycles?: number;
}

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // body wasn't JSON -- fall through to the generic message below
  }
  return `Request failed: ${res.status} ${res.statusText}`;
}

export async function createAssessment(
  input: CreateAssessmentInput,
): Promise<CreateAssessmentResponse> {
  const form = new FormData();
  // openai_api_key/galileo_api_key travel in this multipart body only --
  // never appended to a URL, never set on a header the browser would log,
  // matching the backend's own "never persisted, never logged" contract.
  form.set("openai_api_key", input.openaiApiKey);
  form.set("operator_goals", input.operatorGoals);
  if (input.model) form.set("model", input.model);
  if (input.githubUrl) form.set("github_url", input.githubUrl);
  if (input.galileoApiKey) form.set("galileo_api_key", input.galileoApiKey);
  if (input.galileoProject) form.set("galileo_project", input.galileoProject);
  if (input.maxDirectedWorkers != null) {
    form.set("max_directed_workers", String(input.maxDirectedWorkers));
  }
  if (input.maxConcurrent != null) {
    form.set("max_concurrent", String(input.maxConcurrent));
  }
  if (input.maxCycles != null) {
    form.set("max_cycles", String(input.maxCycles));
  }
  for (const file of input.files ?? []) {
    form.append("files", file);
  }

  const res = await fetch(`${API_BASE_URL}/assessments`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

export async function getStatus(assessmentId: string): Promise<StatusResponse> {
  const res = await fetch(`${API_BASE_URL}/assessments/${assessmentId}/status`);
  if (!res.ok) throw new Error(await readErrorDetail(res));
  return res.json();
}

export function reportUrl(assessmentId: string): string {
  return `${API_BASE_URL}/assessments/${assessmentId}/report`;
}

/** Subscribes to the backend's SSE event stream. Returns an unsubscribe
 * function; call it on unmount to avoid leaking the EventSource. */
export function subscribeToEvents(
  assessmentId: string,
  onEvent: (event: AssessmentEvent) => void,
  onDone: (status: string) => void,
  onError?: (message: string) => void,
): () => void {
  const source = new EventSource(`${API_BASE_URL}/assessments/${assessmentId}/events`);

  source.addEventListener("message", (e) => {
    onEvent(JSON.parse(e.data) as AssessmentEvent);
  });

  // The backend emits this as a *named* SSE event ("event: done\n...", see
  // src/foundry/api/app.py::stream_events) specifically so it's
  // distinguishable from ordinary progress events on the wire.
  source.addEventListener("done", (e) => {
    const payload = JSON.parse((e as MessageEvent).data) as { status: string };
    onDone(payload.status);
    source.close();
  });

  source.onerror = () => {
    // A closed stream after "done" also fires onerror in some browsers;
    // readyState CLOSED there is expected, not a real failure. Only a
    // connection that dies before any "done" event is a genuine problem.
    if (source.readyState === EventSource.CLOSED) return;
    onError?.("Lost connection to the assessment event stream.");
  };

  return () => source.close();
}
