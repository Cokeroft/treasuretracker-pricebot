# Playwright's official image ships Chromium + all required system deps
# preinstalled, so we don't need to fight apt-get dependency resolution
# for headless browser libs on Railway. Match the version to whatever
# the existing TreasureTracker scraper uses if it differs.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already in the base image, but this is a harmless no-op
# safety net in case the base image version drifts from requirements.txt.
RUN playwright install --with-deps chromium

COPY . .

# Railway sets PORT for web services; this bot has no HTTP server of its
# own (it's a Discord gateway client), so no EXPOSE/PORT binding needed.
CMD ["python", "bot.py"]
