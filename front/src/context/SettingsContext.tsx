// 글씨 크기, 자동 읽어주기 (ilgeo.v1.settings)
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, type ReactNode } from 'react';
import { useLocalStorage } from '../hooks/useLocalStorage';
import { STORAGE_KEYS } from '../lib/storage';

export type FontScale = 1 | 2 | 3;

export interface Settings {
  fontScale: FontScale;
  autoSpeak: boolean;
}

/** 글씨 크기 3단계 = 루트 font-size (구현지시서 4.1절) */
export const FONT_SCALES: ReadonlyArray<{ value: FontScale; label: string; px: number }> = [
  { value: 1, label: '보통', px: 18 },
  { value: 2, label: '크게', px: 21 },
  { value: 3, label: '아주 크게', px: 24 },
];

const DEFAULT_SETTINGS: Settings = { fontScale: 1, autoSpeak: false };

function parseSettings(raw: unknown): Settings | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined;
  const r = raw as Partial<Settings>;
  return {
    fontScale: r.fontScale === 2 || r.fontScale === 3 ? r.fontScale : 1,
    autoSpeak: r.autoSpeak === true,
  };
}

interface SettingsValue extends Settings {
  fontLabel: string;
  setFontScale(scale: FontScale): void;
  cycleFontScale(): void;
  setAutoSpeak(on: boolean): void;
}

const SettingsContext = createContext<SettingsValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useLocalStorage(STORAGE_KEYS.settings, DEFAULT_SETTINGS, parseSettings);

  useLayoutEffect(() => {
    const scale = FONT_SCALES.find((s) => s.value === settings.fontScale) ?? FONT_SCALES[0];
    document.documentElement.style.fontSize = `${scale.px}px`;
  }, [settings.fontScale]);

  const setFontScale = useCallback((fontScale: FontScale) => setSettings((s) => ({ ...s, fontScale })), [setSettings]);
  const cycleFontScale = useCallback(
    () => setSettings((s) => ({ ...s, fontScale: s.fontScale === 3 ? 1 : ((s.fontScale + 1) as FontScale) })),
    [setSettings],
  );
  const setAutoSpeak = useCallback((autoSpeak: boolean) => setSettings((s) => ({ ...s, autoSpeak })), [setSettings]);

  const value = useMemo<SettingsValue>(
    () => ({
      ...settings,
      fontLabel: FONT_SCALES.find((s) => s.value === settings.fontScale)?.label ?? '보통',
      setFontScale,
      cycleFontScale,
      setAutoSpeak,
    }),
    [settings, setFontScale, cycleFontScale, setAutoSpeak],
  );
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): SettingsValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('SettingsProvider 가 필요해요');
  return ctx;
}
