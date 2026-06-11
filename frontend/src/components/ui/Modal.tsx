// 中文注释：提供 Modal 通用 UI 组件。

import React from "react";
import { X } from "lucide-react";

export type ModalShellSize = "auto" | "sm" | "md" | "lg" | "drawer-right";

interface ModalShellProps {
  children: React.ReactNode;
  onClose?: () => void;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  open?: boolean;
  backdropClassName?: string;
  shellClassName?: string;
  panelClassName?: string;
  size?: ModalShellSize;
}

const mergeClassName = (...classes: Array<string | undefined | null | false>) => {
  return classes.filter(Boolean).join(" ").trim();
};

const MODAL_SHELL_PANEL_PRESETS: Record<Exclude<ModalShellSize, "auto">, string> = {
  sm: "w-full max-w-md rounded-lg bg-white p-5 shadow-xl",
  md: "w-full max-w-2xl rounded-lg bg-white p-5 shadow-xl",
  lg: "w-full max-w-3xl rounded-lg bg-white p-5 shadow-xl",
  "drawer-right": "h-full w-full max-w-md bg-white shadow-xl flex flex-col rounded-lg",
};

const MODAL_SHELL_SHELL_PRESETS: Record<Exclude<ModalShellSize, "auto" | "sm" | "md" | "lg">, string> = {
  "drawer-right": "!justify-end !items-stretch !px-0",
};

export const ModalShell: React.FC<ModalShellProps> = ({
  children,
  onClose,
  closeOnBackdrop = false,
  closeOnEscape = false,
  open = true,
  backdropClassName = "",
  shellClassName = "",
  panelClassName = "",
  size = "auto",
}) => {
  const sizePanelClassName = size === "auto" ? "" : MODAL_SHELL_PANEL_PRESETS[size];
  const sizeShellClassName = size === "drawer-right" ? MODAL_SHELL_SHELL_PRESETS["drawer-right"] : "";
  React.useEffect(() => {
    if (!open || !closeOnEscape || !onClose) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closeOnEscape, onClose, open]);

  if (!open) return null;

  return (
    <div
      className={mergeClassName(
        "fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4",
        sizeShellClassName,
        backdropClassName,
        shellClassName,
      )}
      onMouseDown={(event) => {
        if (!closeOnBackdrop || !onClose) return;
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className={mergeClassName(sizePanelClassName, panelClassName)}
        onMouseDown={(event) => {
          event.stopPropagation();
        }}
      >
        {children}
      </div>
    </div>
  );
};

interface ModalHeaderProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose?: () => void;
  closeAriaLabel?: string;
  actions?: React.ReactNode;
  className?: string;
}

export const ModalHeader: React.FC<ModalHeaderProps> = ({
  title,
  subtitle,
  onClose,
  closeAriaLabel = "Close",
  actions,
  className = "",
}) => {
  return (
    <div className={`mb-4 flex items-start justify-between gap-4 ${className}`}>
      <div>
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="inline-flex items-center gap-2 shrink-0">
        {actions}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label={closeAriaLabel}
          >
            <X size={18} />
          </button>
        )}
      </div>
    </div>
  );
};
