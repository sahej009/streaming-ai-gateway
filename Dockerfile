FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip

# 👇 1. Download the lightweight, CPU-only version of PyTorch FIRST
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# 👇 2. Then install everything else (it will see torch is already installed and skip the 500MB download)
RUN pip install --default-timeout=1000 --retries 10 -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]