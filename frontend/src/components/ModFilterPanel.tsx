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
}) => {
  return (
    <Panel as="section" padding="lg" className={`mb-6 ${className}`.trim()}>
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
        containerClassName="mb-4 block"
      />

      <div className="flex flex-wrap items-end gap-3">
        {fields.map((field) => (
          <FilterSelect
            key={field.key}
            label={field.label}
            value={field.value}
            onValueChange={field.onChange}
            icon={field.icon}
            containerClassName={field.className}
          >
            {field.children}
          </FilterSelect>
        ))}
      </div>
    </Panel>
  );
};

export default ModFilterPanel;
