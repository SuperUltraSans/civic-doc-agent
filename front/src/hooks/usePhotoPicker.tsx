// 사진 찍기·사진첩 고르기. 숨겨진 <input type="file"> 를 버튼 클릭 이벤트 안에서 직접 연다
// (브라우저는 사용자 조작 없이 파일 선택 창을 열지 않는다, 구현지시서 8.2절).
import { useCallback, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCapture } from '../context/CaptureContext';
import { resizeImage } from '../lib/image';

interface PhotoPicker {
  openCamera(): void;
  openGallery(): void;
  busy: boolean;
  /** 화면 어딘가에 렌더링해야 하는 숨겨진 입력 */
  inputs: ReactNode;
}

export function usePhotoPicker(options: { replace?: boolean } = {}): PhotoPicker {
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const capture = useCapture();
  const navigate = useNavigate();

  const onChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = ''; // 같은 사진을 다시 골라도 change 가 오도록
      if (!file) return;
      setBusy(true);
      try {
        capture.setImage(await resizeImage(file));
      } catch {
        capture.setUnreadable();
      } finally {
        setBusy(false);
      }
      navigate('/capture', { replace: options.replace });
    },
    [capture, navigate, options.replace],
  );

  const inputs = (
    <>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={onChange} />
      <input ref={gallery} type="file" accept="image/*" hidden onChange={onChange} />
    </>
  );

  return {
    openCamera: () => camera.current?.click(),
    openGallery: () => gallery.current?.click(),
    busy,
    inputs,
  };
}
