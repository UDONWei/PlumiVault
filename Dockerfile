FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-linux.lock.txt ./
RUN pip install --no-cache-dir -r requirements-linux.lock.txt && pip check
COPY bird_index/ ./bird_index/
COPY tools/ ./tools/
COPY web/ ./web/
COPY docs/ ./docs/
USER 1000:1000
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=3).read()"
CMD ["python", "-B", "-m", "bird_index", "serve", "--config", "/config/config.json", "--port", "8765"]
