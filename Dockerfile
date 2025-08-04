FROM python:3.11-slim

# —— system packages ——
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        libnss3 \
        libx11-xcb1 \
        libatk-bridge2.0-0 \
        libgtk-3-0 \
        fonts-liberation \
        ca-certificates \
        wget && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Optional: show versions
RUN chromium --version && chromedriver --version

# —— python env ——
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# —— source code ——
COPY . .

CMD ["python", "main.py"]
