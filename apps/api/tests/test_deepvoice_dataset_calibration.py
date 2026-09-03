# F-03 딥보이스 임계값을 실제 데이터셋(data/deepvoice_samples/)으로 검증하는 회귀 테스트.
# test_deepvoice_adapter.py가 "각 지표가 설계 의도대로 반응하는가"를 손으로 만든 신호로
# 검증한다면, 이 파일은 "실제로 판별이 되는가"를 실측 오디오로 검증한다 — 공개 TTS
# 엔진(gTTS)이 합성한 한국어 음성 8건과, 라이선스가 명확한 공개 인간 발화(LibriSpeech)
# 8건. 두 소스와 라이선스는 data/deepvoice_samples/manifest.json과
# scripts/generate_deepvoice_dataset.py 상단 주석 참고.
#
# 여기서 재현율/오탐률 임계값(7/8, 2/8)은 이 16건짜리 소규모 데이터셋으로 실측 보정한
# deepvoice_adapter.py의 JITTER_LOW_THRESHOLD/SPECTRAL_FLATNESS_STD_THRESHOLD가 앞으로
# 실수로 도로 느슨해지거나(예: 0.01로 되돌아가는 등) 타이트해지는 걸 잡기 위한
# 회귀 가드다 — "이 정도면 잘 판별한다"는 정확도 보증이 아니다(표본이 16건뿐이므로
# 일반화는 보장하지 않는다, deepvoice_adapter.py 상단 주석 참고).

import json
import wave
from pathlib import Path

import pytest

from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "deepvoice_samples"
MANIFEST = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))


def _load(sample: dict) -> bytes:
    return (DATA_DIR / sample["path"]).read_bytes()


TTS_SAMPLES = [s for s in MANIFEST["samples"] if s["label"] == "tts"]
NATURAL_SAMPLES = [s for s in MANIFEST["samples"] if s["label"] == "natural"]


@pytest.fixture(scope="module")
def adapter() -> HeuristicDeepvoiceAdapter:
    return HeuristicDeepvoiceAdapter()


def test_dataset_files_actually_exist_and_are_valid_wav():
    """manifest.json이 가리키는 파일이 실제로 있고 읽을 수 있는 WAV인지 먼저 확인한다 —
    이게 깨지면 아래 재현율/오탐률 테스트는 "판단 보류"로 조용히 통과해버려 의미가 없다."""
    assert len(TTS_SAMPLES) == 8
    assert len(NATURAL_SAMPLES) == 8
    for sample in MANIFEST["samples"]:
        path = DATA_DIR / sample["path"]
        assert path.exists(), f"{sample['id']}: {path} 없음"
        with wave.open(str(path), "rb") as wf:
            assert wf.getnframes() > 0


def test_tts_recall_is_at_least_seven_of_eight(adapter):
    """실측 보정된 임계값(deepvoice_adapter.py) 기준 재현율 7/8(87.5%) — 이보다 낮아지면
    임계값이 (의도치 않게) 다시 타이트해졌다는 신호다."""
    hits = sum(1 for s in TTS_SAMPLES if adapter.analyze(_load(s)).is_synthetic is True)
    assert hits >= 7, f"TTS 8건 중 {hits}건만 합성으로 판별됨 (기대: 7건 이상)"


def test_natural_false_positive_rate_is_at_most_two_of_eight(adapter):
    """실측 오탐 2/8(25%) — 이보다 늘어나면 임계값이 (의도치 않게) 다시 느슨해졌다는
    신호다(예: 실수로 원래 값 0.01로 되돌리면 오히려 재현율이 0으로 떨어지므로 이
    테스트가 아니라 위 재현율 테스트가 먼저 잡는다 — 이 테스트는 반대 방향 회귀용)."""
    false_positives = sum(1 for s in NATURAL_SAMPLES if adapter.analyze(_load(s)).is_synthetic is True)
    assert false_positives <= 2, f"자연 발화 8건 중 {false_positives}건이 합성으로 오판됨 (기대: 2건 이하)"


def test_verdicts_always_include_explanation_for_n04():
    """N-04(설명가능성): 데이터셋 16건 전부 blackbox 판정 없이 지표 근거를 동반해야 한다."""
    adapter_ = HeuristicDeepvoiceAdapter()
    for sample in MANIFEST["samples"]:
        verdict = adapter_.analyze(_load(sample))
        assert verdict.explanation
        assert len(verdict.indicators) == 3
