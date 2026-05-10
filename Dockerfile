FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flux_led==1.2.0

COPY controller.py /app/
COPY web/ /app/web/

VOLUME /data

ARG BUILD_SHA=dev
ARG BUILD_VERSION=local
ARG BUILD_DATE=unknown

ENV CONFIG_PATH=/data/config.json
ENV WEB_PORT=8080
ENV API_PORT=8081
ENV BUILD_SHA=${BUILD_SHA}
ENV BUILD_VERSION=${BUILD_VERSION}
ENV BUILD_DATE=${BUILD_DATE}

LABEL org.opencontainers.image.revision=${BUILD_SHA}
LABEL org.opencontainers.image.version=${BUILD_VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/api/state')" || exit 1

CMD ["python", "-u", "controller.py"]
