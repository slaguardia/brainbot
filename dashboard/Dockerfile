# Build the client + transpile the server, then run from a slim image.
#
# Build context is the REPO ROOT (see compose/docker-compose.yml: context: ..)
# because the dashboard now depends on ../web-toolkit (a file: dependency) and docs.ts
# imports ../../docs/*.md?raw — both live outside dashboard/. Copy the toolkit, the
# rendered docs, and the app, install (resolving the file dep), then build.
FROM node:22-alpine AS build
WORKDIR /app
# The toolkit first (the file: dep must exist before `npm install` in dashboard/).
COPY web-toolkit ./web-toolkit
# Only the docs docs.ts renders (?raw imports); keeps the context lean.
COPY docs/brain-architecture.md docs/learnings.md docs/positioning.md ./docs/
# The app.
COPY dashboard ./dashboard
WORKDIR /app/dashboard
RUN npm install --no-audit --no-fund
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8787
# Runtime needs only the built client + transpiled server + package.json. The
# toolkit is bundled into dist/ at build time; the backend never imports it.
COPY --from=build /app/dashboard/package.json ./
COPY --from=build /app/dashboard/dist ./dist
COPY --from=build /app/dashboard/dist-server ./dist-server
EXPOSE 8787
CMD ["node", "dist-server/server/index.js"]
