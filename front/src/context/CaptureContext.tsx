// 촬영 이미지 (메모리 전용). URL·localStorage·sessionStorage 어디에도 넣지 않는다.
// 새로고침으로 사라지는 것이 의도된 동작이다 (이미지 비저장 원칙, 구현지시서 3장).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

interface CaptureValue {
  image: Blob | null;
  previewUrl: string | null;
  /** 이미지를 읽을 수 없었음 (HEIC 등) */
  unreadable: boolean;
  setImage(image: Blob): void;
  setUnreadable(): void;
  clear(): void;
}

const CaptureContext = createContext<CaptureValue | null>(null);

export function CaptureProvider({ children }: { children: ReactNode }) {
  const [image, setImageState] = useState<Blob | null>(null);
  const [unreadable, setUnreadableState] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!image) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(image);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  const setImage = useCallback((next: Blob) => {
    setUnreadableState(false);
    setImageState(next);
  }, []);
  const setUnreadable = useCallback(() => {
    setImageState(null);
    setUnreadableState(true);
  }, []);
  const clear = useCallback(() => {
    setImageState(null);
    setUnreadableState(false);
  }, []);

  const value = useMemo(
    () => ({ image, previewUrl, unreadable, setImage, setUnreadable, clear }),
    [image, previewUrl, unreadable, setImage, setUnreadable, clear],
  );
  return <CaptureContext.Provider value={value}>{children}</CaptureContext.Provider>;
}

export function useCapture(): CaptureValue {
  const ctx = useContext(CaptureContext);
  if (!ctx) throw new Error('CaptureProvider 가 필요해요');
  return ctx;
}
