# The server side as one container for Render: the gateway (public, owns the session cookie)
# and the FastAPI backend (listening on localhost only, so it's reachable just through the
# gateway). The React app is hosted separately (Vercel); see README "Deployment".

# Gateway dependencies, built with npm, then only node and the modules are copied over.
FROM node:22-slim AS gateway
WORKDIR /gateway
COPY gateway/package.json gateway/package-lock.json ./
RUN npm ci --omit=dev
COPY gateway/src ./src

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# DejaVu has the ₹ and € signs for the PDF exports (app/exports/pdf.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=gateway /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app

COPY --from=gateway /gateway /app/gateway
COPY deploy/start.sh /app/start.sh

RUN useradd --create-home --uid 10001 app && chmod +x /app/start.sh
USER app

ENV NODE_ENV=production \
    FASTAPI_URL=http://127.0.0.1:8000 \
    PORT=10000
EXPOSE 10000
CMD ["/app/start.sh"]
