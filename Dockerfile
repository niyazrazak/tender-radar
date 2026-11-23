# Runs the dashboard and the scheduled checks on a server, for a team.
#   docker build -t tender-radar .
#   docker run -d --name tender-radar -p 8765:8765 --env-file .env \
#     -v tender-radar-data:/app/data -v tender-radar-reports:/app/reports tender-radar
# .env must set TENDER_RADAR_PASSWORD: the container listens on all addresses, so a login is required.
FROM python:3.14-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.json .
COPY tender_radar tender_radar

ENV PYTHONUNBUFFERED=1 TENDER_RADAR_HOST=0.0.0.0
EXPOSE 8765
CMD ["python", "-m", "tender_radar", "serve"]
