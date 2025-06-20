FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Removed supervisor installation and config copy
# RUN apt-get update && apt-get install -y supervisor
# COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

COPY ./huh.db /app/huh.db
CMD ["python3", "/app/discord_bot.py"]
