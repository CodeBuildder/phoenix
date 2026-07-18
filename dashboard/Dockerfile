FROM node:20-alpine AS build
ARG VITE_ARGUS_URL
ARG VITE_SENTINEL_URL
ENV VITE_ARGUS_URL=$VITE_ARGUS_URL
ENV VITE_SENTINEL_URL=$VITE_SENTINEL_URL
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.25-alpine
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 8080
