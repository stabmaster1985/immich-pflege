FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    CONFIG_DIR=/config

WORKDIR /app
COPY pyproject.toml ./
COPY immich_pflege ./immich_pflege
RUN pip install . \
 && groupadd --gid 1000 pflege \
 && useradd --uid 1000 --gid pflege --no-create-home --shell /usr/sbin/nologin pflege \
 && mkdir -p /data /config \
 && chown pflege:pflege /data /config

COPY regeln.example.yaml /app/regeln.example.yaml

USER pflege
VOLUME ["/data", "/config"]
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "immich_pflege.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090", "--proxy-headers"]
