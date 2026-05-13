# Multi-stage build: keeps the runtime image small (~150MB) and leaves the
# build toolchain out of production.

# ── builder ────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# Prune devDependencies for the runtime stage.
RUN npm prune --omit=dev

# ── runtime ────────────────────────────────────────────────────────────────
FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0

COPY --from=builder /app/build ./build
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/scripts ./scripts

EXPOSE 3000

# adapter-node entrypoint.
CMD ["node", "build"]
