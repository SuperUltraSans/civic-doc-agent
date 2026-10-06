# 읽어드림 프론트 — Vite 개발 서버 (컨테이너 안에서 0.0.0.0:3000).
# /api 요청은 vite.config.ts 의 프록시가 API_URL(기본 http://back:8000)로 넘긴다.
FROM node:22-alpine

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 활용)
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

# 개발 서버는 반드시 0.0.0.0 으로 열어야 컨테이너 밖에서 접속할 수 있다
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000", "--strictPort"]
