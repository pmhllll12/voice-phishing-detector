# F-03 딥보이스 판별기(v2, wav2vec2)의 "일반화" 검증용 홀드아웃 데이터셋을 만든다.
#
# WHY 기존 data/deepvoice_samples/(16건, F-03 임계값 실측 보정용)와 별도 폴더인가:
# 그 데이터셋으로 "일반화된다"까지 주장하면 순환 논증이다(같은 데이터로 보정하고 같은
# 데이터로 검증) — 그리고 그 데이터셋은 TTS=한국어(gTTS)/자연발화=영어(LibriSpeech)로
# 언어가 갈려있어서, "완벽 분리"가 합성 여부가 아니라 언어를 구분한 결과일 수 있다는
# 교란 요인이 있다(docs/design.md 6장? 아님 — N-06 "확장성이 아직 검증 안 된 지점"
# 참고). 이 스크립트는 그 두 문제를 동시에 해결하는 새 홀드아웃 세트를 만든다:
#
#   tts_gtts/        - gTTS(기존과 동일 엔진) 한국어 합성 음성 12건, 새 문장
#   tts_edge/        - edge-tts(마이크로소프트 신경망 TTS, 완전히 다른 엔진/보이스)
#                      한국어 합성 음성 12건 — "엔진이 바뀌어도 잡는가"를 검증
#   natural_librispeech/ - 기존과 같은 소스(LibriSpeech clean validation, CC BY 4.0)의
#                      새 발화 12건(기존 8건과 겹치지 않는 인덱스)
#   natural_zeroth_ko/   - Zeroth-Korean(kresnik/zeroth_korean, CC BY 4.0) 테스트 스플릿
#                      한국어 실제 인간 발화 12건 — "언어를 한국어로 맞춰도 자연 발화를
#                      자연 발화로 정확히 구분하는가"를 검증(언어 교란 요인 통제)
#
# 재생성 방법: apps/api/scripts/requirements-datagen.txt에 edge-tts 추가해서 별도
# venv에 설치(gTTS 스크립트 상단 주석과 동일한 이유 — apps/api/.venv를 오염시키지 말 것).
# ffmpeg 시스템 바이너리 필요.

import io
import subprocess
import wave
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "deepvoice_generalization_samples"

# F-01/F-02 합성 데이터셋과 같은 결의 시나리오 문장 — 기존 8건(generate_deepvoice_dataset.py)과
# 겹치지 않는 새 문장 12개.
SENTENCES = [
    "국세청인데 세금 환급 대상이라 계좌번호를 확인해야 합니다.",
    "택배 주소가 잘못되어 재배송료 결제가 필요하다고 문자가 왔어요.",
    "경찰서인데 본인 명의 계좌가 대포통장으로 신고되었습니다.",
    "카드사에서 안내드립니다. 해외 결제가 승인되었는데 본인 결제가 맞으신가요.",
    "내일 오전 아홉 시까지 회의실로 서류를 가져다주세요.",
    "엄마 나 폰 액정 깨져서 임시로 이 번호 쓰고 있어요.",
    "저희는 신용회복위원회입니다. 채무 조정 상담을 도와드리겠습니다.",
    "오늘 저녁에는 비가 온다고 하니 우산 챙기세요.",
    "법원인데 소송 서류가 반송되어 새 주소 확인이 필요합니다.",
    "동생이 사고가 나서 병원비가 급하게 필요하다고 연락이 왔어요.",
    "다음 주 화요일에 프로젝트 발표가 예정되어 있습니다.",
    "인터넷 쇼핑몰에서 주문하신 상품이 품절되어 환불 처리됩니다.",
]

TTS_MIN_BYTES = 30_000
TTS_MAX_BYTES = 200_000
NATURAL_MIN_BYTES = 30_000
NATURAL_MAX_BYTES = 120_000
NATURAL_COUNT = 12

EDGE_TTS_VOICE = "ko-KR-SunHiNeural"


def _mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", str(wav_path)],
        check=True,
        capture_output=True,
    )
    mp3_path.unlink()


def generate_gtts_samples() -> list[dict]:
    from gtts import gTTS

    out_dir = DATA_DIR / "tts_gtts"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, text in enumerate(SENTENCES):
        mp3_path = out_dir / f"tts_gtts_{i}.mp3"
        wav_path = out_dir / f"tts_gtts_{i}.wav"
        gTTS(text, lang="ko").save(str(mp3_path))
        _mp3_to_wav(mp3_path, wav_path)
        print(f"tts_gtts/{wav_path.name} <- {text[:30]!r}")
        manifest.append(
            {
                "id": f"gen_tts_gtts_{i}",
                "path": f"tts_gtts/{wav_path.name}",
                "label": "tts",
                "source": "gTTS (Google Translate TTS, ko)",
                "text": text,
            }
        )
    return manifest


def generate_edge_tts_samples() -> list[dict]:
    import asyncio

    import edge_tts

    out_dir = DATA_DIR / "tts_edge"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    async def _synthesize(text: str, mp3_path: Path) -> None:
        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
        await communicate.save(str(mp3_path))

    for i, text in enumerate(SENTENCES):
        mp3_path = out_dir / f"tts_edge_{i}.mp3"
        wav_path = out_dir / f"tts_edge_{i}.wav"
        asyncio.run(_synthesize(text, mp3_path))
        _mp3_to_wav(mp3_path, wav_path)
        print(f"tts_edge/{wav_path.name} <- {text[:30]!r}")
        manifest.append(
            {
                "id": f"gen_tts_edge_{i}",
                "path": f"tts_edge/{wav_path.name}",
                "label": "tts",
                "source": f"edge-tts (Microsoft neural TTS, voice={EDGE_TTS_VOICE})",
                "text": text,
            }
        )
    return manifest


def generate_librispeech_samples() -> list[dict]:
    import pyarrow.parquet as pq
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    out_dir = DATA_DIR / "natural_librispeech"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    parquet_path = hf_hub_download(
        repo_id="hf-internal-testing/librispeech_asr_dummy",
        repo_type="dataset",
        filename="clean/validation-00000-of-00001.parquet",
    )
    rows = pq.read_table(parquet_path).to_pylist()
    candidates = sorted(rows, key=lambda r: len(r["audio"]["bytes"]))
    in_range = [r for r in candidates if NATURAL_MIN_BYTES < len(r["audio"]["bytes"]) < NATURAL_MAX_BYTES]
    # 기존 data/deepvoice_samples/의 natural_0~7은 이 정렬에서 가장 작은 8건이다 —
    # 겹치지 않도록 그 뒤(인덱스 8부터)에서 12건을 새로 뽑는다.
    chosen = in_range[8 : 8 + NATURAL_COUNT]

    for i, row in enumerate(chosen):
        data, sample_rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="int16")
        wav_path = out_dir / f"natural_librispeech_{i}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(data.tobytes())
        print(f"natural_librispeech/{wav_path.name} <- {row['text'][:30]!r}")
        manifest.append(
            {
                "id": f"gen_natural_librispeech_{i}",
                "path": f"natural_librispeech/{wav_path.name}",
                "label": "natural",
                "source": "hf-internal-testing/librispeech_asr_dummy (LibriSpeech clean validation split, CC BY 4.0)",
                "text": row["text"],
            }
        )
    return manifest


def generate_zeroth_korean_samples() -> list[dict]:
    import pyarrow.parquet as pq
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    out_dir = DATA_DIR / "natural_zeroth_ko"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    parquet_path = hf_hub_download(
        repo_id="kresnik/zeroth_korean",
        repo_type="dataset",
        filename="data/test-00000-of-00001.parquet",
    )
    rows = pq.read_table(parquet_path).to_pylist()
    candidates = sorted(rows, key=lambda r: len(r["audio"]["bytes"]))
    in_range = [r for r in candidates if NATURAL_MIN_BYTES < len(r["audio"]["bytes"]) < NATURAL_MAX_BYTES]
    chosen = in_range[:NATURAL_COUNT]

    for i, row in enumerate(chosen):
        data, sample_rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="int16")
        wav_path = out_dir / f"natural_zeroth_ko_{i}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(data.tobytes())
        print(f"natural_zeroth_ko/{wav_path.name} <- {row['text'][:30]!r}")
        manifest.append(
            {
                "id": f"gen_natural_zeroth_ko_{i}",
                "path": f"natural_zeroth_ko/{wav_path.name}",
                "label": "natural",
                "source": "kresnik/zeroth_korean (test split, CC BY 4.0)",
                "text": row["text"],
            }
        )
    return manifest


if __name__ == "__main__":
    import json

    all_samples = (
        generate_gtts_samples()
        + generate_edge_tts_samples()
        + generate_librispeech_samples()
        + generate_zeroth_korean_samples()
    )
    manifest = {
        "description": (
            "F-03 v2(wav2vec2) 일반화 검증용 홀드아웃 데이터셋 — data/deepvoice_samples/"
            "(임계값 보정용, 16건)와 별도. TTS 엔진 2종(gTTS/edge-tts) x 자연 발화 언어 2종"
            "(영어 LibriSpeech/한국어 Zeroth-Korean)으로 언어·엔진 교란 요인을 통제했다. "
            "재생성 방법은 generate_deepvoice_generalization_dataset.py 상단 주석 참고."
        ),
        "label_true_for_is_synthetic": "tts",
        "label_false_for_is_synthetic": "natural",
        "samples": all_samples,
    }
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n완료: {len(all_samples)}건, manifest.json 작성됨")
