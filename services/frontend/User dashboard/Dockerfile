FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

# API 주소는 런타임에 접속 호스트를 따라가므로 더는 빌드 타임에 박지 않는다.
# (프론트/백엔드가 다른 호스트에 뜨는 환경에서만 VITE_API_BASE_URL을 넘기면 된다.)
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# 구글 OAuth 시작 호스트만 콜백과 맞추기 위해 고정으로 주입한다 (#123).
ARG VITE_OAUTH_BASE_URL
ENV VITE_OAUTH_BASE_URL=$VITE_OAUTH_BASE_URL

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80