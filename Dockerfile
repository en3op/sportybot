# Use Python 3.11 Slim as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# 1. Install system dependencies (Lighter layer)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 2. Set working directory
WORKDIR /app

# 3. Install Python dependencies (Medium layer - cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy project files (Light layer - changes frequently)
COPY . .

# Expose the Flask port
EXPOSE 5000

# Start the application orchestrator
CMD ["python", "render_app.py"]
