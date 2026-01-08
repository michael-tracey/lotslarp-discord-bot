FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for WeasyPrint and DiscordChatExporter
# libicu-dev is required for .NET globalization (DiscordChatExporter)
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    libjpeg62-turbo-dev \
    libopenjp2-7-dev \
    libffi-dev \
    libicu-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install DiscordChatExporter.Cli
# Using latest release with correct lowercase filename
RUN mkdir -p /app/bin/DiscordChatExporter \
    && DCE_URL="https://github.com/Tyrrrz/DiscordChatExporter/releases/latest/download/DiscordChatExporter.Cli.linux-x64.zip" \
    && echo "Downloading from: $DCE_URL" \
    && curl -L -o /tmp/dce.zip "$DCE_URL" \
    && if ! unzip /tmp/dce.zip -d /app/bin/DiscordChatExporter; then cat /tmp/dce.zip; exit 1; fi \
    && chmod +x /app/bin/DiscordChatExporter/DiscordChatExporter.Cli \
    && rm /tmp/dce.zip

# Set ENV for the bot to find the tool. 
# This will be the default unless overridden by deployment config, 
# but deploy scripts should be configured to NOT override this with a local path.
ENV DCE_CLI_PATH=/app/bin/DiscordChatExporter/DiscordChatExporter.Cli

COPY . .

# Removed supervisor installation and config copy
# RUN apt-get update && apt-get install -y supervisor
# COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

COPY ./huh.db /app/huh.db
CMD ["python3", "/app/discord_bot.py"]