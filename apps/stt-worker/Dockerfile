# =============================================================================
# apps/stt-worker/Dockerfile — 뼈대 (skeleton, docker-compose.yaml에는 아직 미등록)
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

# GPU(cuBLAS/cuDNN) 사용에 필요 — requirements.txt 상단 주석 참고. pip로 설치한
# nvidia-cublas-cu12/nvidia-cudnn-cu12는 시스템 라이브러리 경로에 없어서 명시적으로
# LD_LIBRARY_PATH에 추가해야 ctranslate2가 찾는다.
ENV LD_LIBRARY_PATH="/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib"

EXPOSE 8300

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8300", "--reload"]
