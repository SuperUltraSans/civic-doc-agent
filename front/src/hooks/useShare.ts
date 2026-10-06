// 가족에게 보내기 (구현지시서 9.4절).
// navigator.share 가 있으면 쓰고(카카오톡 등 선택), 없으면 클립보드에 복사한다.
import { useCallback } from 'react';
import { useToast } from '../components/Toast';

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 아래 방식으로 다시 시도
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

export function useShare() {
  const toast = useToast();
  return useCallback(
    async (title: string, text: string) => {
      if (typeof navigator.share === 'function') {
        try {
          await navigator.share({ title, text });
          return;
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') return; // 사용자가 닫음
          // 그 밖의 실패는 복사로 대신한다
        }
      }
      if (await copyText(text)) toast.show('복사했어요. 카카오톡에 붙여 넣어 보내세요');
      else toast.show('복사하지 못했어요. 화면을 가족에게 보여 주세요');
    },
    [toast],
  );
}
