FROM python:3.12-slim
WORKDIR /app
COPY mock_ota_server.py .
EXPOSE 9000
CMD ["python", "mock_ota_server.py"]
