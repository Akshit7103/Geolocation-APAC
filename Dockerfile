FROM python:3.12-slim

# Keep Python output unbuffered so logs stream to `docker compose logs`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY main.py maps2.py gunicorn.conf.py ./

EXPOSE 8000

# Production server: Gunicorn managing Uvicorn workers (see gunicorn.conf.py).
CMD ["gunicorn", "main:app", "-c", "gunicorn.conf.py"]
