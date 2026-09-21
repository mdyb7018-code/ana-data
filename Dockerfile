FROM python:3.11-slim

WORKDIR /app

# System deps for tgcrypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY backend/ .
COPY frontend/ ./frontend/

EXPOSE 8000

# Persistent session storage
VOLUME ["/app/data"]

ENV DB_PATH=/app/data/anadata.db
ENV SESSION_DIR=/app/data

CMD ["python", "main.py"]

