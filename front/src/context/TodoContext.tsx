// 할 일 목록 (ilgeo.v1.todos)
import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from 'react';
import type { AnalysisResult, TodoItem } from '../api/types';
import { useLocalStorage } from '../hooks/useLocalStorage';
import { STORAGE_KEYS } from '../lib/storage';
import { isTodoItem, removeDone, restoreTodos, todosFromResult } from '../lib/todos';

function parseTodos(raw: unknown): TodoItem[] | undefined {
  return Array.isArray(raw) ? raw.filter(isTodoItem) : undefined;
}

interface TodoValue {
  todos: TodoItem[];
  /** 결과의 할 일을 추가한다. 이미 있는 id 는 무시한다 */
  addFromResult(result: AnalysisResult): void;
  setStatus(id: string, status: TodoItem['status']): void;
  /** 끝낸 일을 지운다. 지운 항목을 돌려준다 (되돌리기용) */
  removeDone(ids: ReadonlyArray<string>): TodoItem[];
  /** 되돌리기: 지운 항목을 다시 넣는다 */
  restore(items: ReadonlyArray<TodoItem>): void;
  clear(): void;
}

const TodoContext = createContext<TodoValue | null>(null);

export function TodoProvider({ children }: { children: ReactNode }) {
  const [todos, setTodos] = useLocalStorage<TodoItem[]>(STORAGE_KEYS.todos, [], parseTodos);

  const addFromResult = useCallback(
    (result: AnalysisResult) =>
      setTodos((list) => {
        const ids = new Set(list.map((t) => t.id));
        const fresh = todosFromResult(result).filter((t) => !ids.has(t.id));
        return fresh.length ? [...list, ...fresh] : list;
      }),
    [setTodos],
  );

  const setStatus = useCallback(
    (id: string, status: TodoItem['status']) =>
      setTodos((list) =>
        list.map((t) => {
          if (t.id !== id) return t;
          if (status === 'done') return { ...t, status, doneAt: new Date().toISOString() };
          const { doneAt: _doneAt, ...rest } = t;
          return { ...rest, status };
        }),
      ),
    [setTodos],
  );

  // 지운 항목(되돌리기용)은 지금 목록에서 고르고, 실제 지우기는 최신 목록 기준으로 한다 (그사이 바뀐 것을 덮어쓰지 않게)
  const latest = useRef(todos);
  latest.current = todos;
  const remove = useCallback(
    (ids: ReadonlyArray<string>) => {
      const { removed } = removeDone(latest.current, ids);
      if (removed.length) setTodos((list) => removeDone(list, ids).kept);
      return removed;
    },
    [setTodos],
  );

  const restore = useCallback((items: ReadonlyArray<TodoItem>) => setTodos((list) => restoreTodos(list, items)), [setTodos]);

  const clear = useCallback(() => setTodos([]), [setTodos]);

  const value = useMemo(
    () => ({ todos, addFromResult, setStatus, removeDone: remove, restore, clear }),
    [todos, addFromResult, setStatus, remove, restore, clear],
  );
  return <TodoContext.Provider value={value}>{children}</TodoContext.Provider>;
}

export function useTodos(): TodoValue {
  const ctx = useContext(TodoContext);
  if (!ctx) throw new Error('TodoProvider 가 필요해요');
  return ctx;
}
