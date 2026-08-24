# =============================================================================
# apps/frontend/Dockerfile — 뼈대 (skeleton)
# TODO: 프로덕션용 멀티스테이지 빌드 (deps → build → standalone runtime)로 전환
# =============================================================================

FROM node:20-slim

WORKDIR /app

COPY package.json .
RUN npm install

COPY . .

EXPOSE 3000

# TODO: 프로덕션에서는 `npm run build && npm run start` 로 전환
CMD ["npm", "run", "dev"]
