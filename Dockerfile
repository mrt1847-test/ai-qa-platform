FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY third_party/mobile_agent/manifest.json ./third_party/mobile_agent/
COPY third_party/mobile_agent/upstream/run_gui_owl_1_5_for_mobile.py ./third_party/mobile_agent/upstream/
COPY third_party/mobile_agent/upstream/utils.py ./third_party/mobile_agent/upstream/
COPY third_party/mobile_agent/upstream/packages.py ./third_party/mobile_agent/upstream/
COPY third_party/mobile_agent/upstream/LICENSE ./third_party/mobile_agent/upstream/
RUN pip install --no-cache-dir '.[hosted]' \
    && useradd --create-home --uid 10001 aiqa \
    && mkdir -p /tmp/aiqa \
    && chown aiqa:aiqa /tmp/aiqa

USER aiqa
EXPOSE 8000
CMD ["python", "-B", "-m", "aiqa.hosted.entry"]
