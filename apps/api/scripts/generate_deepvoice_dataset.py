# F-03 딥보이스 데이터셋(data/deepvoice_samples/) 생성 스크립트. 실제 보이스피싱 녹음은
# 쓸 수 없으므로(docs/RFP.md 4장), 대신 라이선스가 명확한 두 실측 소스를 조합한다:
#
#   tts/      - gTTS(Google Translate TTS)가 실제로 합성한 한국어 음성 8건. gTTS는
#               API 키 없이 쓸 수 있는 공개 TTS 엔진이라 "공개 TTS 합성 음성"이라는
#               조건을 문자 그대로 만족한다. 문장은 이 프로젝트의 통화 시나리오
#               (mcp-server/data/synthetic_call_transcripts.json)와 결이 맞게 직접 작성.
#   natural/  - HuggingFace의 hf-internal-testing/librispeech_asr_dummy(LibriSpeech
#               clean validation split, CC BY 4.0)에서 뽑은 실제 인간 발화 8건. 저작권이
#               불분명한 오디오를 임의로 가져오는 대신, ML 커뮤니티에서 정확히 이런
#               가벼운 데모/테스트 용도로 널리 쓰이는 표준 공개 데이터셋을 썼다. 영어
#               발화이지만 이 데이터셋의 목적은 "무슨 말을 하는가"가 아니라 피치 지터/
#               스펙트럼 평탄도/묵음 규칙성 같은 언어 독립적 음향 통계이므로 문제되지
#               않는다.
#
# 재생성 방법: requirements-datagen.txt 참고(반드시 별도 venv, apps/api/.venv를
# 오염시키지 말 것). ffmpeg 시스템 바이너리 필요.
#
# 실행 후 apps/api/data/deepvoice_samples/{tts,natural}/*.wav + manifest.json이
# 갱신된다 — manifest.json의 text 필드는 이 스크립트의 SENTENCES/자동 추출 텍스트와
# 수동으로 맞춰져 있으니, 문장을 바꾸면 manifest.json도 함께 갱신할 것.

import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "deepvoice_samples"
TTS_DIR = DATA_DIR / "tts"
NATURAL_DIR = DATA_DIR / "natural"

# F-01/F-02 합성 데이터셋과 같은 결의 시나리오 문장(보이스피싱 유형) + 일상 대화(대조군).
TTS_SENTENCES = [
    "안녕하세요, 오늘 날씨가 정말 좋네요.",
    "검찰청 수사관인데 계좌가 범죄에 연루되어 지금 즉시 안전계좌로 이체해야 합니다.",
    "택배가 반송된다는 문자를 받았는데 링크를 눌렀더니 앱이 설치됐어요.",
    "고객님의 계좌가 명의도용으로 사용되었습니다. 본인 확인이 필요합니다.",
    "회의는 오후 세 시에 시작할 예정이니 늦지 않게 참석해 주세요.",
    "아버지 저 핸드폰 액정이 깨져서 지금 이 번호로 통화하고 있어요.",
    "금융감독원에서 안내드립니다. 고객님 명의로 대포통장이 개설되었습니다.",
    "오늘 점심 메뉴는 김치찌개와 계란말이입니다.",
]

# LibriSpeech clean validation의 73건 중, 오디오 길이(바이트 크기)로 얼추 2~6초대
# 발화만 골라 처음 8건을 쓴다 — 너무 짧으면 MIN_VOICED_FRAMES(deepvoice_adapter.py)
# 미달로 판단 보류되고, 너무 길면 커밋 용량만 커진다.
NATURAL_MIN_BYTES = 30_000
NATURAL_MAX_BYTES = 120_000
NATURAL_COUNT = 8


def generate_tts_samples() -> None:
    from gtts import gTTS

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(TTS_SENTENCES):
        mp3_path = TTS_DIR / f"tts_{i}.mp3"
        wav_path = TTS_DIR / f"tts_{i}.wav"
        gTTS(text, lang="ko").save(str(mp3_path))
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", str(wav_path)],
            check=True,
            capture_output=True,
        )
        mp3_path.unlink()
        print(f"tts/{wav_path.name} <- {text[:30]!r}")


def generate_natural_samples() -> None:
    import io
    import wave

    import pyarrow.parquet as pq
    import soundfile as sf
    from huggingface_hub import hf_hub_download

    NATURAL_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = hf_hub_download(
        repo_id="hf-internal-testing/librispeech_asr_dummy",
        repo_type="dataset",
        filename="clean/validation-00000-of-00001.parquet",
    )
    rows = pq.read_table(parquet_path).to_pylist()
    candidates = sorted(rows, key=lambda r: len(r["audio"]["bytes"]))
    chosen = [r for r in candidates if NATURAL_MIN_BYTES < len(r["audio"]["bytes"]) < NATURAL_MAX_BYTES][:NATURAL_COUNT]

    for i, row in enumerate(chosen):
        data, sample_rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="int16")
        wav_path = NATURAL_DIR / f"natural_{i}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(data.tobytes())
        print(f"natural/{wav_path.name} <- {row['text'][:30]!r}")


if __name__ == "__main__":
    generate_tts_samples()
    generate_natural_samples()
    print(
        "\n완료. manifest.json의 text 필드가 위 출력과 어긋나면 수동으로 맞춰줄 것 "
        "(재생성 시 gTTS/LibriSpeech 선택 순서가 달라질 수 있음).",
        file=sys.stderr,
    )
