FROM python:3.11-slim

# ── only system package we really need ───────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python deps ──────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── project code ─────────────────────────────────────────────
COPY proxy_pool.py   .
COPY html_scraper.py .
COPY main.py         .
CMD ["python", "main.py"]
