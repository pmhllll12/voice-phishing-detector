# 실제 보이스피싱/딥보이스 음성 샘플은 쓸 수 없으므로(docs/RFP.md 4장 데이터 제약),
# numpy로 직접 합성한 WAV 신호로 휴리스틱의 "동작"을 검증한다. 이 테스트는 딥보이스
# 탐지 "정확도"를 검증하는 것이 아니라, 각 지표(피치/스펙트럼/묵음)가 설계 의도대로
# 반응하는지를 검증하는 것이다 — 정확도 검증은 실제 데이터 확보 후 별도로 필요하다.

import io
import wave

import numpy as np
import pytest

from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter

SAMPLE_RATE = 16000


def _make_wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE, sample_width: int = 2) -> bytes:
    samples = np.clip(samples, -1.0, 1.0)
    int_samples = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(int_samples.tobytes())
    return buf.getvalue()


def _make_monotone_signal(duration: float = 3.0, freq: float = 150.0) -> np.ndarray:
    """완벽하게 일정한 순음 — 피치/스펙트럼이 전혀 변하지 않는, 합성음 유사 신호."""
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    return 0.5 * np.sin(2 * np.pi * freq * t)


def _make_natural_like_signal(seed: int = 42) -> np.ndarray:
    """피치가 랜덤워크로 흔들리고, 잡음이 섞이고, 묵음 길이가 불규칙한 육성 유사 신호."""
    rng = np.random.default_rng(seed)
    segments = []
    for _ in range(6):
        word_duration = rng.uniform(0.3, 0.6)
        n_samples = int(word_duration * SAMPLE_RATE)
        freq_base = rng.uniform(120, 220)
        freq_track = freq_base + np.cumsum(rng.normal(0, 3, n_samples))
        phase = 2 * np.pi * np.cumsum(freq_track) / SAMPLE_RATE
        tone = 0.5 * np.sin(phase)
        noise = rng.normal(0, 0.02, n_samples)
        segments.append(tone + noise)

        pause_duration = rng.uniform(0.1, 0.5)
        n_pause = int(pause_duration * SAMPLE_RATE)
        segments.append(rng.normal(0, 0.001, n_pause))

    return np.concatenate(segments)


@pytest.fixture
def adapter() -> HeuristicDeepvoiceAdapter:
    return HeuristicDeepvoiceAdapter()


def test_perfectly_stable_tone_is_flagged_as_synthetic_like(adapter):
    wav_bytes = _make_wav_bytes(_make_monotone_signal())
    verdict = adapter.analyze(wav_bytes)

    assert verdict.is_synthetic is True
    triggered_names = {i.name for i in verdict.indicators if i.triggered}
    assert "pitch_stability" in triggered_names
    assert "spectral_uniformity" in triggered_names


def test_natural_like_variation_is_not_flagged(adapter):
    wav_bytes = _make_wav_bytes(_make_natural_like_signal())
    verdict = adapter.analyze(wav_bytes)

    assert verdict.is_synthetic is False
    assert all(not i.triggered for i in verdict.indicators)


def test_too_short_audio_defers_judgement(adapter):
    wav_bytes = _make_wav_bytes(np.zeros(100))
    verdict = adapter.analyze(wav_bytes)

    assert verdict.is_synthetic is None
    assert verdict.confidence == 0.0


def test_explanation_cites_triggered_indicators(adapter):
    wav_bytes = _make_wav_bytes(_make_monotone_signal())
    verdict = adapter.analyze(wav_bytes)

    assert "pitch_stability" in verdict.explanation
    assert "spectral_uniformity" in verdict.explanation


def test_unsupported_sample_width_raises_value_error(adapter):
    wav_bytes = _make_wav_bytes(_make_monotone_signal(duration=0.5), sample_width=1)

    with pytest.raises(ValueError, match="16-bit PCM"):
        adapter.analyze(wav_bytes)
