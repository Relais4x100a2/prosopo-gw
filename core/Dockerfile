FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[api]"
EXPOSE 8000
CMD ["uvicorn", "geneweb_py.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
