# Playwright official Python image: includes Chromium + all browser system deps (ubuntu-jammy).
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5000 \
    PULSETRACE_BACKEND=gemini \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# WeasyPrint native deps (Pango / Cairo / GDK-PixBuf) + fonts for PDF rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 \
      libgdk-pixbuf-2.0-0 shared-mime-info fonts-liberation fonts-dejavu-core \
      build-essential tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt gunicorn

COPY . .

# Persisted state lives on host volumes.
RUN mkdir -p /app/data /app/info /app/data/runs /app/data/event_logs

EXPOSE 5000

ENTRYPOINT ["/usr/bin/tini","--"]
# 2 sync workers, 1 thread each — Playwright + SSE need long-lived connections.
# Threaded class lets SSE generators stream concurrently without blocking the worker.
CMD ["gunicorn","-k","gthread","-w","2","--threads","8","--timeout","600","-b","0.0.0.0:5000","server:app"]
