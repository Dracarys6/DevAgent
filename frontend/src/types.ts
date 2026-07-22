export type TaskStatus =
  | "PENDING"
  | "RUNNING"
  | "WAITING_PERMISSION"
  | "DONE"
  | "FAILED"
  | "CANCELLED";

export interface AgentTask {
  task_id: string;
  question: string;
  workspace: string;
  provider: string;
  model: string | null;
  base_url: string | null;
  max_steps: number;
  max_tool_calls: number;
  status: TaskStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface TraceStep {
  sequence_id: number;
  event_id: string;
  event_type: string;
  message: string;
  timestamp: string;
  payload: Record<string, unknown>;
  details: Record<string, unknown>;
}

export interface TaskTrace {
  task_id: string;
  summary: {
    event_count: number;
    final_status: string | null;
    final_answer: string | null;
    llm_call_count: number;
    tool_call_count: number;
    permission_request_count: number;
    error_count: number;
  };
  steps: TraceStep[];
}

export interface PermissionRequest {
  request_id: string;
  task_id: string | null;
  tool_name: string;
  tool_arguments: Record<string, unknown>;
  risk_level: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface Evidence {
  evidence_id: string;
  kind: string;
  tool_name: string;
  source: string;
  locator: string;
  excerpt: string;
}

export interface MissingEvidence {
  needed: string;
  reason: string;
  suggested_tool: string | null;
}

export interface GitCommitSummary {
  ref: string;
  sha: string;
  subject: string;
}

export interface DiagnosisReport {
  report_id: string;
  scenario: string;
  target: string;
  status: string;
  summary: string;
  findings: Array<{
    kind: string;
    statement: string;
    confidence: string;
    evidence_ids: string[];
  }>;
  evidence: Evidence[];
  recommendations: Array<{
    action: string;
    rationale: string;
    evidence_ids: string[];
    verification_steps: string[];
  }>;
  missing_evidence: MissingEvidence[];
}

export type ReviewSeverity = "critical" | "high" | "medium" | "low";

export interface ReviewFinding {
  finding_id: string;
  severity: ReviewSeverity;
  category:
    | "correctness"
    | "security"
    | "compatibility"
    | "performance"
    | "maintainability"
    | "test_gap";
  title: string;
  description: string;
  file_path: string;
  line_start: number;
  line_end: number | null;
  side: "base" | "head";
  evidence_ids: string[];
  suggestion: string;
  verification_steps: string[];
}

export interface CodeReviewReport {
  review_id: string;
  base_ref: string;
  head_ref: string;
  status: "reviewed" | "insufficient_evidence";
  summary: string;
  findings: ReviewFinding[];
  evidence: Evidence[];
  missing_evidence: MissingEvidence[];
}

export type GitHubReviewTaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed";

export interface GitHubReviewTask {
  task_id: string;
  delivery_id: string;
  installation_id: number;
  locator: {
    platform: string;
    repository: string;
    number: number;
  };
  status: GitHubReviewTaskStatus;
  report_id: string | null;
  error_message: string | null;
}
