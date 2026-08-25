# Backend image: dependencies only. The repository is bind-mounted at
# runtime (decision in #221: no code copied into the image, so code
# updates don't require a rebuild — only dependency changes do).
#
# Build context is backend/ (see docker-compose.yml).

FROM python:3.12-slim

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The repo is mounted here by compose; the app runs from its backend/ dir
WORKDIR /repo/backend

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
