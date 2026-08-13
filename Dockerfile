FROM python:3.10-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/rag_application

WORKDIR /app

# 1. System dependencies:
#    - build-essential/libpq-dev: needed to build psycopg
#    - curl: needed to install uv below
#    (Node.js was removed — tools.py launches both MCP servers via `uvx`, not `npx`)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Install uv (required by tools.py to run the AWS MCP servers via `uvx`)
RUN pip install --no-cache-dir uv

# 3. Install Python dependencies (separate layer so this is cached across code changes)
COPY requirment.txt .
RUN pip install --no-cache-dir -r requirment.txt

# 4. Copy application source code
COPY . .

# Expose ports for FastAPI (8080) and Streamlit (8501)
EXPOSE 8080
EXPOSE 8501

# Default command runs FastAPI; docker-compose overrides this for the Streamlit frontend service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]