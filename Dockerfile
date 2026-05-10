FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flux_led==1.2.0

COPY controller.py /app/
COPY web/ /app/web/

VOLUME /data

ENV CONFIG_PATH=/data/config.json
ENV WEB_PORT=8080
ENV API_PORT=8081

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/api/state')" || exit 1

CMD ["python", "-u", "controller.py"]
