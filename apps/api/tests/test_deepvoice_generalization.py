# F-03 v2(wav2vec2) "일반화" 검증 — test_deepvoice_dataset_calibration.py가 쓰는
# data/deepvoice_samples/(16건, 임계값 보정용)와는 별도의 홀드아웃 데이터셋
# (data/deepvoice_generalization_samples/, 48건)으로 검증한다.
#
# WHY 별도 데이터셋인가: 보정에 쓴 데이터로 일반화까지 주장하면 순환 논증이다. 게다가
# 보정 데이터셋은 TTS=한국어(gTTS)/자연발화=영어(LibriSpeech)로 언어가 갈려있어서,
# "완벽 분리"가 합성 여부가 아니라 언어를 구분한 결과일 수 있다는 교란 요인이 있었다.
# 이 데이터셋은 TTS 엔진 2종(gTTS/edge-tts) x 자연 발화 언어 2종(영어 LibriSpeech/
# 한국어 Zeroth-Korean, CC BY 4.0)으로 구성해 엔진·언어 교란 요인을 통제했다 —
# generate_deepvoice_generalization_dataset.py 상단 주석 참고.
#
# 실측(2026-09-01): 전체 47/48(97.9%). 특히 보정 데이터셋에 없던 두 축 —
# 처음 보는 TTS 엔진(edge-tts, 12/12)과 한국어 실제 인간 발화(Zeroth-Korean, 12/12) —
# 에서 완벽하게 분리했다. 유일한 오탐은 LibriSpeech 자연 발화 1건(11/12).

import json
import wave
from pathlib import Path

import pytest

from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter
from src.infrastructure.adapters.wav2vec2_deepvoice_adapter import Wav2Vec2DeepvoiceAdapter

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "deepvoice_generalization_samples"
MANIFEST = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))


def _load(sample: dict) -> bytes:
    return (DATA_DIR / sample["path"]).read_bytes()


def _source_group(sample: dict) -> str:
    return sample["source"].split(" (")[0]


ALL_SAMPLES = MANIFEST["samples"]
_GROUPS = {"gTTS", "edge-tts", "hf-internal-testing/librispeech_asr_dummy", "kresnik/zeroth_korean"}


@pytest.fixture(scope="module")
def adapter() -> Wav2Vec2DeepvoiceAdapter:
    return Wav2Vec2DeepvoiceAdapter(fallback=HeuristicDeepvoiceAdapter())


def test_dataset_files_exist_and_cover_four_groups():
    """48건(그룹당 12건), 파일이 실제로 존재하고 유효한 WAV인지 먼저 확인 — 이게
    깨지면 아래 정확도 테스트가 축소된 표본으로 조용히 통과해버려 의미가 없다."""
    assert len(ALL_SAMPLES) == 48
    groups = {_source_group(s) for s in ALL_SAMPLES}
    assert groups == _GROUPS
    for group in _GROUPS:
        assert sum(1 for s in ALL_SAMPLES if _source_group(s) == group) == 12
    for sample in ALL_SAMPLES:
        path = DATA_DIR / sample["path"]
        assert path.exists(), f"{sample['id']}: {path} 없음"
        with wave.open(str(path), "rb") as wf:
            assert wf.getnframes() > 0


def test_overall_accuracy_is_at_least_47_of_48(adapter):
    """실측 47/48(97.9%) — 이보다 낮아지면 모델/전처리에 회귀가 생겼다는 신호다."""
    correct = sum(
        1 for s in ALL_SAMPLES if adapter.analyze(_load(s)).is_synthetic == (s["label"] == "tts")
    )
    assert correct >= 47, f"48건 중 {correct}건만 정확 (기대: 47건 이상)"


def test_generalizes_to_unseen_tts_engine_edge_tts(adapter):
    """보정 데이터셋(gTTS만)에 없던 TTS 엔진(edge-tts, Microsoft 신경망 TTS)도 전부
    합성으로 정확히 판별해야 한다 — "gTTS 특유의 아티팩트만 외웠다"는 우려에 대한
    직접적인 반증."""
    edge_samples = [s for s in ALL_SAMPLES if _source_group(s) == "edge-tts"]
    hits = sum(1 for s in edge_samples if adapter.analyze(_load(s)).is_synthetic is True)
    assert hits == 12, f"edge-tts 12건 중 {hits}건만 합성으로 판별됨"


def test_generalizes_to_korean_natural_speech_language_confound_control(adapter):
    """보정 데이터셋의 자연 발화(LibriSpeech)는 전부 영어였다 — "합성 여부가 아니라
    언어를 구분한 것 아니냐"는 교란 요인을 통제하기 위해, 한국어 실제 인간 발화
    (Zeroth-Korean)도 전부 자연 발화로 정확히 판별하는지 확인한다."""
    ko_natural_samples = [s for s in ALL_SAMPLES if _source_group(s) == "kresnik/zeroth_korean"]
    hits = sum(1 for s in ko_natural_samples if adapter.analyze(_load(s)).is_synthetic is False)
    assert hits == 12, f"한국어 자연 발화 12건 중 {hits}건만 정확히 판별됨"


def test_verdicts_always_include_explanation_for_n04(adapter):
    """N-04(설명가능성): 48건 전부 blackbox 판정 없이 근거를 동반해야 한다."""
    for sample in ALL_SAMPLES:
        verdict = adapter.analyze(_load(sample))
        assert verdict.explanation
