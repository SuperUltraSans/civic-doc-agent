// 화면 전환 시 해당 화면 제목(h1)으로 포커스를 옮긴다 (구현지시서 4.3절).
import { useEffect, useRef } from 'react';

export function usePageHeading<T extends HTMLElement = HTMLHeadingElement>(key?: unknown) {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.focus({ preventScroll: false });
  }, [key]);
  return ref;
}
