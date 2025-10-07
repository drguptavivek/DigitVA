FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y postgresql-client ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN chmod +x resource/smartva boot.sh

ENV FLASK_APP run.py

ENTRYPOINT ["./boot.sh"]
EXPOSE 5000
