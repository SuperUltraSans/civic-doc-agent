// 읽어주기 (구현지시서 9.3절). ko-KR, 속도 0.9.
// 한국어 음성이 없거나 API가 없으면 supported=false — 관련 버튼·설정을 숨긴다.
import { useCallback, useEffect, useState } from 'react';

function hasApi(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined';
}

function koreanVoice(): SpeechSynthesisVoice | undefined {
  return window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().replace('_', '-').startsWith('ko'));
}

/** 한국어 음성이 있는지 (음성 목록은 늦게 채워질 수 있어 voiceschanged 를 기다린다) */
export function useSpeechSupported(): boolean {
  const [supported, setSupported] = useState(() => hasApi() && Boolean(koreanVoice()));
  useEffect(() => {
    if (!hasApi()) return;
    const check = () => setSupported(Boolean(koreanVoice()));
    check();
    window.speechSynthesis.addEventListener('voiceschanged', check);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', check);
  }, []);
  return supported;
}

export function useSpeech() {
  const supported = useSpeechSupported();
  const [speaking, setSpeaking] = useState(false);

  const stop = useCallback(() => {
    if (!hasApi()) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string) => {
      if (!hasApi() || !text.trim()) return;
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'ko-KR';
        utterance.rate = 0.9;
        const voice = koreanVoice();
        if (voice) utterance.voice = voice;
        utterance.onend = () => setSpeaking(false);
        utterance.onerror = () => setSpeaking(false); // 자동 재생이 막혀도 조용히 넘어간다
        setSpeaking(true);
        window.speechSynthesis.speak(utterance);
      } catch {
        setSpeaking(false);
      }
    },
    [],
  );

  // 화면 이동·언마운트 시 멈춘다
  useEffect(() => () => {
    if (hasApi()) window.speechSynthesis.cancel();
  }, []);

  return { supported, speaking, speak, stop };
}
