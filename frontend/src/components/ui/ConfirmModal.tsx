import React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ModalHeader, ModalShell, ModalShellSize } from "@/components/ui/Modal";

type ButtonVariant = "default" | "outline" | "ghost" | "destructive";

interface ConfirmModalProps {
  open: boolean;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose?: () => void;
  onCancel?: () => void;
  onConfirm: () => void;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  panelClassName?: string;
  size?: ModalShellSize;
  headerClassName?: string;
  messageClassName?: string;
  actionsClassName?: string;
  closeAriaLabel?: string;
  children?: React.ReactNode;
  cancelText?: React.ReactNode;
  confirmText?: React.ReactNode;
  confirmVariant?: ButtonVariant;
  cancelVariant?: ButtonVariant;
  confirmClassName?: string;
  cancelClassName?: string;
  confirmDisabled?: boolean;
  cancelDisabled?: boolean;
  confirmLoading?: boolean;
  cancelLoading?: boolean;
  showCancel?: boolean;
  confirmChildren?: React.ReactNode;
  cancelChildren?: React.ReactNode;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  open,
  title,
  subtitle,
  onClose,
  onCancel,
  onConfirm,
  closeOnBackdrop = false,
  closeOnEscape = false,
  panelClassName = "",
  size = "md",
  headerClassName,
  messageClassName = "text-sm font-medium text-slate-600",
  actionsClassName = "mt-5 flex justify-end gap-2",
  closeAriaLabel,
  children,
  cancelText,
  confirmText,
  confirmVariant = "destructive",
  cancelVariant = "outline",
  confirmClassName = "",
  cancelClassName = "",
  confirmDisabled = false,
  cancelDisabled = false,
  confirmLoading = false,
  cancelLoading = false,
  showCancel = true,
  confirmChildren,
  cancelChildren,
}) => {
  const handleClose = onClose;
  const handleCancel = onCancel ?? onClose;
  const confirmNode = confirmChildren ?? (
    <>
      {confirmLoading && <Loader2 size={14} className="mr-1.5 animate-spin" />}
      {confirmText}
    </>
  );
  const cancelNode = cancelChildren ?? (
    <>
      {cancelLoading && <Loader2 size={14} className="mr-1.5 animate-spin" />}
      {cancelText ?? "Cancel"}
    </>
  );

  return (
    <ModalShell
      open={open}
      onClose={handleClose}
      closeOnBackdrop={closeOnBackdrop}
      closeOnEscape={closeOnEscape}
      size={size}
      panelClassName={panelClassName}
    >
      <ModalHeader
        title={title}
        subtitle={subtitle}
        onClose={handleClose}
        closeAriaLabel={closeAriaLabel}
        className={headerClassName}
      />
      {children && <div className={messageClassName}>{children}</div>}
      <div className={actionsClassName}>
        {showCancel && (
          <Button
            type="button"
            variant={cancelVariant}
            className={cancelClassName}
            onClick={handleCancel}
            disabled={cancelDisabled}
          >
            {cancelNode}
          </Button>
        )}
        <Button
          type="button"
          variant={confirmVariant}
          className={confirmClassName}
          onClick={onConfirm}
          disabled={confirmDisabled}
        >
          {confirmNode}
        </Button>
      </div>
    </ModalShell>
  );
};
