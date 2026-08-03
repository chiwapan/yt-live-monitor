FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web/ ./web/
# live_data.jsonl lives in a volume by default (see README)
ENV LIVE_JSONL=/data/live_data.jsonl PORT=8899

EXPOSE 8899
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8899/api/ping',timeout=4)" || exit 1

CMD ["python", "web/app.py"]
