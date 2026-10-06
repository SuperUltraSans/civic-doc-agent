// 결과 기록 (ilgeo.v1.history) — 새로고침 시 결과 화면을 다시 불러오는 데 쓴다.
// 연락처·주소를 지운 StoredResult 만 저장한다 (lib/history.ts).
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';
import type { AnalysisResult, Explanation } from '../api/types';
import { useLocalStorage } from '../hooks/useLocalStorage';
import { isStoredResult, toStoredResult, trimHistory, type StoredResult } from '../lib/history';
import { STORAGE_KEYS } from '../lib/storage';

type History = Record<string, StoredResult>;

function parseHistory(raw: unknown): History | undefined {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return undefined;
  return Object.fromEntries(Object.entries(raw).filter(([, v]) => isStoredResult(v))) as History;
}

interface HistoryValue {
  get(docId: string): StoredResult | undefined;
  save(result: AnalysisResult): void;
  updateExplanation(docId: string, explanation: Explanation): void;
  clear(): void;
}

const HistoryContext = createContext<HistoryValue | null>(null);

export function HistoryProvider({ children }: { children: ReactNode }) {
  const [history, setHistory] = useLocalStorage<History>(STORAGE_KEYS.history, {}, parseHistory);

  const get = useCallback((docId: string) => history[docId], [history]);
  const save = useCallback(
    (result: AnalysisResult) => setHistory((h) => trimHistory({ ...h, [result.docId]: toStoredResult(result) })),
    [setHistory],
  );
  const updateExplanation = useCallback(
    (docId: string, explanation: Explanation) =>
      setHistory((h) => (h[docId] ? { ...h, [docId]: { ...h[docId], explanation } } : h)),
    [setHistory],
  );
  const clear = useCallback(() => setHistory({}), [setHistory]);

  const value = useMemo(() => ({ get, save, updateExplanation, clear }), [get, save, updateExplanation, clear]);
  return <HistoryContext.Provider value={value}>{children}</HistoryContext.Provider>;
}

export function useHistory(): HistoryValue {
  const ctx = useContext(HistoryContext);
  if (!ctx) throw new Error('HistoryProvider 가 필요해요');
  return ctx;
}
