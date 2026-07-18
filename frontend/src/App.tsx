import {
  Activity,
  AlertTriangle,
  Ban,
  Bot,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  FileSearch,
  GitCommitHorizontal,
  LoaderCircle,
  Moon,
  Play,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, openTaskStream } from "./api";
import type {
  AgentTask,
  DiagnosisReport,
  PermissionRequest,
  TaskStatus,
  TaskTrace,
  TraceStep,
} from "./types";

type View = "tasks" | "diagnosis" | "permissions";
type Theme = "dark" | "light";

const terminalStatuses: TaskStatus[] = ["DONE", "FAILED", "CANCELLED"];

function getInitialTheme(): Theme {
  const savedTheme = window.localStorage.getItem("devagent-theme");
  if (savedTheme === "dark" || savedTheme === "light") return savedTheme;
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function shortId(value: string): string {
  return value.slice(0, 8);
}

function StatusBadge({ status }: { status: TaskStatus | string }) {
  return <span className={`status status-${status.toLowerCase()}`}>{status}</span>;
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}

function TraceDisclosure({
  initiallyOpen,
  children,
}: {
  initiallyOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(initiallyOpen);

  return (
    <details
      className="trace-disclosure"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      {children}
    </details>
  );
}

function eventIcon(type: string) {
  if (type.includes("tool")) return <Wrench size={15} />;
  if (type.includes("llm")) return <Sparkles size={15} />;
  if (type.includes("permission")) return <ShieldCheck size={15} />;
  if (type.includes("error") || type.includes("failed"))
    return <AlertTriangle size={15} />;
  if (type.includes("finished")) return <Check size={15} />;
  return <CircleDot size={15} />;
}

function EventCard({ step }: { step: TraceStep }) {
  const detailEntries = Object.entries(step.details).filter(
    ([, value]) => value !== null && value !== "" && value !== false,
  );
  const hasPayload = Object.keys(step.payload).length > 0;

  return (
    <article className={`event-card event-${step.event_type}`}>
      <div className="event-rail">
        <span className="event-dot">{eventIcon(step.event_type)}</span>
        <span className="event-line" />
      </div>
      <div className="event-body">
        <div className="event-heading">
          <div>
            <span className="event-type">{step.event_type.replaceAll("_", " ")}</span>
            <span className="sequence">#{step.sequence_id}</span>
          </div>
          <time>{formatTime(step.timestamp)}</time>
        </div>
        <p>{step.message}</p>
        {(hasPayload || detailEntries.length > 0) && (
          <details>
            <summary>查看事件数据</summary>
            <pre>
              {JSON.stringify(
                { ...step.details, ...(hasPayload ? { payload: step.payload } : {}) },
                null,
                2,
              )}
            </pre>
          </details>
        )}
      </div>
    </article>
  );
}

function App() {
  const [view, setView] = useState<View>("tasks");
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TaskTrace | null>(null);
  const [permissions, setPermissions] = useState<PermissionRequest[]>([]);
  const [serviceOnline, setServiceOnline] = useState<boolean | null>(null);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selectedTask = tasks.find((task) => task.task_id === selectedTaskId);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("devagent-theme", theme);
  }, [theme]);

  const loadTasks = useCallback(async () => {
    try {
      const result = await api.listTasks();
      const ordered = [...result.tasks].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      setTasks(ordered);
      setSelectedTaskId((current) => current ?? ordered[0]?.task_id ?? null);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务列表加载失败");
    } finally {
      setLoadingTasks(false);
    }
  }, []);

  const loadPermissions = useCallback(async () => {
    try {
      const result = await api.listPermissions();
      setPermissions(result.requests);
    } catch {
      // * 顶部服务状态已经能反馈连接异常，轮询审批时不重复打扰用户。
    }
  }, []);

  const loadTrace = useCallback(async (taskId: string) => {
    try {
      setTrace(await api.getTrace(taskId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Trace 加载失败");
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then(() => setServiceOnline(true))
      .catch(() => setServiceOnline(false));
    void loadTasks();
    void loadPermissions();
  }, [loadPermissions, loadTasks]);

  useEffect(() => {
    if (!selectedTaskId) {
      setTrace(null);
      return;
    }
    void loadTrace(selectedTaskId);
  }, [loadTrace, selectedTaskId]);

  useEffect(() => {
    if (!selectedTask || terminalStatuses.includes(selectedTask.status)) return;
    const refresh = () => {
      void loadTrace(selectedTask.task_id);
      void loadTasks();
      void loadPermissions();
    };
    const stream = openTaskStream(selectedTask.task_id, refresh, () => {
      stream.close();
    });
    return () => stream.close();
  }, [loadPermissions, loadTasks, loadTrace, selectedTask]);

  async function resolvePermission(requestId: string, decision: "ALLOW" | "DENY") {
    try {
      await api.resolvePermission(requestId, decision);
      await loadPermissions();
      await loadTasks();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "审批失败");
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><Bot size={22} /></span>
          <div>
            <strong>DevAgent</strong>
            <small>CONTROL PLANE</small>
          </div>
        </div>

        <nav>
          <button
            className={view === "tasks" ? "active" : ""}
            onClick={() => setView("tasks")}
          >
            <Activity size={18} /> Agent 任务
          </button>
          <button
            className={view === "diagnosis" ? "active" : ""}
            onClick={() => setView("diagnosis")}
          >
            <FileSearch size={18} /> CI 诊断
          </button>
          <button
            className={view === "permissions" ? "active" : ""}
            onClick={() => setView("permissions")}
          >
            <ShieldCheck size={18} /> 权限审批
            {permissions.length > 0 && (
              <span className="nav-count">{permissions.length}</span>
            )}
          </button>
          <button
            className="theme-toggle"
            onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
            aria-label={`切换到${theme === "dark" ? "亮色" : "暗色"}模式`}
            title={`切换到${theme === "dark" ? "亮色" : "暗色"}模式`}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            {theme === "dark" ? "亮色模式" : "暗色模式"}
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="service-row">
            <span className={`service-dot ${serviceOnline ? "online" : ""}`} />
            <div>
              <strong>{serviceOnline ? "API 已连接" : "API 未连接"}</strong>
              <small>127.0.0.1:8000</small>
            </div>
          </div>
          <div className="memory-note">
            <Server size={14} />
            <span>当前数据存储于进程内存</span>
          </div>
        </div>
      </aside>

      <main>
        {error && (
          <div className="error-banner">
            <AlertTriangle size={16} />
            <span>{error}</span>
            <button onClick={() => setError(null)} aria-label="关闭错误提示">
              <X size={16} />
            </button>
          </div>
        )}
        {view === "tasks" && (
          <TasksView
            tasks={tasks}
            selectedTask={selectedTask}
            trace={trace}
            loading={loadingTasks}
            onSelect={setSelectedTaskId}
            onRefresh={loadTasks}
            onCreated={async (taskId) => {
              await loadTasks();
              setSelectedTaskId(taskId);
            }}
            onCancel={async (taskId) => {
              try {
                await api.cancelTask(taskId);
                await loadTasks();
                await loadTrace(taskId);
              } catch (cause) {
                setError(cause instanceof Error ? cause.message : "取消任务失败");
              }
            }}
          />
        )}
        {view === "diagnosis" && <DiagnosisView onError={setError} />}
        {view === "permissions" && (
          <PermissionsView
            requests={permissions}
            onResolve={resolvePermission}
            onRefresh={loadPermissions}
          />
        )}
      </main>
    </div>
  );
}

function TasksView({
  tasks,
  selectedTask,
  trace,
  loading,
  onSelect,
  onRefresh,
  onCreated,
  onCancel,
}: {
  tasks: AgentTask[];
  selectedTask?: AgentTask;
  trace: TaskTrace | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onRefresh: () => Promise<void>;
  onCreated: (id: string) => Promise<void>;
  onCancel: (id: string) => Promise<void>;
}) {
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const filteredTasks = useMemo(
    () =>
      tasks.filter(
        (task) =>
          task.question.toLowerCase().includes(search.toLowerCase()) ||
          task.task_id.includes(search),
      ),
    [search, tasks],
  );

  async function submitTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    try {
      const provider = String(form.get("provider")) as "mock" | "real";
      const result = await api.createTask({
        question: String(form.get("question")),
        workspace: String(form.get("workspace")),
        provider,
        model: provider === "real" ? String(form.get("model") || "") || undefined : undefined,
        max_steps: Number(form.get("max_steps")),
        max_tool_calls: Number(form.get("max_tool_calls")),
      });
      setCreating(false);
      await onCreated(result.task_id);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="tasks-layout">
      <section className="task-list-pane">
        <header className="pane-header">
          <div>
            <span className="eyebrow">WORKSPACE</span>
            <h1>Agent 任务</h1>
          </div>
          <button className="icon-button" onClick={() => void onRefresh()}>
            <RefreshCw size={16} />
          </button>
        </header>
        <button className="primary-button create-button" onClick={() => setCreating(true)}>
          <Play size={16} fill="currentColor" /> 新建任务
        </button>
        <label className="search-box">
          <Search size={15} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索任务或 ID"
          />
        </label>
        <div className="task-list">
          {loading ? (
            <LoaderCircle className="spin centered" />
          ) : filteredTasks.length === 0 ? (
            <EmptyState
              icon={<Terminal />}
              title="还没有任务"
              description="创建一个任务，观察 Agent 的完整执行轨迹。"
            />
          ) : (
            filteredTasks.map((task) => (
              <button
                key={task.task_id}
                className={`task-item ${
                  selectedTask?.task_id === task.task_id ? "selected" : ""
                }`}
                onClick={() => onSelect(task.task_id)}
              >
                <div className="task-item-top">
                  <StatusBadge status={task.status} />
                  <time>{formatTime(task.created_at)}</time>
                </div>
                <strong>{task.question}</strong>
                <div className="task-meta">
                  <Code2 size={13} /> {task.workspace}
                  <span>#{shortId(task.task_id)}</span>
                </div>
              </button>
            ))
          )}
        </div>
      </section>

      <section className="trace-pane">
        {!selectedTask ? (
          <EmptyState
            icon={<Activity />}
            title="选择一个任务"
            description="这里会实时展示 LLM、工具调用和权限事件。"
          />
        ) : (
          <>
            <header className="trace-header">
              <div>
                <div className="trace-title-row">
                  <StatusBadge status={selectedTask.status} />
                  <span className="mono">TASK / {shortId(selectedTask.task_id)}</span>
                </div>
                <h2>{selectedTask.question}</h2>
                <p>{selectedTask.workspace} · {selectedTask.provider} provider</p>
              </div>
              {!terminalStatuses.includes(selectedTask.status) && (
                <button className="danger-button" onClick={() => void onCancel(selectedTask.task_id)}>
                  <Square size={14} fill="currentColor" /> 取消
                </button>
              )}
            </header>
            <div className="task-content">
              {trace?.summary.final_answer && (
                <article className="final-answer">
                  <div><Sparkles size={15} /> Agent 结果</div>
                  <p>{trace.summary.final_answer}</p>
                </article>
              )}
              <TraceDisclosure
                key={`${selectedTask.task_id}-${Boolean(trace?.summary.final_answer)}`}
                initiallyOpen={!trace?.summary.final_answer}
              >
                <summary>
                  <span>
                    <Activity size={15} />
                    执行轨迹
                    <small>{trace?.summary.event_count ?? 0} 个事件</small>
                  </span>
                  <span className="trace-summary-metrics">
                    {trace?.summary.tool_call_count ?? 0} tools · {trace?.summary.error_count ?? 0} errors
                  </span>
                </summary>
                <div className="metric-strip">
                  <Metric label="事件" value={trace?.summary.event_count ?? 0} />
                  <Metric label="LLM 调用" value={trace?.summary.llm_call_count ?? 0} />
                  <Metric label="工具调用" value={trace?.summary.tool_call_count ?? 0} />
                  <Metric label="错误" value={trace?.summary.error_count ?? 0} alert />
                </div>
                <div className="timeline">
                  {trace?.steps.length ? (
                    trace.steps.map((step) => <EventCard key={step.event_id} step={step} />)
                  ) : (
                    <EmptyState
                      icon={<Clock3 />}
                      title="等待事件"
                      description="任务开始执行后，事件会通过 SSE 实时显示。"
                    />
                  )}
                </div>
              </TraceDisclosure>
            </div>
          </>
        )}
      </section>

      {creating && (
        <div className="modal-backdrop" onMouseDown={() => setCreating(false)}>
          <form
            className="modal"
            onSubmit={(event) => void submitTask(event)}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span className="eyebrow">NEW RUN</span>
                <h2>创建 Agent 任务</h2>
              </div>
              <button type="button" className="icon-button" onClick={() => setCreating(false)}>
                <X size={18} />
              </button>
            </header>
            <label>
              任务描述
              <textarea
                name="question"
                required
                autoFocus
                defaultValue="请分析这个项目的核心架构和入口"
              />
            </label>
            <div className="form-grid">
              <label>
                Workspace
                <input name="workspace" defaultValue="." required />
              </label>
              <label>
                Provider
                <select name="provider" defaultValue="mock">
                  <option value="mock">Mock（离线演示）</option>
                  <option value="real">Real（服务端环境变量）</option>
                </select>
              </label>
              <label>
                Model（Real 可选覆盖）
                <input name="model" placeholder="例如 gpt-5" />
              </label>
              <label>
                最大步骤
                <input name="max_steps" type="number" min="1" max="50" defaultValue="10" />
              </label>
              <label>
                工具调用预算
                <input name="max_tool_calls" type="number" min="1" max="100" defaultValue="20" />
              </label>
            </div>
            <div className="modal-actions">
              <button type="button" className="secondary-button" onClick={() => setCreating(false)}>
                取消
              </button>
              <button className="primary-button" disabled={submitting}>
                {submitting ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
                启动任务
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  alert = false,
}: {
  label: string;
  value: number;
  alert?: boolean;
}) {
  return (
    <div className={alert && value > 0 ? "metric alert" : "metric"}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function DiagnosisView({ onError }: { onError: (message: string) => void }) {
  const [commitId, setCommitId] = useState("abc123");
  const [workspace, setWorkspace] = useState("examples/sample_repo");
  const [report, setReport] = useState<DiagnosisReport | null>(null);
  const [loading, setLoading] = useState(false);

  async function diagnose(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      setReport(await api.diagnoseCI(commitId, workspace));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "CI 诊断失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="content-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">EVIDENCE-DRIVEN</span>
          <h1>CI 失败诊断</h1>
          <p>从 CI 结果、代码与变更中收集证据，生成可追溯的根因报告。</p>
        </div>
      </header>
      <form className="diagnosis-form" onSubmit={(event) => void diagnose(event)}>
        <label>
          <GitCommitHorizontal size={16} /> Commit ID
          <input value={commitId} onChange={(event) => setCommitId(event.target.value)} />
        </label>
        <label>
          <Code2 size={16} /> Workspace
          <input value={workspace} onChange={(event) => setWorkspace(event.target.value)} />
        </label>
        <button className="primary-button" disabled={loading}>
          {loading ? <LoaderCircle className="spin" size={16} /> : <FileSearch size={16} />}
          开始诊断
        </button>
      </form>
      {!report ? (
        <div className="feature-placeholder">
          <EmptyState
            icon={<FileSearch />}
            title="准备诊断 sample CI"
            description="默认示例已指向 abc123。真实诊断需要服务端配置 LLM API Key 与模型。"
          />
          <div className="pipeline">
            <span>CI Result</span><ChevronRight size={16} />
            <span>Evidence</span><ChevronRight size={16} />
            <span>LLM Analysis</span><ChevronRight size={16} />
            <span>Report</span>
          </div>
        </div>
      ) : (
        <DiagnosisReportView report={report} />
      )}
    </div>
  );
}

function DiagnosisReportView({ report }: { report: DiagnosisReport }) {
  return (
    <div className="report">
      <section className="report-summary">
        <div>
          <StatusBadge status={report.status.toUpperCase()} />
          <span className="mono">{report.report_id}</span>
        </div>
        <h2>{report.summary}</h2>
        <p>诊断目标：{report.target}</p>
      </section>
      <div className="report-grid">
        <section className="report-section">
          <h3><AlertTriangle size={17} /> Findings</h3>
          {report.findings.map((finding, index) => (
            <article className="finding" key={`${finding.kind}-${index}`}>
              <div><span>{finding.kind}</span><b>{finding.confidence}</b></div>
              <p>{finding.statement}</p>
              <small>证据：{finding.evidence_ids.join(", ")}</small>
            </article>
          ))}
        </section>
        <section className="report-section">
          <h3><Wrench size={17} /> Recommendations</h3>
          {report.recommendations.map((item, index) => (
            <article className="recommendation" key={`${item.action}-${index}`}>
              <strong>{item.action}</strong>
              <p>{item.rationale}</p>
              <ol>{item.verification_steps.map((step) => <li key={step}>{step}</li>)}</ol>
            </article>
          ))}
        </section>
      </div>
      <section className="report-section evidence-section">
        <h3><FileSearch size={17} /> Evidence</h3>
        <div className="evidence-grid">
          {report.evidence.map((item) => (
            <article className="evidence-card" key={item.evidence_id}>
              <header><b>{item.evidence_id}</b><span>{item.kind}</span></header>
              <strong>{item.source}</strong>
              <small>{item.locator}</small>
              <pre>{item.excerpt}</pre>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function PermissionsView({
  requests,
  onResolve,
  onRefresh,
}: {
  requests: PermissionRequest[];
  onResolve: (id: string, decision: "ALLOW" | "DENY") => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="content-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">HUMAN IN THE LOOP</span>
          <h1>权限审批</h1>
          <p>高风险工具必须经过人工确认，参数会在执行前完整展示。</p>
        </div>
        <button className="secondary-button" onClick={() => void onRefresh()}>
          <RefreshCw size={15} /> 刷新
        </button>
      </header>
      {requests.length === 0 ? (
        <div className="feature-placeholder">
          <EmptyState
            icon={<ShieldCheck />}
            title="没有待审批请求"
            description="Agent 请求高风险工具时，审批卡片会出现在这里。"
          />
        </div>
      ) : (
        <div className="permission-list">
          {requests.map((request) => (
            <article className="permission-card" key={request.request_id}>
              <header>
                <div className="risk-icon"><AlertTriangle size={20} /></div>
                <div>
                  <span className="eyebrow">{request.risk_level} RISK</span>
                  <h2>{request.tool_name}</h2>
                </div>
                <time>{formatTime(request.created_at)}</time>
              </header>
              <p>{request.reason}</p>
              <pre>{JSON.stringify(request.tool_arguments, null, 2)}</pre>
              <div className="permission-meta">
                <span>Request #{shortId(request.request_id)}</span>
                {request.task_id && <span>Task #{shortId(request.task_id)}</span>}
              </div>
              <footer>
                <button className="deny-button" onClick={() => void onResolve(request.request_id, "DENY")}>
                  <Ban size={16} /> 拒绝
                </button>
                <button className="approve-button" onClick={() => void onResolve(request.request_id, "ALLOW")}>
                  <Check size={16} /> 本次允许
                </button>
              </footer>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
