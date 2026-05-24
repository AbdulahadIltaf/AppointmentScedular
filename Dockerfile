FROM python:3.12-slim

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy all source files
COPY . .

# Expose the mandatory Hugging Face port
EXPOSE 7860

# Run FastAPI app via Uvicorn on HF Space port
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
