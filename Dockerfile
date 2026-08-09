FROM arm32v7/debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MESH_DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-flask python3-paramiko iputils-ping ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py mesh_core.py /app/
COPY templates /app/templates
COPY static /app/static

VOLUME ["/data"]
EXPOSE 8088
CMD ["python3", "/app/app.py"]
