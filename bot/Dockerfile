# Slim multi-arch base — works on the Spark's aarch64 (GB10).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Persisted SQLite lives here (mounted volume in compose).
VOLUME ["/data"]

CMD ["python", "-u", "bot.py"]
