# =============================================================================
# apps/api/Dockerfile — 뼈대 (skeleton)
# TODO: 멀티스테이지 빌드로 전환 (빌드 의존성과 런타임 이미지 분리)
# TODO: non-root user로 실행 (보안 요구사항 N-02와 연결지어 어필 가능)
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

EXPOSE 8000

# TODO: 프로덕션에서는 --reload 제거, worker 수 등 튜닝
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
