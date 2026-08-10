FROM debian:bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8088 \
    TZ=Europe/Prague

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-flask \
      python3-paramiko \
      gunicorn \
      tzdata \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN python3 /app/v369_patch.py

EXPOSE 8088
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
