FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py start.sh ./
RUN chmod +x start.sh

EXPOSE 10000

CMD ["./start.sh"]
