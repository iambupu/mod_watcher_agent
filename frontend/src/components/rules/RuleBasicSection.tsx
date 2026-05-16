import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

export const RuleBasicSection: React.FC = () => {
  const { t } = useTranslation();
  const name = useRuleEditorStore((s) => s.draft.name);
  const enabled = useRuleEditorStore((s) => s.draft.enabled);
  const intervalMinutes = useRuleEditorStore((s) => s.draft.intervalMinutes);
  const setBasicInfo = useRuleEditorStore((s) => s.setBasicInfo);

  const [touched, setTouched] = useState(false);
  const nameError = touched && !name.trim() ? t("rules.validation.nameRequired") : undefined;

  return (
    <div className="flex flex-col gap-3">
      <Input
        label={t("rules.basic.nameLabel")}
        value={name}
        onChange={(e) => {
          setBasicInfo({ name: e.target.value });
          if (!touched) setTouched(true);
        }}
        onBlur={() => setTouched(true)}
        error={nameError}
        placeholder={t("rules.name")}
      />
      <Switch
        checked={enabled}
        onCheckedChange={(checked) => setBasicInfo({ enabled: checked })}
        label={t("rules.basic.enabledLabel")}
      />
      <Input
        label={t("rules.basic.intervalMinutesLabel")}
        type="number"
        min={1}
        max={1440}
        value={intervalMinutes}
        onChange={(e) => {
          const raw = e.target.value.trim();
          if (!raw) {
            setBasicInfo({ intervalMinutes: 360 });
            return;
          }
          const parsed = Number(raw);
          if (!Number.isFinite(parsed) || parsed < 1) {
            setBasicInfo({ intervalMinutes: 360 });
            return;
          }
          setBasicInfo({ intervalMinutes: Math.min(1440, Math.floor(parsed)) });
        }}
      />
    </div>
  );
};
