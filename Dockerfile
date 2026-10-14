# The FastAPI backend for Render. The React app is hosted separately (Vercel), which forwards
# /api/* here; see README "Deployment".
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# DejaVu has the ₹ and € signs for the PDF exports (app/exports/pdf.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app

RUN useradd --create-home --uid 10001 app
USER app

ENV ENVIRONMENT=production \
    PORT=10000
EXPOSE 10000
# Render sets $PORT. Proxy headers are read by app/core/client_ip.py (TRUST_PROXY), not uvicorn.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-proxy-headers"]
