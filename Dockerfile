FROM python:3.10-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/

# Python configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Create a shared directory for the SQLite database volume
RUN mkdir -p /app/data

EXPOSE 8000

# Default cmd (will be run by the api service)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
