// 모든 화면의 틀: 상단 바 + 가운데 정렬된 한 열 컨테이너 (글은 왼쪽 정렬)
import type { ReactNode } from 'react';
import { TopBar } from './TopBar';

interface PageProps {
  children: ReactNode;
  back?: boolean | (() => void);
  title?: ReactNode;
  /** 이 값이 바뀌면 본문이 다시 부드럽게 나타난다 (한 화면 안의 상태 전환용) */
  animateKey?: string;
}

export function Page({ children, back = true, title, animateKey }: PageProps) {
  return (
    <>
      <TopBar back={back} title={title} />
      <main className="container page">
        <div key={animateKey} className="screen-enter">
          {children}
        </div>
      </main>
    </>
  );
}
