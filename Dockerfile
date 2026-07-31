FROM python:3.11.9-alpine@sha256:f9ce6fe33d9a5499e35c976df16d24ae80f6ef0a28be5433140236c2ca482686 AS compile-image

WORKDIR /app

COPY requirements.txt /app/

RUN apk add --no-cache --virtual .build-deps \
        gcc=13.2.1_git20240309-r1 \
        musl-dev=1.2.5-r3 \
    && pip install --trusted-host pypi.python.org -r requirements.txt \
    && apk del .build-deps && rm -rf requirements.txt

RUN apk add --no-cache rclone=1.66.0-r5

FROM python:3.11.9-alpine@sha256:f9ce6fe33d9a5499e35c976df16d24ae80f6ef0a28be5433140236c2ca482686 AS runtime-image

WORKDIR /app

ENV HOME=/home/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/app/temp \
    XDG_CACHE_HOME=/app/temp/.cache \
    TMD_RUNTIME_HEALTH_PATH=/app/state/runtime-health.json

RUN addgroup -S -g 10001 app \
    && adduser -S -D -u 10001 -G app -h /home/app app \
    && mkdir -p /app/downloads /app/log /app/rclone /app/sessions \
        /app/state /app/temp /home/app/.config/rclone \
    && chown -R app:app /app /home/app

COPY --from=compile-image --chown=app:app /usr/bin/rclone /app/rclone/rclone

COPY --from=compile-image /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

COPY --chown=app:app config.example.yaml data.example.yaml setup.py media_downloader.py /app/
COPY --chown=app:app module /app/module
COPY --chown=app:app utils /app/utils

USER app:app

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "module.runtime_health"]

CMD ["python", "media_downloader.py"]
