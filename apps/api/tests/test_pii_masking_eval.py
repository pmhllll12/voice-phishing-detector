# N-03 이름 마스킹을 실측 라벨 데이터셋(data/pii_masking_eval.json)으로 정량 검증하는
# 회귀 테스트. test_pii_masking.py가 "의도한 패턴이 실제로 지워지는가"를 손으로 만든
# 개별 사례로 확인한다면, 이 파일은 "정밀도/재현율이 실측으로 얼마인가"를 28건 라벨셋
# 전체에 대해 확인한다 — test_deepvoice_dataset_calibration.py와 같은 성격의 회귀 가드다.
#
# 여기서 정밀도 1.0/재현율 0.727 임계값은 domain/pii_masking.py의
# _NAME_FALSE_POSITIVE_WORDS 블록리스트로 실측 보정한 결과다. 앞으로 실수로 블록리스트가
# 없어지거나(정밀도 하락) 정규식이 더 타이트해지면(재현율 하락) 이 테스트가 잡는다 —
# "이 정도면 완벽하다"는 보증이 아니다(domain/pii_masking.py 상단 주석의 남은 한계 참고).

import json
from pathlib import Path

from src.domain.pii_masking import mask_pii

DATASET = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "pii_masking_eval.json").read_text(encoding="utf-8")
)
CASES = DATASET["cases"]
POSITIVE_CASES = [c for c in CASES if c["has_name"]]
NEGATIVE_CASES = [c for c in CASES if not c["has_name"]]


def _is_hit(case: dict) -> bool:
    out = mask_pii(case["text"])
    return case["expected_span"] not in out and out.count("[이름]") >= 1


def test_dataset_has_expected_case_counts():
    """데이터셋 자체가 의도한 크기인지 먼저 확인 — 이게 깨지면 아래 정밀도/재현율
    테스트가 축소된 표본으로 조용히 통과해버려 의미가 없다."""
    assert len(POSITIVE_CASES) == 22
    assert len(NEGATIVE_CASES) == 12  # 오탐 위험 10건 + 안전 사례(성씨 목록 밖) 2건


def test_name_masking_precision_is_1_0():
    """블록리스트(_NAME_FALSE_POSITIVE_WORDS) 보정 후 실측 정밀도 1.0 — 오탐 0건.
    이보다 낮아지면 블록리스트가 손상됐거나 새 오탐 패턴이 생겼다는 신호다."""
    false_positives = [c["id"] for c in NEGATIVE_CASES if mask_pii(c["text"]).count("[이름]") > 0]
    assert not false_positives, f"오탐 발생: {false_positives}"


def test_name_masking_recall_is_at_least_0_727():
    """실측 재현율 16/22(0.727) — 이보다 낮아지면 정규식이 의도치 않게 더 타이트해졌다는
    신호다. 남은 6건의 누락(FN-01~03,05~07)은 알려진 한계(성씨 목록 밖/호칭 분리/반말)로,
    이 테스트가 요구하는 건 "현재 수준을 유지"이지 "전부 잡아라"가 아니다."""
    hits = sum(1 for c in POSITIVE_CASES if _is_hit(c))
    recall = hits / len(POSITIVE_CASES)
    assert recall >= 0.727, f"재현율 {recall:.3f} (기대: 0.727 이상, {hits}/{len(POSITIVE_CASES)})"


def test_known_false_negative_patterns_are_still_documented_limits():
    """알려진 3가지 누락 패턴(성씨 목록 밖, 호칭이 이름과 분리, 호칭 없는 반말)이 여전히
    한계로 존재함을 확인 — 언젠가 이 중 하나가 우연히 고쳐지면(다른 변경의 부작용) 이
    테스트가 실패하니, 그때는 이 테스트를 지우고 domain/pii_masking.py 주석도 갱신할 것."""
    known_miss_ids = {"FN-01", "FN-02", "FN-03", "FN-05", "FN-06", "FN-07"}
    still_missed = {c["id"] for c in POSITIVE_CASES if c["id"] in known_miss_ids and not _is_hit(c)}
    assert still_missed == known_miss_ids
