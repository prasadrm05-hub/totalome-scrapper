FROM python:3.10-slim

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# OS deps for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends     libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3     libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1     libpango-1.0-0 libasound2 libatspi2.0-0 libxshmfence1 fonts-liberation     ca-certificates wget gnupg &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright
RUN python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
