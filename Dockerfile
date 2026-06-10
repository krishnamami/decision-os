# Accord / Decision OS — API backend (FastAPI + uvicorn)
FROM python:3.11-slim

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source. .env, frontend/, and caches are excluded via .dockerignore —
# secrets are injected at runtime via environment variables, never baked in.
COPY . .

EXPOSE 8000

# The app starts via the create_app() factory, exposed as get_app() for
# `uvicorn --factory` (the plain module-level `app` is None until built).
CMD ["uvicorn", "api.main:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
