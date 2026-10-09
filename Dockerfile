FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 JARVIS_DATA_DIR=/data HF_HOME=/data/hf PORT=8080
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[server]"
# El modelo de voz se descarga en la primera transcripción y queda en el volumen /data.
VOLUME /data
EXPOSE 8080
CMD ["jarvis-server"]
