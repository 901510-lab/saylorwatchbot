FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# fonts-dejavu-core — шрифты для генерации image-карточек (Pillow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py i18n.py cards.py start.sh ./
RUN chmod +x start.sh

EXPOSE 10000

CMD ["./start.sh"]
