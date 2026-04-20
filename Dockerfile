FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py kiosk_names.json kiosk_locations.json ./

CMD ["python", "bot.py"]
