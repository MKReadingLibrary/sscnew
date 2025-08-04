FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium chromium-driver \
        libnss3 libx11-xcb1 libatk-bridge2.0-0 libgtk-3-0 \
        fonts-liberation ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
RUN chmod +x /app/main.py

CMD ["python", "main.py"]
