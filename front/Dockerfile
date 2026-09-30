FROM node:22-alpine

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 활용). package.json 이 생기면 자동 설치됨
COPY package*.jso[n] ./
RUN if [ -f package.json ]; then npm install; fi

COPY . .

EXPOSE 3000

# TODO: 프레임워크 확정 후 교체 (개발 서버는 반드시 0.0.0.0 으로 열어야 외부 접속 가능)
#   Vite 예:    CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
#   Next.js 예: CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]
CMD ["node", "-e", "require('http').createServer((q,s)=>s.end('front placeholder')).listen(3000)"]
