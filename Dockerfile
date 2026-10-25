# Version (Commit) ermitteln – ohne git im Image:
# aus den Build-Argumenten (Update-Dienst baut aus „git archive“) oder aus dem .git-Verzeichnis
FROM python:3.12-slim AS version
ARG GIT_COMMIT=""
ARG GIT_BRANCH=""
ARG GIT_DATE=""
WORKDIR /src
COPY . .
RUN python -c "import json, os, sys; from pathlib import Path; sys.path.insert(0, 'immich_pflege'); \
from gitinfo import read_git_version; c = os.environ.get('GIT_COMMIT'); \
v = {'commit': c, 'branch': os.environ.get('GIT_BRANCH') or None, 'updated_at': os.environ.get('GIT_DATE') or None} \
if c else read_git_version(Path('.')); print(json.dumps(v))" > /version.json

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml ./
COPY immich_pflege ./immich_pflege
RUN pip install . \
 && groupadd --gid 1000 pflege \
 && useradd --uid 1000 --gid pflege --no-create-home --shell /usr/sbin/nologin pflege \
 && mkdir -p /data \
 && chown pflege:pflege /data
COPY --from=version /version.json /app/version.json

USER pflege
VOLUME ["/data"]
EXPOSE 2222

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:2222/healthz', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "immich_pflege.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "2222", "--proxy-headers"]
