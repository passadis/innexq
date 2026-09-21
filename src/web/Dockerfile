FROM node:24-alpine AS build
WORKDIR /app/src/web
COPY src/web/package*.json ./
RUN npm ci --ignore-scripts
COPY src/web/ ./
COPY src/contracts/schemas/ /app/src/contracts/schemas/
RUN npm run contracts:check && npm run build

FROM node:24-alpine
ENV NODE_ENV=production PORT=8080
WORKDIR /app
COPY --from=build --chown=node:node /app/src/web/dist ./dist
COPY --chown=node:node src/web/server.mjs ./server.mjs
USER node
EXPOSE 8080
CMD ["node", "server.mjs"]
