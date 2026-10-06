// 읽어주기 / 그만 읽기 (구현지시서 7장). 한국어 음성이 없는 기기에서는 렌더링하지 않는다.
import { SpeakerHighIcon, StopIcon } from '@phosphor-icons/react';
import { useEffect, useRef } from 'react';
import { useSpeech } from '../hooks/useSpeech';
import { BigButton } from './BigButton';

export function SpeakButton({ text, autoStart = false }: { text: string; autoStart?: boolean }) {
  const { supported, speaking, speak, stop } = useSpeech();
  const started = useRef(false);

  // 자동 읽어주기: 기기에 따라 사용자 조작 없이 재생이 막힐 수 있다 → 실패하면 조용히 넘어간다
  useEffect(() => {
    if (autoStart && supported && !started.current) {
      started.current = true;
      speak(text);
    }
  }, [autoStart, supported, speak, text]);

  if (!supported) return null;
  return speaking ? (
    <BigButton variant="secondary" icon={StopIcon} onClick={stop}>
      그만 읽기
    </BigButton>
  ) : (
    <BigButton variant="secondary" icon={SpeakerHighIcon} onClick={() => speak(text)}>
      읽어주기
    </BigButton>
  );
}
