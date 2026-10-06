// 짧은 알림 (구현지시서 7장, 디자인 지시서 5.7절). 3초 후 사라짐, role="status".
// "되돌리기"가 있으면 5초 동안 보여 준다. 튀어 오르지 않고 0.15초 페이드로만 나타난다.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import styles from './Toast.module.css';

interface ToastOptions {
  actionLabel?: string;
  onAction?: () => void;
  durationMs?: number;
}

interface ToastState extends ToastOptions {
  id: number;
  message: string;
}

interface ToastValue {
  show(message: string, options?: ToastOptions): void;
  hide(): void;
}

const ToastContext = createContext<ToastValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const seq = useRef(0);

  const hide = useCallback(() => {
    window.clearTimeout(timer.current);
    setToast(null);
  }, []);

  const show = useCallback(
    (message: string, options: ToastOptions = {}) => {
      window.clearTimeout(timer.current);
      seq.current += 1;
      setToast({ id: seq.current, message, ...options });
      const duration = options.durationMs ?? (options.onAction ? 5000 : 3000);
      timer.current = window.setTimeout(() => setToast(null), duration);
    },
    [],
  );

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const value = useMemo(() => ({ show, hide }), [show, hide]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* 알림 영역은 항상 두어 화면 읽기 도구가 바뀐 내용을 읽게 한다 */}
      <div className={styles.region} role="status" aria-live="polite">
        {toast && (
          <div key={toast.id} className={styles.toast}>
            <span className={styles.message}>{toast.message}</span>
            {toast.onAction && (
              <button
                type="button"
                className={styles.action}
                onClick={() => {
                  toast.onAction?.();
                  hide();
                }}
              >
                {toast.actionLabel ?? '되돌리기'}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('ToastProvider 가 필요해요');
  return ctx;
}
