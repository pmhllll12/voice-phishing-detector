# /ready용 순수 함수. main.py에서 분리해둔 이유: main.py를 그냥 import하면
# EmbeddingSimilarityAdapter(_corpus) 생성 시점에 sentence-transformers 모델을 실제로
# 로드한다(HuggingFace Hub 조회 포함, 로컬에서 실측 약 20초) — 이 파일을 따로 두면
# 테스트가 main.py 전체를 import하지 않고 이 순수 함수만 가짜 서비스로 빠르게 검증할
# 수 있다 (apps/rag-worker/tests/test_ready_endpoint.py 참고).

from src.application.services import SimilarCaseSearchService


def check_embedding_search_ready(service: SimilarCaseSearchService, device: str) -> dict:
    """/health는 모델 "로드 성공" 여부만 보여준다 — 이 체크는 그 모델이 지금도 실제로
    응답하는지를 아주 가벼운 검색 1건으로 검증한다(예: 로드는 성공했지만 이후 다른
    프로세스가 VRAM을 다 써서 CUDA 컨텍스트가 깨지는 경우를 잡기 위함). 외부 서비스를
    호출하지 않으므로 순환 의존 위험이 없다.
    """
    try:
        service.execute("헬스체크용 더미 쿼리", top_k=1)
        return {"status": "ok", "detail": device}
    except Exception as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}
