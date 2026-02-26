FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for PyAV (video decoding) and build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libavcodec-dev libavformat-dev libavutil-dev libswscale-dev \
        pkg-config gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY client/ client/
COPY scripts/ scripts/

EXPOSE 8000

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
