FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies: versioni del worker di produzione, transitivi inclusi
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p data/simulations data/uploads data/graphs

EXPOSE 5001

CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--timeout", "300", "--worker-class", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker", "run:app"]
