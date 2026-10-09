FROM python:3.12-slim
ARG WHISPER_MODEL=small
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    JARVIS_DATA_DIR=/data PORT=8080 \
    HF_HOME=/opt/hf JARVIS_WHISPER_MODEL=${WHISPER_MODEL}
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[server]"
# El modelo de voz se descarga al construir la imagen (no en la primera visita) y queda dentro de ella.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', compute_type='int8')"
EXPOSE 8080
CMD ["jarvis-server"]
