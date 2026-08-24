# TODO: 여기에 실제 어댑터 구현체를 추가한다 (헥사고날 아키텍처의 "port 구현체")
#   - postgres_repository.py: 감사로그/판정결과 저장 (N-01)
#   - mcp_client.py: mcp-server 호출 클라이언트
#   - rag_client.py: rag-worker 호출 클라이언트
#
# application 계층은 이 어댑터들의 "인터페이스"만 알아야 하고,
# 구체 구현(어떤 DB 드라이버를 쓰는지 등)은 여기 안에 갇혀 있어야 한다.
