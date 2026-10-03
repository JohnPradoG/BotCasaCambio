FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt requirements-browser.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Para scrapers con JavaScript, descomentar:
# RUN pip install --no-cache-dir -r requirements-browser.txt && python -m playwright install --with-deps chromium

COPY . .
CMD ["python", "-m", "app.main", "loop"]
