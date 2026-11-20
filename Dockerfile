FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data

ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

RUN groupadd --gid ${APP_GID} appuser \
 && useradd --uid ${APP_UID} --gid appuser --no-create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Data volume: configuration (settings.json), invitations, audit log and session key.
# The only folder to mount from the host.
RUN mkdir -p /app/data && chown appuser:appuser /app/data

VOLUME ["/app/data"]

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=2)" || exit 1

CMD ["python", "entrypoint.py", \
     "python", "-m", "gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "30", \
     "app:app"]
