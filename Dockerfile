FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    CERTIFICA_BROWSER_MODE=server \
    CERTIFICA_HEADLESS=false \
    CERTIFICA_PROFILE_DIR=/data/browser-profile \
    CERTIFICA_MAX_QUEUE=100

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app.py consultations.py federal.py santa_rita.py browser_worker.py ./
COPY static ./static
COPY docs ./docs

RUN mkdir -p /data/browser-profile && chown -R pwuser:pwuser /app /data

USER pwuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz',timeout=3).close()"

CMD ["sh", "-c", "xvfb-run -a python app.py --host 0.0.0.0 --port ${PORT:-8000}"]
