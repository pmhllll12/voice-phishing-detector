# =============================================================================
# apps/rag-worker/Dockerfile
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY data ./data
# F-04 pgvector 이전: docker-compose의 기동 커맨드(scripts.seed_fraud_cases)가
# 필요로 한다 — scripts/seed_fraud_cases.py 상단 주석 참고.
COPY scripts ./scripts

EXPOSE 8200

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8200", "--reload"]
