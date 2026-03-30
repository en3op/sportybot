# Use Python 3.11 Slim as base
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose the Flask port
EXPOSE 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# Start the application orchestrator
CMD ["python", "render_app.py"]
