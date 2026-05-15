import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

interface RuleEditorActionsProps {
  onSave: () => void;
  onTest: () => void;
  onCancel: () => void;
  saving?: boolean;
  testing?: boolean;
}

export const RuleEditorActions: React.FC<RuleEditorActionsProps> = ({
  onSave,
  onTest,
  onCancel,
  saving = false,
  testing = false,
}) => {
  const { t } = useTranslation();
  const isDirty = useRuleEditorStore((s) => s.isDirty);
  const name = useRuleEditorStore((s) => s.draft.name);

  const saveDisabled = !isDirty || !name.trim() || saving;

  return (
    <div className="flex items-center gap-3 pt-4 border-t border-gray-200">
      <Button onClick={onSave} disabled={saveDisabled}>
        {t("rules.actions.saveRule")}
      </Button>
      <Button variant="outline" onClick={onTest} disabled={testing}>
        {t("rules.actions.testRule")}
      </Button>
      <Button variant="ghost" onClick={onCancel}>
        {t("common.cancel")}
      </Button>
    </div>
  );
};
