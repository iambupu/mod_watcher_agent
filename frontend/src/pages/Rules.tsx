import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  SlidersHorizontal,
  Plus,
  Play,
  Edit,
  Trash2,
  Loader2,
  Download,
  Upload,
  Link2,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import AppSidebar from "@/components/layout/AppSidebar";
import {
  fetchRules,
  deleteRule,
  runRule,
  toggleRule,
  exportRules,
  importRulesByUrl,
  importRulesFromLocalFile,
} from "@/api/rules";
import { fetchJobRun, fetchJobRuns } from "@/api/jobs";
import type { WatchRule, ModSource } from "@/types";

const Rules: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [deleteTarget, setDeleteTarget] = useState<WatchRule | null>(null);
  const [runStatus, setRunStatus] = useState<Record<number, string>>({});
  const [isImporting, setIsImporting] = useState(false);
  const mountedRef = useRef(true);
  const ruleRunTokensRef = useRef(new Map<number, number>());
  const localImportInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      ruleRunTokensRef.current.clear();
    };
  }, []);

  const {
    data: rules = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["rules"],
    queryFn: fetchRules,
  });
  const { data: recentJobRuns } = useQuery({
    queryKey: ["job-runs-for-rules"],
    queryFn: () => fetchJobRuns(200),
    refetchInterval: 10000,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      setDeleteTarget(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      toggleRule(id, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
    },
  });

  const runMutation = useMutation({
    mutationFn: runRule,
    onSuccess: (data, ruleId) => {
      const token = Date.now();
      ruleRunTokensRef.current.set(ruleId, token);
      setRunStatus((prev) => ({
        ...prev,
        [ruleId]: t("jobs.queued", { jobId: data.job_id }),
      }));
      pollRuleJob(data.job_id, ruleId, token);
    },
    onError: (err: Error, ruleId) => {
      setRunStatus((prev) => ({
        ...prev,
        [ruleId]: t("jobs.failed", { error: err.message }),
      }));
    },
  });

  const pollRuleJob = async (jobId: number, ruleId: number, token: number) => {
    const isCurrentRun = () => mountedRef.current && ruleRunTokensRef.current.get(ruleId) === token;
    for (let i = 0; i < 60; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      if (!isCurrentRun()) return;
      const job = await fetchJobRun(jobId);
      if (!isCurrentRun()) return;
      if (job.status === "queued" || job.status === "running") {
        setRunStatus((prev) => ({
          ...prev,
          [ruleId]: t("jobs.running", { jobId, status: t(`jobs.status.${job.status}`) }),
        }));
        continue;
      }
      if (job.status === "failed") {
        setRunStatus((prev) => ({
          ...prev,
          [ruleId]: t("jobs.failed", { error: job.error_message || t("jobs.failedDefault") }),
        }));
        return;
      }
      setRunStatus((prev) => ({
        ...prev,
        [ruleId]: t("jobs.foundMods", { count: job.items_matched }),
      }));
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      return;
    }
  };

  const getSourceBadgeVariant = (
    source: ModSource,
  ): "info" | "success" => {
    return source === "nexusmods" ? "info" : "success";
  };

  const handleToggle = (rule: WatchRule) => {
    toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled });
  };

  const handleRun = (ruleId: number) => {
    runMutation.mutate(ruleId);
  };

  const latestRunByRuleId = React.useMemo(() => {
    const map = new Map<number, string>();
    const items = recentJobRuns?.items ?? [];
    for (const job of items) {
      if (job.job_name !== "run_rule_discovery") continue;
      const raw = job.metadata_json;
      if (!raw) continue;
      let parsed: Record<string, unknown> = {};
      try {
        parsed = JSON.parse(raw) as Record<string, unknown>;
      } catch {
        parsed = {};
      }
      const ruleId = Number(parsed.rule_id || 0);
      if (!ruleId || map.has(ruleId)) continue;
      map.set(ruleId, job.finished_at || job.started_at);
    }
    return map;
  }, [recentJobRuns?.items]);

  const formatTime = (value?: string) => {
    if (!value) return t("rules.neverRun");
    const normalized = value.includes("T") ? value : value.replace(" ", "T");
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  };

  const handleExport = async () => {
    const payload = await exportRules();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `mod_watcher_rules_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  const refreshAfterImport = () => {
    queryClient.invalidateQueries({ queryKey: ["rules"] });
    queryClient.invalidateQueries({ queryKey: ["job-runs-for-rules"] });
  };

  const handleImportByUrl = async () => {
    const url = window.prompt(t("rules.importByUrl"));
    if (!url) return;
    setIsImporting(true);
    try {
      const result = await importRulesByUrl(url);
      alert(t("rules.importDone", { imported: result.imported, skipped: result.skipped }));
      refreshAfterImport();
    } catch (err) {
      alert((err as Error).message || t("rules.importFailed"));
    } finally {
      setIsImporting(false);
    }
  };

  const handleImportLocal: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setIsImporting(true);
    try {
      const result = await importRulesFromLocalFile(file);
      alert(t("rules.importDone", { imported: result.imported, skipped: result.skipped }));
      refreshAfterImport();
    } catch (err) {
      alert((err as Error).message || t("rules.importFailed"));
    } finally {
      setIsImporting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <AppSidebar active="rules" />

        <main className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-gray-900">
              {t("rules.title")}
            </h2>
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={handleExport}>
                <Download size={16} />
                <span className="ml-1">{t("settings.export")}</span>
              </Button>
              <input
                ref={localImportInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={handleImportLocal}
              />
              <Button
                variant="outline"
                disabled={isImporting}
                onClick={() => localImportInputRef.current?.click()}
              >
                <Upload size={16} />
                <span className="ml-1">{t("rules.importLocal")}</span>
              </Button>
              <Button variant="outline" onClick={handleImportByUrl} disabled={isImporting}>
                <Link2 size={16} />
                <span className="ml-1">{t("rules.importUrl")}</span>
              </Button>
              <Button onClick={() => navigate("/rules/new")}>
                <Plus size={16} />
                <span className="ml-1">{t("common.create")}</span>
              </Button>
            </div>
          </div>

          {isLoading ? (
            <div className="text-center py-12">
              <Loader2 size={32} className="animate-spin mx-auto text-gray-400" />
              <p className="text-gray-500 mt-2">{t("rules.loading")}</p>
            </div>
          ) : isError ? (
            <div className="text-center py-12">
              <p className="text-red-500">
                {(error as Error)?.message || t("rules.loadFailed")}
              </p>
              <Button
                variant="outline"
                className="mt-2"
                onClick={() =>
                  queryClient.invalidateQueries({ queryKey: ["rules"] })
                }
              >
                {t("common.retry")}
              </Button>
            </div>
          ) : rules.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <SlidersHorizontal
                  size={48}
                  className="mx-auto text-gray-300 mb-4"
                />
                <p className="text-gray-500">{t("rules.noRules")}</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {rules.map((rule) => (
                <Card key={rule.id}>
                  <CardContent className="py-4">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => {
                            handleToggle(rule);
                          }}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
                            rule.enabled ? "bg-blue-600" : "bg-gray-300"
                          }`}
                          aria-label={
                            rule.enabled ? t("rules.disableRule") : t("rules.enableRule")
                          }
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                              rule.enabled ? "translate-x-6" : "translate-x-1"
                            }`}
                          />
                        </button>
                        <div>
                          <h3 className="font-medium text-gray-900">
                            {rule.name}
                          </h3>
                          <div className="flex gap-1 flex-wrap mt-1">
                            <Badge variant={getSourceBadgeVariant(rule.source)}>
                              {rule.source}
                            </Badge>
                          </div>
                          <div className="mt-1 text-xs text-gray-500">
                            {t("rules.lastRun")}: {formatTime(latestRunByRuleId.get(rule.id))}
                            <span className="mx-2">·</span>
                            {t("rules.intervalMinutes", { minutes: rule.intervalMinutes })}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleRun(rule.id)}
                          disabled={runMutation.isPending}
                        >
                          <Play size={14} />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => navigate(`/rules/${rule.id}/edit`)}
                        >
                          <Edit size={14} />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setDeleteTarget(rule)}
                        >
                          <Trash2 size={14} className="text-red-500" />
                        </Button>
                      </div>
                    </div>
                    {runStatus[rule.id] && (
                      <p className="text-xs text-blue-600 mt-2">
                        {runStatus[rule.id]}
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {deleteTarget && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
              <div className="bg-white rounded-xl p-6 shadow-xl max-w-sm w-full mx-4">
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  {t("rules.deleteTitle")}
                </h3>
                <p className="text-sm text-gray-600 mb-4">
                  {t("rules.deleteConfirm", { name: deleteTarget.name })}
                </p>
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setDeleteTarget(null)}
                    disabled={deleteMutation.isPending}
                  >
                    {t("common.cancel")}
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => deleteMutation.mutate(deleteTarget.id)}
                    disabled={deleteMutation.isPending}
                  >
                    {deleteMutation.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      t("common.delete")
                    )}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default Rules;
