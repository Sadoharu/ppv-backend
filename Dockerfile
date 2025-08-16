FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python","start.py"]
