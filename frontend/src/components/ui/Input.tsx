// 中文注释：提供 Input 通用 UI 组件。

import React from "react";
import { HelpButton } from "@/components/HelpButton";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  help?: {
    titleKey: string;
    stepsKey: string;
    stepCount: number;
  };
}

export const Input: React.FC<InputProps> = ({ label, error, className = "", id, help, ...props }) => {
  const inputId = id || label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <div className="flex items-center gap-1">
          <label htmlFor={inputId} className="text-sm font-medium text-gray-700">
            {label}
          </label>
          {help && <HelpButton titleKey={help.titleKey} stepsKey={help.stepsKey} stepCount={help.stepCount} />}
        </div>
      )}
      <input
        id={inputId}
        className={`rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-500 ${error ? "border-red-500 focus:border-red-500 focus:ring-red-500" : ""} ${className}`}
        {...props}
      />
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  );
};
