FROM python:3.11-slim-bullseye

WORKDIR /app

RUN apt-get update && apt-get install -y curl jq wget git
ENV PYTHONUNBUFFERED True

COPY requirements-docker.txt /app

RUN pip install -r requirements-docker.txt
EXPOSE 8080

COPY autogpt/ /app/autogpt
COPY gunicorn.conf.py /app

ENV PORT 8080
ENV HOST 0.0.0.0

CMD ["gunicorn" , "-c", "gunicorn.conf.py", "autogpt.api:app"]
