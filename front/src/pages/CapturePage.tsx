// 촬영·확인 (구현지시서 8.3절, 디자인 지시서 6.2절)
import { CameraIcon } from '@phosphor-icons/react';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { BigButton } from '../components/BigButton';
import { Page } from '../components/Page';
import { useCapture } from '../context/CaptureContext';
import { usePageHeading } from '../hooks/usePageHeading';
import { usePhotoPicker } from '../hooks/usePhotoPicker';
import styles from './CapturePage.module.css';

export function CapturePage() {
  const { image, previewUrl, unreadable } = useCapture();
  const navigate = useNavigate();
  const picker = usePhotoPicker({ replace: true });
  const heading = usePageHeading(unreadable);

  // 이미지가 없으면 홈으로
  useEffect(() => {
    if (!image && !unreadable && !picker.busy) navigate('/', { replace: true });
  }, [image, unreadable, picker.busy, navigate]);

  if (unreadable) {
    return (
      <Page back={() => navigate('/', { replace: true })}>
        <h1 ref={heading} tabIndex={-1} className="title">
          이 사진은 열 수 없어요
        </h1>
        <p className={styles.hint}>카메라로 다시 찍어 주세요.</p>
        <div className={`stack ${styles.buttons}`}>
          <BigButton icon={CameraIcon} onClick={picker.openCamera} disabled={picker.busy}>
            {picker.busy ? '사진을 준비하고 있어요' : '다시 찍기'}
          </BigButton>
        </div>
        {picker.inputs}
      </Page>
    );
  }

  return (
    <Page back={() => navigate('/', { replace: true })}>
      <h1 ref={heading} tabIndex={-1} className="title">
        이 사진으로 확인할까요?
      </h1>
      {previewUrl && <img src={previewUrl} alt="찍은 문서 사진" className={styles.preview} />}
      <p className={styles.hint}>종이 전체가 보이고 글씨가 또렷하면 좋아요</p>
      <div className={`stack ${styles.buttons}`}>
        <BigButton onClick={() => navigate('/processing')} disabled={!image || picker.busy}>
          이 사진으로 할게요
        </BigButton>
        <BigButton variant="secondary" icon={CameraIcon} onClick={picker.openCamera} disabled={picker.busy}>
          {picker.busy ? '사진을 준비하고 있어요' : '다시 찍을게요'}
        </BigButton>
      </div>
      {picker.inputs}
    </Page>
  );
}
