FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY packages/promptetheus/pyproject.toml packages/promptetheus/README.md packages/promptetheus/
COPY packages/promptetheus/promptetheus packages/promptetheus/promptetheus

RUN pip install --no-cache-dir "./packages/promptetheus[server]"

CMD ["sh", "-c", "uvicorn promptetheus.server.app:create_app --factory --host 0.0.0.0 --port ${PORT:-4318}"]
