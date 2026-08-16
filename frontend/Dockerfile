# 프론트엔드(Next.js) 배포 이미지.
#
# Railway 서비스의 루트 디렉터리를 `frontend`로 잡고 이 파일을 쓴다.
#
# **빌드 단계와 실행 단계를 나눈다.** 빌드에는 개발 의존성(타입스크립트·vitest)이
# 필요하지만 실행에는 없어도 된다. 실행 이미지에 개발 도구를 넣으면 배포물에
# 쓰지 않는 코드가 따라간다.

# --- 빌드 ---
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# **rewrites는 빌드 시점에 구워진다.** next.config.mjs의 destination이
# `.next/routes-manifest.json`에 문자열로 박히므로, 실행할 때 환경변수를 넣어도
# 이미 늦다. 실제로 넣어봤더니 `localhost:8000`으로 굳어 프록시가 502를 냈다.
# 그래서 빌드 인자로 받는다 — Railway는 서비스 변수를 빌드 인자로도 넘겨준다.
ARG PMS_BACKEND_ORIGIN=http://localhost:8000
ENV PMS_BACKEND_ORIGIN=$PMS_BACKEND_ORIGIN
RUN npm run build

# --- 실행 ---
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

# public/ 은 이 프로젝트에 없다. 생기면 여기 한 줄 추가한다.
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./next.config.mjs

# 루트로 돌리지 않는다.
USER node

EXPOSE 3000

# Next는 PORT 환경변수를 따른다. Railway가 이 값을 넣어준다.
CMD ["npm", "run", "start"]
