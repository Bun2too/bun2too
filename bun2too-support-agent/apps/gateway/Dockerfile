FROM node:24-slim
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY apps/gateway ./apps/gateway
RUN pnpm install --frozen-lockfile --filter @relay/gateway...
ENV NODE_ENV=production RELAY_GATEWAY_PORT=8080
EXPOSE 8080
CMD ["pnpm", "--filter", "@relay/gateway", "start"]
