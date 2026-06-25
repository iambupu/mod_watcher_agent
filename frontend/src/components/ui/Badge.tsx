// 中文注释：提供 Badge 通用 UI 组件。

import React from "react";

interface BadgeProps {
  variant?: "default" | "success" | "warning" | "danger" | "info";
  className?: string;
  children: React.ReactNode;
}

const variantClasses: Record<string, string> = {
  default: "bg-slate-100 text-slate-800",
  success: "bg-sky-100 text-sky-800",
  warning: "bg-yellow-100 text-yellow-800",
  danger: "bg-red-100 text-red-800",
  info: "bg-cyan-100 text-cyan-800",
};

export const Badge: React.FC<BadgeProps> = ({ variant = "default", className = "", children }) => {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${variantClasses[variant]} ${className}`}>
      {children}
    </span>
  );
};
