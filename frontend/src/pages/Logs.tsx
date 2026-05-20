import React, { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Inbox,
  AlertCircle,
  Activity,
  Settings2,
  Link2,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import AppSidebar from "@/components/layout/AppSidebar";
import { MarkdownText } from "@/components/MarkdownText";
import { fetchLogs, openLogDirectory } from "@/api/logging";
import { fetchJobRuns, fetchSchedulerStatus, type JobRun, type SchedulerJob } from "@/api/jobs";

const levelBadge: Record<string, "default" | "info" | "warning" | "danger"> = {
  DEBUG: "default",
  INFO: "info",
  WARNING: "warning",
  ERROR: "danger",
};

function LogSkeleton() {
  return (
    <div className="space-y-1">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-2.5 animate-pulse">
          <div className="h-3 w-28 bg-gray-200 rounded" />
          <div className="h-5 w-14 bg-gray-200 rounded-full" />
          <div className="h-3 w-20 bg-gray-200 rounded" />
          <div className="h-3 flex-1 bg-gray-200 rounded" />
        </div>
      ))}
    </div>
  );
}

const Logs: React.FC = () => {
  const { t } = useTranslation();
  const [level, setLevel] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"logs" | "finished" | "running">("logs");
  const listEndRef = useRef<HTMLDivElement>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["logs", level, search],
    queryFn: () =>
      fetchLogs({
        level: level === "ALL" ? undefined : level,
        search: search || undefined,
        limit: 200,
      }),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });

  const entries = data?.entries ?? [];
  const { data: jobRuns, refetch: refetchJobs, isFetching: jobsFetching } = useQuery({
    queryKey: ["job-runs"],
    queryFn: () => fetchJobRuns(50),
    refetchInterval: 5000,
    enabled: activeTab !== "logs",
  });
  const tasks = jobRuns?.items ?? [];
  const runningTasks = tasks.filter((task) => task.status === "queued" || task.status === "running");
  const finishedTasks = tasks.filter((task) => task.status === "succeeded" || task.status === "failed");
  const { data: schedulerStatus, refetch: refetchSchedulerStatus } = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: fetchSchedulerStatus,
    refetchInterval: 5000,
    enabled: activeTab !== "logs",
  });
  const schedulerJobs = schedulerStatus?.jobs ?? [];
  const refreshTasks = () => {
    refetchJobs();
    refetchSchedulerStatus();
  };

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <AppSidebar active="logs" />

        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-5xl mx-auto">
            <div className="mb-6 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-2xl font-bold text-gray-900">{t("logs.title")}</h2>
                  <button
                    type="button"
                    title="打开日志目录"
                    onClick={async () => {
                      try {
                        await openLogDirectory();
                      } catch {
                        // Keep UI quiet; this is a convenience shortcut only.
                      }
                    }}
                    className="inline-flex h-6 w-6 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  >
                    <Link2 size={13} />
                  </button>
                </div>
                <p className="text-sm text-gray-500 mt-1">
                  {t("common.total", { total: entries.length })}
                  <span className="ml-2 text-xs text-gray-400">本地时区显示</span>
                  {isFetching && (
                    <span className="ml-2 text-blue-500 text-xs">
                      {t("logs.autoRefresh")}
                    </span>
                  )}
                </p>
              </div>
            </div>

            <div className="mb-4 flex gap-2 items-center">
              <button
                type="button"
                onClick={() => setActiveTab("logs")}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${activeTab === "logs" ? "bg-blue-600 text-white" : "border border-gray-300 bg-white text-gray-700"}`}
              >
                运行日志
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("finished")}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${activeTab === "finished" ? "bg-blue-600 text-white" : "border border-gray-300 bg-white text-gray-700"}`}
              >
                已结束任务
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("running")}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${activeTab === "running" ? "bg-blue-600 text-white" : "border border-gray-300 bg-white text-gray-700"}`}
              >
                运行中任务
              </button>
            </div>

            {activeTab === "logs" && (
            <div className="mb-4 flex gap-2 items-center">
              <select
                className="border rounded px-2 py-1.5 text-sm"
                value={level}
                onChange={(e) => {
                  setLevel(e.target.value);
                  setExpandedIndex(null);
                }}
              >
                <option value="ALL">{t("logs.levelAll")}</option>
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>

              <input
                className="border rounded px-3 py-1.5 text-sm w-48"
                type="text"
                placeholder={t("logs.searchPlaceholder")}
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setExpandedIndex(null);
                }}
              />

              <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading}>
                <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
                <span className="ml-1.5">{t("common.refresh")}</span>
              </Button>
            </div>
            )}

            {activeTab !== "logs" ? (
              <Card>
                <CardContent className="p-0">
                  <div className="border-b border-gray-100 px-4 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                      <Activity size={16} />
                      <span>{activeTab === "finished" ? "已结束任务" : "运行中任务"}</span>
                      {jobsFetching && <span className="text-xs text-blue-500">刷新中</span>}
                    </div>
                    <Button variant="outline" size="sm" onClick={refreshTasks}>
                      <RefreshCw size={14} />
                      <span className="ml-1.5">{t("common.refresh")}</span>
                    </Button>
                  </div>
                  {(activeTab === "finished" ? finishedTasks : runningTasks).length === 0 ? (
                    <div className="flex flex-col items-center gap-3 py-12">
                      <Inbox size={40} className="text-gray-300" />
                      <p className="text-sm text-gray-500">{activeTab === "finished" ? "暂无已结束任务" : "当前没有运行中任务"}</p>
                    </div>
                  ) : (
                    <div className="divide-y divide-gray-100">
                      {(activeTab === "finished" ? finishedTasks : runningTasks).map((task) => (
                        <TaskRow
                          key={task.id}
                          task={task}
                          schedulerJob={findSchedulerJob(task, schedulerJobs)}
                          showNextRun={activeTab === "finished"}
                        />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : isError ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-12">
                  <AlertCircle size={40} className="text-red-400" />
                  <p className="text-sm text-gray-500">{t("logs.loadError")}</p>
                  <Button variant="outline" onClick={() => refetch()}>
                    {t("common.retry")}
                  </Button>
                </CardContent>
              </Card>
            ) : isLoading ? (
              <Card>
                <CardContent className="p-0">{<LogSkeleton />}</CardContent>
              </Card>
            ) : entries.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-12">
                  <Inbox size={40} className="text-gray-300" />
                  <p className="text-sm text-gray-500">{t("logs.empty")}</p>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <div className="divide-y divide-gray-100">
                    {entries.map((entry, idx) => {
                      const isExpanded = expandedIndex === idx;
                      return (
                        <div key={idx}>
                          <div
                            className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 cursor-pointer transition-colors"
                            onClick={() =>
                              setExpandedIndex(isExpanded ? null : idx)
                            }
                          >
                            <span className="w-4 text-gray-400 flex-shrink-0">
                              {isExpanded ? (
                                <ChevronDown size={14} />
                              ) : (
                                <ChevronRight size={14} />
                              )}
                            </span>
                            <span className="text-xs text-gray-500 whitespace-nowrap w-36 flex-shrink-0">
                              {formatLogTime(entry.time || entry.timestamp)}
                            </span>
                            <Badge variant={levelBadge[entry.level] ?? "default"}>
                              {entry.level}
                            </Badge>
                            <span className="text-xs font-medium text-gray-500 whitespace-nowrap w-28 flex-shrink-0 truncate">
                              {entry.module || entry.name || "-"}
                            </span>
                            <span className="text-sm text-gray-700 truncate flex-1">
                              {entry.message}
                            </span>
                          </div>
                          {isExpanded && (
                            <div className="px-12 py-3 bg-gray-50">
                              <MarkdownText
                                text={entry.message}
                                className="text-sm text-gray-600"
                              />
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div ref={listEndRef} />
                </CardContent>
              </Card>
            )}
          </div>
        </main>
      </div>
    </div>
  );
};

export default Logs;

const SCHEDULED_JOB_MATCHERS: Array<{ ids: string[]; names: string[] }> = [
  {
    ids: ["discover_new_mods"],
    names: ["discover_all", "run_rule_discovery", "discover_new_mods"],
  },
  {
    ids: ["check_favorite_updates"],
    names: ["check_favorites", "check_favorite_updates"],
  },
  {
    ids: ["generate_summaries"],
    names: ["generate_summaries", "llm_generate_summaries", "llm_translate_summaries"],
  },
  {
    ids: ["llm_summary_report"],
    names: ["llm_summary_report"],
  },
  {
    ids: ["send_digest"],
    names: ["send_digest", "daily_digest"],
  },
];

function findSchedulerJob(task: JobRun, schedulerJobs: SchedulerJob[]): SchedulerJob | undefined {
  const normalized = task.job_name.toLowerCase();
  if (normalized === "run_rule_discovery") {
    const metadata = parseTaskMetadata(task.metadata_json);
    const ruleId = Number(metadata.rule_id || 0);
    if (ruleId > 0) {
      const exactRuleJobId = `discover_rule_${ruleId}`;
      const exact = schedulerJobs.find((job) => job.id === exactRuleJobId);
      if (exact) return exact;
    }
    const fallback = schedulerJobs.find((job) => job.id.startsWith("discover_rule_"));
    if (fallback) return fallback;
  }
  const matcher = SCHEDULED_JOB_MATCHERS.find((item) => item.names.includes(normalized));
  if (matcher) {
    return schedulerJobs.find((job) => matcher.ids.includes(job.id));
  }
  return schedulerJobs.find((job) => job.id === normalized || job.name.toLowerCase() === normalized);
}

function TaskRow({
  task,
  schedulerJob,
  showNextRun,
}: {
  task: JobRun;
  schedulerJob?: SchedulerJob;
  showNextRun: boolean;
}) {
  const metadata = parseTaskMetadata(task.metadata_json);
  const ruleId = Number(metadata.rule_id || 0);
  const ruleName = String(metadata.rule_name || "");
  const llmModel = String(metadata.llm_model || metadata.model || "");
  const isRuleRun = task.job_name === "run_rule_discovery";
  const isLlmTask = task.job_name.startsWith("llm_") || task.job_name.includes("summary");

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-3">
        <Badge variant={task.status === "failed" ? "danger" : task.status === "succeeded" ? "info" : "warning"}>
          {task.status}
        </Badge>
        <span className="text-sm font-semibold text-gray-900">{task.job_name}</span>
        <span className="ml-auto text-xs text-gray-500">{formatLogTime(task.started_at)}</span>
      </div>
      {isRuleRun && ruleName && (
        <div className="mt-2 flex items-center gap-2 text-xs text-gray-700">
          {ruleId > 0 && (
            <a
              href={`/rules/${ruleId}/edit`}
              className="inline-flex items-center justify-center rounded-md border border-gray-300 px-2 py-1 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              <Settings2 size={12} />
              <span className="ml-1">规则设置</span>
            </a>
          )}
          <span>规则：<span className="font-medium">{ruleName}</span></span>
        </div>
      )}
      {isLlmTask && llmModel && (
        <div className="mt-2 text-xs text-gray-700">
          模型：<span className="font-medium">{llmModel}</span>
        </div>
      )}
      <div className="mt-2 grid grid-cols-2 gap-3 text-xs text-gray-500 md:grid-cols-4">
        <span>扫描 {task.items_scanned}</span>
        <span>匹配 {task.items_matched}</span>
        <span>{task.finished_at ? `完成 ${formatLogTime(task.finished_at)}` : "执行中"}</span>
        {showNextRun && schedulerJob ? (
          <span>下次执行 {formatLogTime(schedulerJob.next_run_time || undefined)}</span>
        ) : showNextRun ? (
          <span>非定时任务</span>
        ) : null}
      </div>
      {task.error_message && (
        <MarkdownText
          text={task.error_message}
          className="mt-2 text-xs text-red-600"
        />
      )}
    </div>
  );
}

function formatLogTime(value?: string): string {
  if (!value) return "-";
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function parseTaskMetadata(raw?: string | null): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}
