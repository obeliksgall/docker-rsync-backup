FROM python:3.11-alpine

# Instalacja rsync i stref czasowych
RUN apk add --no-cache rsync tzdata

WORKDIR /app

# Instalacja bibliotek Pythona dla schedulera i powiadomień
RUN pip install --no-cache-dir apscheduler requests croniter

# Skrypt uruchomieniowy
COPY src/ /app/src/

# Uruchamiamy aplikację bez buforowania logów (żeby od razu były widoczne w docker logs)
ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/src/main.py"]