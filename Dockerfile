FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --upgrade pip

# 👇 1. Download the lightweight, CPU-only version of PyTorch FIRST
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# 👇 2. Then install everything else (it will see torch is already installed and skip the 500MB download)
RUN pip install --default-timeout=1000 --retries 10 -r requirements.txt

RUN pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl --default-timeout=1000 --retries 10

COPY . .

CMD ["python", "-m", "app.main"]