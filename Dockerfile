# syntax=docker/dockerfile:1

# ---- base ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---- system deps: Tesseract + libs Pillow needs ----
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libtesseract-dev \
        libleptonica-dev \
        gcc \
        libjpeg62-turbo-dev \
        zlib1g-dev \
        libpng-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

# ---- app ----
WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . /app

# ---- run ----
CMD ["python", "-u", "c1c_claims_appreciation.py"]
