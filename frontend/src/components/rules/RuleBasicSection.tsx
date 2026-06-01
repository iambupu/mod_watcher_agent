import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { MAX_RULE_INTERVAL_MINUTES, MIN_RULE_INTERVAL_MINUTES } from "@/constants/rules";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import { parseIntegerInput } from "@/utils/numberInput";

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
        min={MIN_RULE_INTERVAL_MINUTES}
        max={MAX_RULE_INTERVAL_MINUTES}
        value={intervalText}
        onChange={(e) => {
          const raw = e.target.value.trim();
          setIntervalText(raw);
          if (!raw) {
            return;
          }
          const parsed = parseIntegerInput(raw, { min: MIN_RULE_INTERVAL_MINUTES, max: MAX_RULE_INTERVAL_MINUTES });
          if (parsed == null) {
            return;
          }
          setBasicInfo({ intervalMinutes: parsed });
        }}
        onBlur={() => {
          const parsed = parseIntegerInput(intervalText, {
            min: MIN_RULE_INTERVAL_MINUTES,
            max: MAX_RULE_INTERVAL_MINUTES,
          });
          if (parsed == null) {
            setIntervalText(String(intervalMinutes));
          } else {
            setIntervalText(String(parsed));
          }
        }}
        className="h-10 rounded-lg border-slate-300"
      />
      <p className="lg:col-start-2 self-start text-xs font-semibold text-slate-400">{t("rules.basic.intervalHint")}</p>
    </div>
  );
};
