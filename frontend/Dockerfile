# Accord frontend — build with Vite, serve static assets with nginx.
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

# Empty VITE_API_URL → the app calls /api/... on the same origin, which nginx
# proxies to the api service (correct for both local compose and AWS/ALB).
# Override at build time (--build-arg VITE_API_URL=...) for other setups.
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
