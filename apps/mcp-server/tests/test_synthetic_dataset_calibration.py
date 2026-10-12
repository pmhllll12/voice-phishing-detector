# F-01/F-02 규칙 기반(v1) 스코어링을 합성 데이터셋(data/synthetic_call_transcripts.json)으로
# 검증한다 (docs/RFP.md 4장, pattern_rules.py/entities.py의 "합성 데이터셋으로 검증할 것" TODO).
#
# 데이터셋은 세 그룹으로 나뉜다:
#   - textbook: PATTERN_RULES 키워드와 정확히 겹치는 문장 — CATEGORY_WEIGHTS/RISK_LEVEL_THRESHOLDS
#     조합이 설계 의도(1개 카테고리→저위험, 2개→중위험, 3개 이상→고위험)대로 동작하는지 확인한다.
#   - benign: 정상 통화 대조군 — 오탐(false positive) 없이 0점이어야 한다(정밀도 검증).
#   - natural_language_gap: 같은 수법을 자연스러운 구어체로 표현한 문장 — v1이 놓치는 것을
#     "버그"가 아니라 "알려진 한계"로 문서화한다. 나중에 PATTERN_RULES를 보강해서 이 중 하나를
#     잡아내게 되면, 바로 이 테스트가 실패하며 "여기 보강됐다"는 신호를 준다.

import json
from pathlib import Path

import pytest

from application.services import PatternDetectionService, RiskScoringService
from domain.entities import PatternCategory

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_call_transcripts.json"

with open(DATASET_PATH, encoding="utf-8") as f:
    _DATASET = json.load(f)

detection_service = PatternDetectionService()
scoring_service = RiskScoringService()


def _score(text: str):
    detection = detection_service.detect(text)
    risk = scoring_service.score(detection)
    return detection, risk


def _cases(label: str) -> list[dict]:
    return [c for c in _DATASET if c["label"] == label]


@pytest.mark.parametrize("case", _cases("textbook"), ids=lambda c: c["id"])
def test_textbook_case_matches_expected_categories_and_risk_level(case):
    detection, risk = _score(case["text"])

    detected_categories = {p.category.value for p in detection.detected_patterns}
    assert detected_categories == set(case["expected_categories"]), case["text"]
    assert risk.level.value == case["expected_risk_level"], (case["text"], risk.score)


@pytest.mark.parametrize("case", _cases("benign"), ids=lambda c: c["id"])
def test_benign_case_produces_zero_score(case):
    detection, risk = _score(case["text"])

    assert risk.score == 0, case["text"]
    assert risk.level.value == "low"
    assert detection.detected_patterns == []


@pytest.mark.parametrize("case", _cases("natural_language_gap"), ids=lambda c: c["id"])
def test_natural_language_gap_is_a_documented_v1_limitation(case):
    """이 그룹은 통과가 아니라 '현재 v1의 한계 지점'을 기록하는 것이 목적이다.
    rule_based_recall_expected=false인 케이스가 score=0으로 나오는 것은 실패가 아니라
    현재 상태를 있는 그대로 반영한 것 — LLM 기반(v2)이 이 사각지대를 메꾸는 이유이기도 하다.

    2026-08-28 실측(CALL_ANALYSIS_BACKEND=llm, mcp-server /api/v1/analyze 직접 호출):
    G-01(가족사칭) high/85, G-03(대출빙자) high/70, G-04(환급빙자) high/75,
    G-05(지인사칭) high/85 — 문맥 이해가 필요한 자연스러운 사회공학 문구는 v2가
    올바르게 고위험으로 잡아낸다. 유일한 예외는 G-02(URL 스미싱) low/30 — 링크 클릭
    유도형은 대화형 사회공학과 근본적으로 다른 공격 벡터(URL 평판 조회가 필요)라
    LLM도 여전히 놓친다. v1/v2 모두의 공통 사각지대이므로 별도 URL 탐지기가
    필요하다는 뜻 — 이 프로젝트 범위 밖의 후속 과제로 남겨둔다.
    """
    assert case["rule_based_recall_expected"] is False

    detection, risk = _score(case["text"])

    assert risk.score == 0, (
        f"{case['id']}가 더 이상 0점이 아니다 — PATTERN_RULES가 보강되어 이 사각지대를 "
        "잡아내게 됐다는 뜻이므로, 이 케이스의 label을 'textbook'으로 옮기고 "
        "rule_based_recall_expected를 true로 갱신할 것."
    )


def test_dataset_covers_all_pattern_categories_at_least_once():
    """N-06(확장성): 나중에 카테고리가 추가되는데 데이터셋이 갱신되지 않으면 이 테스트가
    바로 알려준다."""
    covered = {cat for case in _cases("textbook") for cat in case["expected_categories"]}
    assert covered == {c.value for c in PatternCategory}
