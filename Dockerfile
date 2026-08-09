FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8088
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/backups
EXPOSE 8088
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "8", "--timeout", "1900", "app:app"]
