/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// 개발 서버는 /api 요청을 백엔드로 넘긴다 (같은 출처라 CORS 설정이 필요 없음).
// Docker Compose 안에서는 API_URL=http://back:8000 이 주입된다.
const apiTarget = process.env.API_URL || 'http://localhost:8000';

// 서브패스 배포(HTTPS 엣지의 /civic-doc-agent/)용. 개발 서버는 기본 '/'.
// 라우터 basename·API 주소는 import.meta.env.BASE_URL 을 따라간다.
const base = process.env.BASE_PATH || '/';

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
