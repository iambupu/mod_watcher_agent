import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { RuleBasicSection } from "@/components/rules/RuleBasicSection";
import { SourceTabs } from "@/components/rules/SourceTabs";
import { NexusModsRulePanel } from "@/components/rules/NexusModsRulePanel";
import { LoversLabRulePanel } from "@/components/rules/LoversLabRulePanel";
import { CommonFilterSection } from "@/components/rules/CommonFilterSection";
import { NotificationSection } from "@/components/rules/NotificationSection";
import { RuleTestResultPanel } from "@/components/rules/RuleTestResultPanel";
import { RuleEditorActions } from "@/components/rules/RuleEditorActions";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import {
  fetchRuleById,
  createRule,
  updateRule,
  testRule,
} from "@/api/rules";
import type { RuleTestResponse, RuleTestRequest, WatchRule } from "@/types";

export const RuleEditorPage: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const editingRuleId = id ? Number(id) : null;
  const isEditMode = editingRuleId !== null;

  const activeSource = useRuleEditorStore((s) => s.activeSource);
  const resetDraft = useRuleEditorStore((s) => s.resetDraft);
  const loadRule = useRuleEditorStore((s) => s.loadRule);
  const getSubmitData = useRuleEditorStore((s) => s.getSubmitData);

  const [testResult, setTestResult] = useState<RuleTestResponse | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const ruleQuery = useQuery({
    queryKey: ["rule", editingRuleId],
    queryFn: () => fetchRuleById(editingRuleId!),
    enabled: isEditMode,
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

  const handleTest = () => {
    const draft = useRuleEditorStore.getState().draft;
    const source = useRuleEditorStore.getState().activeSource;
    const sourceConfig =
      source === "nexusmods" ? draft.nexusmodsDraft : draft.loverslabDraft;
    const ruleLike: WatchRule = {
      id: 0,
      name: draft.name,
      enabled: draft.enabled,
      intervalMinutes: draft.intervalMinutes,
      source,
      sourceConfig,
      filters: draft.commonFilters,
      notification: draft.notification,
      createdAt: "",
      updatedAt: "",
    };
    testMutation.mutate({ rule: ruleLike, dryRun: true });
  };

  const saving = createMutation.isPending || updateMutation.isPending;

  if (isEditMode && ruleQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500">{t("common.loading")}</p>
      </div>
    );
  }

  if (isEditMode && ruleQuery.isError) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-red-500">{t("common.error")}</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">
        {isEditMode ? t("rules.editRule") : t("rules.newRule")}
      </h1>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-gray-700">
            {t("rules.basicInfo")}
          </h2>
        </CardHeader>
        <CardContent>
          <RuleBasicSection />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-gray-700">
            {t("rules.source")}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <SourceTabs />
          {activeSource === "nexusmods" ? (
            <NexusModsRulePanel />
          ) : (
            <LoversLabRulePanel />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-gray-700">
            {t("rules.filters")}
          </h2>
        </CardHeader>
        <CardContent>
          <CommonFilterSection />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-gray-700">
            {t("rules.notification")}
          </h2>
        </CardHeader>
        <CardContent>
          <NotificationSection />
        </CardContent>
      </Card>

      <RuleTestResultPanel result={testResult} />

      {testError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
          {testError}
        </div>
      )}

      <RuleEditorActions
        onSave={handleSave}
        onCancel={handleCancel}
        onTest={handleTest}
        saving={saving}
        testing={testMutation.isPending}
      />

      {(createMutation.isError || updateMutation.isError) && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
          {(createMutation.error || updateMutation.error)?.message}
        </div>
      )}
    </div>
  );
};

export default RuleEditorPage;
