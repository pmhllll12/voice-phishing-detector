from src.application.services import SimilarCaseSearchService
from src.infrastructure.adapters.tfidf_similarity_adapter import TfidfSimilarityAdapter
from src.infrastructure.data_loader import load_fraud_cases

_corpus = load_fraud_cases()
_service = SimilarCaseSearchService(TfidfSimilarityAdapter(_corpus))


def test_prosecutor_impersonation_query_ranks_matching_case_first():
    transcript = "검찰청 수사관인데 계좌가 범죄에 연루돼서 지금 즉시 안전계좌로 이체해야 한다고 전화왔어"
    matches = _service.execute(transcript, top_k=3)

    assert matches[0].case.case_id == "FC-001"
    assert matches[0].similarity > 0


def test_parcel_smishing_query_ranks_matching_case_first():
    transcript = "택배가 반송된다는 문자를 받았는데 링크를 눌렀더니 앱이 설치됐어요"
    matches = _service.execute(transcript, top_k=2)

    assert matches[0].case.case_id == "FC-006"


def test_top_k_limits_result_count():
    matches = _service.execute("아무 관련 없는 일상 대화입니다", top_k=2)
    assert len(matches) == 2


def test_results_are_sorted_by_similarity_descending():
    matches = _service.execute("검찰청 수사관인데 지금 즉시 송금하세요", top_k=len(_corpus))
    scores = [m.similarity for m in matches]
    assert scores == sorted(scores, reverse=True)
