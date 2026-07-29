import type {
  AgentTask,
  CodeReviewReport,
  DiagnosisReport,
  GitCommitSummary,
  GitHubReviewTask,
  KnowledgeSearchResult,
  PermissionRequest,
  TaskTrace,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function getApiUrl(path: string): string {
  return `${API_BASE.replace(/\/$/, "")}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(getApiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  listTasks: () =>
    request<{ tasks: AgentTask[] }>("/api/v1/agent/tasks/list"),
  createTask: (payload: {
    question: string;
    workspace: string;
    provider: "mock" | "real";
    model?: string;
    base_url?: string;
    max_steps: number;
    max_tool_calls: number;
  }) =>
    request<{ task_id: string; status: string }>("/api/v1/agent/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cancelTask: (taskId: string) =>
    request<AgentTask>(`/api/v1/agent/tasks/${taskId}/cancel`, {
      method: "POST",
    }),
  getTrace: (taskId: string) =>
    request<TaskTrace>(`/api/v1/agent/tasks/${taskId}/trace`),
  listPermissions: () =>
    request<{ requests: PermissionRequest[] }>("/api/v1/permissions/pending"),
  resolvePermission: (requestId: string, decision: "ALLOW" | "DENY") =>
    request<PermissionRequest>(
      `/api/v1/permissions/${requestId}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({
          decision,
          decision_reason:
            decision === "ALLOW" ? "通过 DevAgent Console 批准" : "通过 DevAgent Console 拒绝",
        }),
      },
    ),
  diagnoseCI: (commitId: string, workspace: string) =>
    request<DiagnosisReport>("/api/v1/diagnoses/ci", {
      method: "POST",
      body: JSON.stringify({ commit_id: commitId, workspace }),
    }),
  reviewCode: (baseRef: string, headRef: string, workspace: string) =>
    request<CodeReviewReport>("/api/v1/reviews/code", {
      method: "POST",
      body: JSON.stringify({
        base_ref: baseRef,
        head_ref: headRef,
        workspace,
      }),
    }),
  getGitCommitSummary: (ref: string, workspace: string) =>
    request<GitCommitSummary>("/api/v1/git/commit-summary", {
      method: "POST",
      body: JSON.stringify({ ref, workspace }),
    }),
  getGitHubReviewTask: (taskId: string) =>
    request<GitHubReviewTask>(
      `/api/v1/integrations/github/review-tasks/${encodeURIComponent(taskId)}`,
    ),
  searchKnowledge: (query: string, workspace: string, topK: number) =>
    request<KnowledgeSearchResult>("/api/v1/knowledge/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        workspace,
        top_k: topK,
      }),
    }),
};

export function openTaskStream(
  taskId: string,
  onEvent: () => void,
  onError: () => void,
): EventSource {
  const stream = new EventSource(
    getApiUrl(`/api/v1/agent/tasks/${taskId}/stream`),
  );
  const eventTypes = [
    "agent_started",
    "agent_finished",
    "agent_error",
    "llm_call_started",
    "llm_call_finished",
    "tool_call_started",
    "tool_call_finished",
    "tool_call_failed",
    "permission_requested",
    "permission_resolved",
  ];
  eventTypes.forEach((type) => stream.addEventListener(type, onEvent));
  stream.onerror = onError;
  return stream;
}
