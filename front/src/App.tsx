import { IconContext } from '@phosphor-icons/react';
import { useLayoutEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { ToastProvider } from './components/Toast';
import { CaptureProvider } from './context/CaptureContext';
import { HistoryProvider } from './context/HistoryContext';
import { ProfileProvider } from './context/ProfileContext';
import { SettingsProvider } from './context/SettingsContext';
import { TodoProvider } from './context/TodoContext';
import { ScenarioSwitcher } from './dev/ScenarioSwitcher';
import { StyleguidePage } from './dev/StyleguidePage';
import { devToolsEnabled } from './lib/scenario';
import { CapturePage } from './pages/CapturePage';
import { HomePage } from './pages/HomePage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ProcessingPage } from './pages/ProcessingPage';
import { ResultPage } from './pages/ResultPage';
import { SettingsPage } from './pages/SettingsPage';
import { TodosPage } from './pages/TodosPage';

/** 화면을 넘기면 맨 위부터 보이게 한다 (이전 화면의 스크롤 위치가 남지 않게) */
function ScrollToTop() {
  const { pathname } = useLocation();
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

// 아이콘은 Phosphor Bold 한 세트만 (디자인 지시서 5.8절)
const ICONS = { weight: 'bold', size: '1.25em' } as const;

export function App() {
  return (
    <IconContext.Provider value={ICONS}>
      <SettingsProvider>
        <ProfileProvider>
          <TodoProvider>
            <HistoryProvider>
              <CaptureProvider>
                <ToastProvider>
                  <BrowserRouter basename={import.meta.env.BASE_URL}>
                    <ScrollToTop />
                    <Routes>
                      <Route path="/" element={<HomePage />} />
                      <Route path="/capture" element={<CapturePage />} />
                      <Route path="/processing" element={<ProcessingPage />} />
                      <Route path="/result/:docId" element={<ResultPage />} />
                      <Route path="/todos" element={<TodosPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                      <Route path="/dev/styleguide" element={devToolsEnabled() ? <StyleguidePage /> : <Navigate to="/" replace />} />
                      <Route path="*" element={<NotFoundPage />} />
                    </Routes>
                    <ScenarioSwitcher />
                  </BrowserRouter>
                </ToastProvider>
              </CaptureProvider>
            </HistoryProvider>
          </TodoProvider>
        </ProfileProvider>
      </SettingsProvider>
    </IconContext.Provider>
  );
}
