FROM node:22-alpine AS builder
WORKDIR /app
COPY mcp-server/package*.json ./
RUN npm ci --production=false
COPY mcp-server/tsconfig.json ./
COPY mcp-server/src ./src
RUN npx tsc

FROM node:22-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY mcp-server/package.json ./
ENV NODE_ENV=production
EXPOSE 3001
ENTRYPOINT ["node", "dist/index.js"]
