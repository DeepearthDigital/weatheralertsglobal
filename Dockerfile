# Dockerfile
FROM python:3.12-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "-b", ":8080", "main:app", "--worker-class", "gevent", "--log-level", "info"]