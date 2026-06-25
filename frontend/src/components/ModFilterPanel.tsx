// 中文注释：提供 ModFilterPanel 业务组件。

import React from "react";
import { Search } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { FilterInput, FilterSelect } from "@/components/ui/FilterControls";

type ModFilterField = {
  key: string;
  label: string;
  value: string;
  icon: React.ReactNode;
  className?: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
};

interface ModFilterPanelProps {
  searchValue: string;
  searchLabel: string;
  searchPlaceholder: string;
  closeAriaLabel: string;
  onSearchChange: (value: string) => void;
  onSearchClear: () => void;
  fields: ModFilterField[];
  className?: string;
  compact?: boolean;
}

export const ModFilterPanel: React.FC<ModFilterPanelProps> = ({
  searchValue,
  searchLabel,
  searchPlaceholder,
  closeAriaLabel,
  onSearchChange,
  onSearchClear,
  fields,
  className = "",
  compact = false,
}) => {
  const labelClassName = compact
    ? "mb-1 block text-[11px] font-semibold text-slate-500"
    : "mb-1.5 block text-xs font-semibold text-slate-500";
  const fieldClassName = compact
    ? "border-slate-200 bg-slate-50 text-slate-800 shadow-none placeholder:text-slate-400 focus:border-sky-500 focus:ring-sky-100"
    : "";

  return (
    <Panel
      as="section"
      padding={compact ? "md" : "lg"}
      className={`mb-6 ${className}`.trim()}
    >
      <FilterInput
        className="placeholder:text-slate-400"
        label={searchLabel}
        value={searchValue}
        onValueChange={onSearchChange}
        icon={<Search size={18} className="text-slate-500" />}
        clearable
        onClear={onSearchClear}
        clearAriaLabel={closeAriaLabel}
        placeholder={searchPlaceholder}
        containerClassName={compact ? "mb-3 block" : "mb-4 block"}
        labelClassName={labelClassName}
        fieldClassName={fieldClassName}
        controlSize={compact ? "sm" : "md"}
      />

      <div className={compact ? "flex flex-wrap items-end gap-2.5" : "flex flex-wrap items-end gap-3"}>
        {fields.map((field) => (
          <FilterSelect
            key={field.key}
            label={field.label}
            value={field.value}
            onValueChange={field.onChange}
            icon={field.icon}
            containerClassName={field.className}
            labelClassName={labelClassName}
            fieldClassName={fieldClassName}
            controlSize={compact ? "sm" : "md"}
          >
            {field.children}
          </FilterSelect>
        ))}
      </div>
    </Panel>
  );
};

export default ModFilterPanel;
