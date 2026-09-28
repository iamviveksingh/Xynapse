# ==============================================================================
# XYNAPSE // IBVAP — Production Dockerfile for Hugging Face Spaces (CPU Basic)
# 16 GB RAM • Free Tier • Multi-Stage Build (React Frontend + FastAPI Backend)
# ==============================================================================

# ------------------------------------------------------------------------------
# STAGE 1: Build React 18 Frontend
# ------------------------------------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------------------
# STAGE 2: Python 3.11 Runtime with Computer Vision Dependencies
# ------------------------------------------------------------------------------
FROM python:3.11-slim

# Install system dependencies required for OpenCV, ONNX Runtime, and headless rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces non-root user convention (UID 1000)
RUN useradd -m -u 1000 user
WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend code, models, and tests
COPY backend/ ./backend/
COPY models/ ./models/
COPY .env.example ./

# Copy pre-built frontend distribution from Stage 1 into frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Set up evidence directories with proper write permissions for non-root user
RUN mkdir -p evidence/alerts evidence/transits evidence/faces && \
    chown -R user:user /app

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PORT=7860

# Hugging Face Spaces listens on port 7860
EXPOSE 7860

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
