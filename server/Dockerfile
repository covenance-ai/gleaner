FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py db_mock.py server.py dashboard.html dashboard.css ./
COPY js/ js/

ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
