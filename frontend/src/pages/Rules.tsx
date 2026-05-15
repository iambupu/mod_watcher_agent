import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  SlidersHorizontal,
  Search,
  LayoutDashboard,
  Heart,
  Bell,
  Settings,
  Plus,
  Play,
  Edit,
  Trash2,
  Loader2,
  FileText,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import {
  fetchRules,
  deleteRule,
  runRule,
  toggleRule,
} from "@/api/rules";
import { fetchJobRun } from "@/api/jobs";
import type { WatchRule, ModSource } from "@/types";

const NavLink: React.FC<{
  href: string;
  icon: React.ReactNode;
  label: string;
  active?: boolean;
}> = ({ href, icon, label, active }) => (
  <a
    href={href}
    className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      active
        ? "bg-blue-50 text-blue-700"
        : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
    }`}
  >
    {icon}
    {label}
  </a>
);

const Rules: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [deleteTarget, setDeleteTarget] = useState<WatchRule | null>(null);
  const [runStatus, setRunStatus] = useState<Record<number, string>>({});

  const {
    data: rules = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["rules"],
    queryFn: fetchRules,
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
      setRunStatus((prev) => ({
        ...prev,
        [ruleId]: `Queued job #${data.job_id}`,
      }));
      pollRuleJob(data.job_id, ruleId);
    },
    onError: (err: Error, ruleId) => {
      setRunStatus((prev) => ({
        ...prev,
        [ruleId]: `Error: ${err.message}`,
      }));
    },
  });

  const pollRuleJob = async (jobId: number, ruleId: number) => {
    for (let i = 0; i < 60; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const job = await fetchJobRun(jobId);
      if (job.status === "queued" || job.status === "running") {
        setRunStatus((prev) => ({
          ...prev,
          [ruleId]: `Job #${jobId} ${job.status}`,
        }));
        continue;
      }
      if (job.status === "failed") {
        setRunStatus((prev) => ({
          ...prev,
          [ruleId]: `Error: ${job.error_message || "job failed"}`,
        }));
        return;
      }
      setRunStatus((prev) => ({
        ...prev,
        [ruleId]: `Found ${job.items_matched} new mods`,
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

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center gap-2">
            <img src="/mwlogo.png" alt="Mod Watcher" className="h-12 w-auto" />
            <span className="text-lg font-bold text-gray-900">Mod Watcher</span>
          </div>

          <nav className="flex-1 px-3 py-4 space-y-1">
            <NavLink
              href="/"
              icon={<LayoutDashboard size={18} />}
              label={t("nav.dashboard")}
            />
            <NavLink
              href="/discover"
              icon={<Search size={18} />}
              label={t("nav.discover")}
            />
            <NavLink
              href="/favorites"
              icon={<Heart size={18} />}
              label={t("nav.favorites")}
            />
            <NavLink
              href="/updates"
              icon={<Bell size={18} />}
              label={t("nav.updates")}
            />
            <NavLink
              href="/rules"
              icon={<SlidersHorizontal size={18} />}
              label={t("nav.rules")}
              active
            />
            <NavLink
              href="/logs"
              icon={<FileText size={18} />}
              label={t("nav.logs")}
            />
            <NavLink
              href="/settings"
              icon={<Settings size={18} />}
              label={t("nav.settings")}
            />
          </nav>

        </aside>

        <main className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-gray-900">
              {t("rules.title")}
            </h2>
            <Button
              onClick={() => navigate("/rules/new")}
            >
              <Plus size={16} />
              <span className="ml-1">{t("common.create")}</span>
            </Button>
          </div>

          {isLoading ? (
            <div className="text-center py-12">
              <Loader2 size={32} className="animate-spin mx-auto text-gray-400" />
              <p className="text-gray-500 mt-2">Loading rules...</p>
            </div>
          ) : isError ? (
            <div className="text-center py-12">
              <p className="text-red-500">
                {(error as Error)?.message || "Failed to load rules"}
              </p>
              <Button
                variant="outline"
                className="mt-2"
                onClick={() =>
                  queryClient.invalidateQueries({ queryKey: ["rules"] })
                }
              >
                Retry
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
                            rule.enabled ? "Disable rule" : "Enable rule"
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
                          <div className="flex gap-1 flex-wrap mt-0.5">
                            <Badge variant={getSourceBadgeVariant(rule.source)}>
                              {rule.source}
                            </Badge>
                            {rule.filters?.includeKeywords &&
                              rule.filters.includeKeywords.length > 0 && (
                                <span className="text-xs text-gray-500">
                                  +{rule.filters.includeKeywords.join(", ")}
                                </span>
                              )}
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
                  Delete Rule
                </h3>
                <p className="text-sm text-gray-600 mb-4">
                  Are you sure you want to delete "{deleteTarget.name}"? This
                  action cannot be undone.
                </p>
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setDeleteTarget(null)}
                    disabled={deleteMutation.isPending}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => deleteMutation.mutate(deleteTarget.id)}
                    disabled={deleteMutation.isPending}
                  >
                    {deleteMutation.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      "Delete"
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
