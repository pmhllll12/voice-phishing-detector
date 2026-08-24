# =============================================================================
# apps/mcp-server/Dockerfile — 뼈대 (skeleton)
#
# 이 이미지는 rest_server.py(HTTP REST 어댑터)를 띄운다 — docker-compose 네트워크
# 안에서 apps/api가 mcp-server:8100으로 호출하는 쪽. server.py(MCP stdio 어댑터)는
# Claude Code가 로컬에서 .mcp.json으로 직접 붙는 용도라 컨테이너 안에서는 의미가 없다
# (stdio는 네트워크 프로토콜이 아님) — 그래서 이 이미지에는 포함하지 않는다.
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

EXPOSE 8100

CMD ["uvicorn", "rest_server:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8100"]
