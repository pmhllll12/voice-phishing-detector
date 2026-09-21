# F-03 v2(wav2vec2_deepvoice_adapter.py)를 실제 F-03 데이터셋(data/deepvoice_samples/)과
# 실제 HuggingFace 모델로 검증한다 — test_deepvoice_dataset_calibration.py(v1)와 같은
# "실측" 철학이다: v1 대비 v2가 더 낫다는 걸 유닛 목(mock)이 아니라 진짜 16개 오디오
# 파일을 진짜 모델에 태워서 확인한다.
#
# 모델 로드는 최초 1회 HuggingFace Hub 네트워크 접근이 필요하다(이후 로컬 캐시). CI나
# 오프라인 환경에서 깨지지 않도록, 모델 로드에 실패하면(네트워크 없음 등) 이 파일
# 전체를 skip한다 — 그 경우는 wav2vec2_deepvoice_adapter.py의 폴백 로직이 대신 커버한다
# (test_falls_back_to_heuristic_when_model_unavailable 참고, 이 테스트는 일부러 존재하지
# 않는 모델명을 써서 네트워크 상태와 무관하게 항상 실행된다).

import json
from pathlib import Path

import pytest

from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter
from src.infrastructure.adapters.wav2vec2_deepvoice_adapter import Wav2Vec2DeepvoiceAdapter

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "deepvoice_samples"
MANIFEST = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))

TTS_SAMPLES = [s for s in MANIFEST["samples"] if s["label"] == "tts"]
NATURAL_SAMPLES = [s for s in MANIFEST["samples"] if s["label"] == "natural"]


def _load(sample: dict) -> bytes:
    return (DATA_DIR / sample["path"]).read_bytes()


@pytest.fixture(scope="module")
def adapter() -> Wav2Vec2DeepvoiceAdapter:
    instance = Wav2Vec2DeepvoiceAdapter(fallback=HeuristicDeepvoiceAdapter())
    if instance._pipeline is None:  # noqa: SLF001 — 테스트 skip 판단용
        pytest.skip("wav2vec2 딥보이스 모델을 로드하지 못했습니다 (네트워크/HF Hub 접근 필요)")
    return instance


def test_tts_recall_is_perfect_on_measured_dataset(adapter):
    """2026-08-31 실측: mo-thecreator/Deepfake-audio-detection이 TTS 8건 전부(신뢰도
    0.99 이상)를 합성으로 정확히 분류했다. 이 회귀 가드는 "이 모델이 완벽하다"는
    일반화 보증이 아니다 — 표본이 16건뿐이고 모델 카드에 학습 데이터셋이 명시돼
    있지 않아 우리 데이터셋(gTTS)과 겹칠 가능성도 배제 못 한다(어댑터 상단 주석
    참고). 이 값이 흔들리면 모델 버전이 바뀌었거나 라벨 매핑이 깨진 것이다."""
    hits = sum(1 for s in TTS_SAMPLES if adapter.analyze(_load(s)).is_synthetic is True)
    assert hits == 8, f"TTS 8건 중 {hits}건만 합성으로 판별됨 (실측 기준: 8건)"


def test_natural_false_positive_is_zero_on_measured_dataset(adapter):
    """2026-08-31 실측: 자연 발화 8건 전부 오탐 없이 실제 음성으로 분류됐다."""
    false_positives = sum(1 for s in NATURAL_SAMPLES if adapter.analyze(_load(s)).is_synthetic is True)
    assert false_positives == 0, f"자연 발화 8건 중 {false_positives}건이 합성으로 오판됨 (실측 기준: 0건)"


def test_verdicts_combine_model_and_heuristic_indicators_for_n04(adapter):
    """N-04(설명가능성): 모델 판정 1개 + v1 보조 음향 지표 3개, 총 4개 근거가 항상
    함께 반환돼야 한다 — 신경망 모델의 "그렇다고 나왔다"는 한 줄로 끝나지 않게 하려는
    설계(어댑터 상단 주석 참고)."""
    for sample in MANIFEST["samples"]:
        verdict = adapter.analyze(_load(sample))
        assert verdict.explanation
        assert len(verdict.indicators) == 4
        assert verdict.indicators[0].name == "wav2vec2_spoof_classifier"


def test_falls_back_to_heuristic_when_model_unavailable():
    """모델명이 존재하지 않으면(HF Hub 404 등) 생성자에서 로드가 실패하고, 이후
    analyze()는 예외 없이 v1(휴리스틱) 결과를 그대로 반환해야 한다 — Ollama(F-01/F-02
    v2) 폴백과 동일한 안전장치."""
    broken_adapter = Wav2Vec2DeepvoiceAdapter(
        fallback=HeuristicDeepvoiceAdapter(),
        model_name="nonexistent-org/this-model-does-not-exist-portfolio-test",
    )
    assert broken_adapter._pipeline is None  # noqa: SLF001

    verdict = broken_adapter.analyze(_load(TTS_SAMPLES[0]))
    assert verdict.explanation
    assert len(verdict.indicators) == 3  # 순수 v1 휴리스틱 결과(모델 지표 없음)
