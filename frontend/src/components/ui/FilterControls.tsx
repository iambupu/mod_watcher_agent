// 中文注释：提供 FilterControls 通用 UI 组件。

import React from "react";
import { ChevronRight, X } from "lucide-react";

type ControlSize = "sm" | "md";

type ControlSizeOption = {
  sm: string;
  md: string;
};

const selectBaseClasses: ControlSizeOption = {
  sm: "h-10 w-full appearance-none rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700",
  md: "h-11 w-full appearance-none rounded-lg border border-slate-200 bg-white py-2 text-sm font-semibold text-slate-700 shadow-sm",
};

const inputBaseClasses: ControlSizeOption = {
  sm: "h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700",
  md: "h-11 w-full rounded-lg border border-slate-200 bg-white py-2 text-sm font-semibold text-slate-700 shadow-sm",
};

const inlineSelectContainerClass =
  "inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-1 shadow-sm";
const inlineSelectFieldClass = "h-8 rounded-md border border-slate-200 bg-white px-2 text-sm font-semibold text-slate-700";
const focusClass = "focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100";

const mergeClasses = (...classes: Array<string | false | null | undefined>) =>
  classes.filter(Boolean).join(" ");

interface FilterInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  label?: React.ReactNode;
  value: string;
  onValueChange: (value: string) => void;
  icon?: React.ReactNode;
  clearable?: boolean;
  onClear?: () => void;
  clearAriaLabel?: string;
  containerClassName?: string;
  labelClassName?: string;
  fieldClassName?: string;
  controlSize?: ControlSize;
}

export const FilterInput: React.FC<FilterInputProps> = ({
  label,
  value,
  onValueChange,
  icon,
  clearable = false,
  onClear,
  clearAriaLabel,
  containerClassName = "",
  labelClassName = "mb-1.5 block text-xs font-semibold text-slate-500",
  fieldClassName = "",
  controlSize = "md",
  className = "",
  ...props
}) => {
  const canClear = Boolean(clearable && onClear && value.length > 0);

  return (
    <label className={`block min-w-0 ${containerClassName}`}>
      {label && <span className={labelClassName}>{label}</span>}
      <span className="relative block">
        {icon && (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">
            {icon}
          </span>
        )}
        <input
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          className={mergeClasses(
            inputBaseClasses[controlSize],
            icon ? "pl-10" : "",
            canClear ? "pr-10" : "",
            "outline-none transition",
            focusClass,
            fieldClassName,
            className,
          )}
          {...props}
        />
        {canClear && (
          <button
            type="button"
            onClick={onClear}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            aria-label={clearAriaLabel}
          >
            <X size={14} strokeWidth={2.4} />
          </button>
        )}
      </span>
    </label>
  );
};

interface FilterSelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value" | "children"> {
  label?: React.ReactNode;
  value: string;
  onValueChange: (value: string) => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
  containerClassName?: string;
  labelClassName?: string;
  fieldClassName?: string;
  controlSize?: ControlSize;
  inlineLabel?: React.ReactNode;
  inlineClassName?: string;
}

export const FilterSelect: React.FC<FilterSelectProps> = ({
  label,
  value,
  onValueChange,
  icon,
  children,
  containerClassName = "",
  labelClassName = "mb-1.5 block text-xs font-semibold text-slate-500",
  fieldClassName = "",
  controlSize = "md",
  className = "",
  inlineLabel,
  inlineClassName = inlineSelectContainerClass,
  ...props
}) => {
  const useInline = inlineLabel !== undefined;

  if (useInline) {
    return (
      <label className={mergeClasses(inlineClassName, containerClassName)}>
        {inlineLabel ? <span className="text-sm font-semibold text-slate-600">{inlineLabel}</span> : null}
        <select
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          className={mergeClasses(
            "h-8 rounded-md",
            "outline-none transition",
            "focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100",
            inlineSelectFieldClass,
            fieldClassName,
            className,
          )}
          {...props}
        >
          {children}
        </select>
      </label>
    );
  }

  return (
    <label className={`block min-w-0 ${containerClassName}`}>
      {label && <span className={labelClassName}>{label}</span>}
      <span className="relative block">
        {icon && (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">
            {icon}
          </span>
        )}
        <select
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          className={mergeClasses(
            selectBaseClasses[controlSize],
            icon ? "pl-10 pr-9" : "",
            "outline-none transition",
            focusClass,
            fieldClassName,
            className,
          )}
          {...props}
        >
          {children}
        </select>
        {icon && (
          <ChevronRight
            size={15}
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rotate-90 text-slate-400"
          />
        )}
      </span>
    </label>
  );
};

interface SegmentedButtonItem {
  key: string;
  label: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  className?: string;
}

interface FilterButtonGroupProps {
  items: SegmentedButtonItem[];
  containerClassName?: string;
  baseButtonClassName?: string;
  activeClassName?: string;
  inactiveClassName?: string;
  disabledClassName?: string;
}

const defaultContainerClassName = "inline-flex";
const defaultBaseButtonClassName = "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-semibold transition";
const defaultActiveClassName = "bg-blue-600 text-white shadow-sm";
const defaultInactiveClassName = "text-slate-600 hover:bg-slate-50";
const defaultDisabledClassName = "opacity-50 cursor-not-allowed";
const filterBarButtonBaseClass =
  "inline-flex items-center rounded-lg border border-slate-200 bg-white px-4 shadow-sm text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2";

export const FilterButtonGroup: React.FC<FilterButtonGroupProps> = ({
  items,
  containerClassName = defaultContainerClassName,
  baseButtonClassName = defaultBaseButtonClassName,
  activeClassName = defaultActiveClassName,
  inactiveClassName = defaultInactiveClassName,
  disabledClassName = defaultDisabledClassName,
}) => {
  return (
    <div className={containerClassName}>
      {items.map((item) => {
        const classes = [
          baseButtonClassName,
          item.active ? activeClassName : inactiveClassName,
          item.disabled ? disabledClassName : "",
          item.className,
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <button
            key={item.key}
            type="button"
            className={classes}
            onClick={item.onClick}
            disabled={item.disabled}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
};

interface FilterBarButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  height?: "h11" | "h12";
}

export const FilterBarButton: React.FC<FilterBarButtonProps> = ({
  height = "h11",
  className = "",
  children,
  ...props
}) => {
  const sizeClass = height === "h12" ? "h-12 px-5" : "h-11 px-4";

  return (
    <button
      className={mergeClasses(
        filterBarButtonBaseClass,
        sizeClass,
        "rounded-lg text-sm font-semibold",
        className,
      )}
      type="button"
      {...props}
    >
      {children}
    </button>
  );
};
