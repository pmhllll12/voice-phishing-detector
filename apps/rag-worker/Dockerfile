# =============================================================================
# apps/rag-worker/Dockerfile — 뼈대 (skeleton)
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY data ./data

EXPOSE 8200

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8200", "--reload"]
