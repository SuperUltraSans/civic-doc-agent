// 확인 대화상자 — "모든 기록 지우기"에만 쓴다 (구현지시서 8.7절)
import { useEffect, useRef } from 'react';
import { BigButton } from './BigButton';
import styles from './ConfirmDialog.module.css';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm(): void;
  onCancel(): void;
}

export function ConfirmDialog({ open, title, message, confirmLabel, cancelLabel = '그만둘게요', onConfirm, onCancel }: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
    >
      <h2 id="confirm-title" className={styles.title}>
        {title}
      </h2>
      <p className={styles.message}>{message}</p>
      <div className={styles.buttons}>
        <BigButton variant="primary" onClick={onConfirm}>
          {confirmLabel}
        </BigButton>
        <BigButton variant="secondary" onClick={onCancel}>
          {cancelLabel}
        </BigButton>
      </div>
    </dialog>
  );
}
