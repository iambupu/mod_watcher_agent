import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  Beaker,
  CheckCircle2,
  Clock3,
  RotateCcw,
  Save,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import AppSidebar from "@/components/layout/AppSidebar";
import { RuleBasicSection } from "@/components/rules/RuleBasicSection";
import { Panel } from "@/components/ui/Panel";
import { SourceTabs } from "@/components/rules/SourceTabs";
import { NexusModsRulePanel } from "@/components/rules/NexusModsRulePanel";
import { LoversLabRulePanel } from "@/components/rules/LoversLabRulePanel";
import { CommonFilterSection } from "@/components/rules/CommonFilterSection";
import { LlmFilterSection } from "@/components/rules/LlmFilterSection";
import { NotificationSection } from "@/components/rules/NotificationSection";
import { RuleTestResultPanel } from "@/components/rules/RuleTestResultPanel";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import {
  fetchRuleById,
  createRule,
  updateRule,
  testRule,
} from "@/api/rules";
import { parseWholeIntegerInput } from "@/utils/numberInput";
import type { CommonRuleFilters, RuleTestResponse, RuleTestRequest, WatchRule } from "@/types";

function parseRuleRouteId(id: string | undefined): number | null {
  if (!id) return null;
  const value = parseWholeIntegerInput(id, { min: 1 });
  return typeof value === "number" ? value : null;
}

export const RuleEditorPage: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const editingRuleId = parseRuleRouteId(id);
  const isEditMode = editingRuleId !== null;

  const activeSource = useRuleEditorStore((s) => s.activeSource);
  const commonFilters = useRuleEditorStore((s) => s.draft.commonFilters);
  const isDirty = useRuleEditorStore((s) => s.isDirty);
  const ruleName = useRuleEditorStore((s) => s.draft.name);
  const enabled = useRuleEditorStore((s) => s.draft.enabled);
  const setBasicInfo = useRuleEditorStore((s) => s.setBasicInfo);
  const updateCommonFilter = useRuleEditorStore((s) => s.updateCommonFilter);
  const resetDraft = useRuleEditorStore((s) => s.resetDraft);
  const loadRule = useRuleEditorStore((s) => s.loadRule);
  const getSubmitData = useRuleEditorStore((s) => s.getSubmitData);

  const [testResult, setTestResult] = useState<RuleTestResponse | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const ruleQuery = useQuery({
    queryKey: ["rule", editingRuleId],
    queryFn: () => fetchRuleById(editingRuleId!),
    enabled: isEditMode,
    staleTime: 0,
    refetchOnMount: "always",
  });

  useEffect(() => {
    if (!isEditMode) {
      resetDraft();
      setTestResult(null);
      setTestError(null);
    }
  }, [isEditMode, resetDraft]);

  useEffect(() => {
    if (ruleQuery.data && isEditMode) {
      loadRule(ruleQuery.data);
    }
  }, [ruleQuery.data, isEditMode, loadRule]);

  const createMutation = useMutation({
    mutationFn: createRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      navigate("/rules");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id: ruleId, data }: { id: number; data: Partial<WatchRule> }) =>
      updateRule(ruleId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      navigate("/rules");
    },
  });

  const testMutation = useMutation({
    mutationFn: (req: RuleTestRequest) => testRule(req),
    onSuccess: (data) => {
      setTestResult(data);
      setTestError(null);
    },
    onError: (err: Error) => {
      setTestError(err.message);
    },
  });

  const handleSave = () => {
    commitFocusedInput();
    const submitData = getSubmitData();
    if (isEditMode && editingRuleId) {
      updateMutation.mutate({ id: editingRuleId, data: submitData });
    } else {
      createMutation.mutate(submitData);
    }
  };

  const handleCancel = () => {
    navigate("/rules");
  };

  const handleCommonFilterChange = (patch: Partial<CommonRuleFilters>) => {
    updateCommonFilter(patch);
  };

  const handleTest = () => {
    commitFocusedInput();
    const submitData = getSubmitData();
    testMutation.mutate({ rule: submitData, dryRun: true });
  };

  const saving = createMutation.isPending || updateMutation.isPending;
  const saveDisabled = !isDirty || !ruleName.trim() || saving;
  const testStatusOk = Boolean(testResult && !testError);

  const commitFocusedInput = () => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  };

  if (isEditMode && ruleQuery.isLoading) {
    return (
      <div className="flex h-screen bg-slate-50">
        <AppSidebar active="rules" />
        <main className="flex-1 overflow-y-auto">
          <div className="flex h-64 items-center justify-center">
            <p className="text-gray-500">{t("common.loading")}</p>
          </div>
        </main>
      </div>
    );
  }

  if (isEditMode && ruleQuery.isError) {
    return (
      <div className="flex h-screen bg-slate-50">
        <AppSidebar active="rules" />
        <main className="flex-1 overflow-y-auto">
          <div className="flex h-64 items-center justify-center">
            <p className="text-red-500">{t("common.error")}</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-50">
      <AppSidebar active="rules" />
      <main className="flex-1 overflow-y-auto">
        <div className="space-y-5 px-6 py-6 lg:px-8">
          <header className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex items-start gap-4">
              <button
                type="button"
                onClick={handleCancel}
                className="mt-1 inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-600 transition hover:bg-white hover:text-slate-950 hover:shadow-sm"
                aria-label={t("common.cancel")}
              >
                <ArrowLeft size={22} />
              </button>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-bold tracking-normal text-slate-950">
                    {isEditMode ? t("rules.editRule") : t("rules.newRule")}
                  </h1>
                  <span className="rounded-md bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">
                    {activeSource === "nexusmods" ? t("rules.sourceTabs.nexusmods") : t("rules.sourceTabs.loverslab")}
                  </span>
                </div>
                <p className="mt-1 text-sm font-semibold text-slate-500">{t("rules.editorSubtitle")}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-500">
                <Clock3 size={16} />
                {isDirty ? t("rules.unsavedChanges") : t("rules.noUnsavedChanges")}
              </span>
              <Panel as="div" padding="none" className="flex h-10 items-center px-3">
                <Switch
                  checked={enabled}
                  onCheckedChange={(checked) => setBasicInfo({ enabled: checked })}
                  label={t("rules.basic.enabledLabel")}
                />
              </Panel>
              <Button type="button" onClick={handleSave} disabled={saveDisabled} className="h-10 rounded-lg px-4">
                <Save size={16} />
                <span className="ml-2">{t("rules.actions.saveRule")}</span>
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={handleTest}
                disabled={testMutation.isPending}
                className="h-10 rounded-lg bg-white px-4"
              >
                <Beaker size={16} />
                <span className="ml-2">{t("rules.actions.testRule")}</span>
              </Button>
              <Button type="button" variant="ghost" onClick={handleCancel} className="h-10 rounded-lg px-4">
                <RotateCcw size={16} />
                <span className="ml-2">{t("common.cancel")}</span>
              </Button>
            </div>
          </header>

          <RuleStepper />

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-5">
              <RuleSection index={1} title={t("rules.basicInfo")}>
                <RuleBasicSection />
              </RuleSection>

              <RuleSection index={2} title={t("rules.source")} description={t("rules.sourceHelp")}>
                <div className="space-y-4">
                  <SourceTabs />
                  {activeSource === "nexusmods" ? (
                    <NexusModsRulePanel />
                  ) : (
                    <LoversLabRulePanel />
                  )}
                </div>
              </RuleSection>

              <RuleSection index={3} title={t("rules.filters")} description={t("rules.filters.commonFiltersHelp")}>
                <CommonFilterSection />
              </RuleSection>

              <RuleSection index={4} title={t("rules.filters.llmFilter")}>
                <LlmFilterSection
                  llmFilter={commonFilters.llmFilter}
                  onChange={handleCommonFilterChange}
                />
              </RuleSection>

              <RuleSection index={5} title={t("rules.notification")}>
                <NotificationSection />
              </RuleSection>

              {(testError || createMutation.isError || updateMutation.isError) && (
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-600">
                  {testError || (createMutation.error || updateMutation.error)?.message}
                </div>
              )}
            </div>

            <aside className="space-y-4 xl:sticky xl:top-6 xl:self-start">
              <Panel as="section" padding="md" className="space-y-3">
                <div className="flex items-center justify-end">
                  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${
                    testStatusOk ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                  }`}>
                    {testStatusOk ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                    {testStatusOk ? t("rules.test.statusHealthy") : t("rules.test.statusPending")}
                  </span>
                </div>
                <RuleTestResultPanel result={testResult} />
              </Panel>

              <section className="rounded-lg border border-blue-100 bg-blue-50/60 p-4 text-sm text-slate-600">
                <p className="font-bold text-slate-800">{t("rules.editorTipTitle")}</p>
                <p className="mt-2 leading-6">{t("rules.editorTipBody")}</p>
              </section>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
};

function RuleStepper() {
  const { t } = useTranslation();
  const steps = [
    t("rules.basicInfo"),
    t("rules.source"),
    t("rules.filters"),
    t("rules.filters.llmFilter"),
    t("rules.notification"),
    t("rules.test.title"),
  ];

  return (
    <Panel padding="none" className="space-y-0 px-5 py-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {steps.map((step, index) => (
          <div key={step} className="flex items-center gap-2">
            <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
              index === 0 ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-500"
            }`}>
              {index + 1}
            </span>
            <span className={`truncate text-sm font-bold ${index === 0 ? "text-slate-900" : "text-slate-500"}`}>
              {step}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function RuleSection({
  index,
  title,
  description,
  children,
}: {
  index: number;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Panel as="section" padding="none" className="p-5">
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-700">
          {index}
        </span>
        <div>
          <h2 className="text-lg font-bold text-slate-950">{title}</h2>
          {description ? <p className="mt-1 text-sm font-semibold text-slate-500">{description}</p> : null}
        </div>
      </div>
      {children}
    </Panel>
  );
}
