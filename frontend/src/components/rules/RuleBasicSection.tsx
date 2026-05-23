import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

export const RuleBasicSection: React.FC = () => {
  const { t } = useTranslation();
  const name = useRuleEditorStore((s) => s.draft.name);
  const intervalMinutes = useRuleEditorStore((s) => s.draft.intervalMinutes);
  const setBasicInfo = useRuleEditorStore((s) => s.setBasicInfo);

  const [touched, setTouched] = useState(false);
  const [intervalText, setIntervalText] = useState(String(intervalMinutes));
  const nameError = touched && !name.trim() ? t("rules.validation.nameRequired") : undefined;

  useEffect(() => {
    setIntervalText(String(intervalMinutes));
  }, [intervalMinutes]);

  return (
    <div className="grid gap-5 lg:grid-cols-2">
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
        className="h-10 rounded-lg border-slate-300"
      />
      <Input
        label={t("rules.basic.intervalMinutesLabel")}
        type="number"
        min={1}
        max={1440}
        value={intervalText}
        onChange={(e) => {
          const raw = e.target.value.trim();
          setIntervalText(raw);
          if (!raw) {
            return;
          }
          const parsed = Number(raw);
          if (!Number.isFinite(parsed) || parsed < 1) {
            return;
          }
          setBasicInfo({ intervalMinutes: Math.min(1440, Math.floor(parsed)) });
        }}
        onBlur={() => {
          const parsed = Number(intervalText);
          if (!Number.isFinite(parsed) || parsed < 1) {
            setIntervalText(String(intervalMinutes));
          }
        }}
        className="h-10 rounded-lg border-slate-300"
      />
      <p className="lg:col-start-2 self-start text-xs font-semibold text-slate-400">{t("rules.basic.intervalHint")}</p>
    </div>
  );
};
