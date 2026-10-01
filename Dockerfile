FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TRACKER_DB=/app/data/tracker.sqlite3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home tracker \
    && mkdir -p /app/data && chown tracker:tracker /app/data
COPY --chown=tracker:tracker main.py database.py models.py seed_demo.py index.html app.js styles.css ./
USER tracker
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
