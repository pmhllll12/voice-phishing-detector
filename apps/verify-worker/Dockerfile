# =============================================================================
# apps/verify-worker/Dockerfile — 뼈대 (skeleton, docker-compose/k3s에는 아직 미등록)
# 역방향 신원확인 POC(모의 시제품). 실제 모바일신분증과 연동하지 않는다.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

EXPOSE 8400

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8400"]
