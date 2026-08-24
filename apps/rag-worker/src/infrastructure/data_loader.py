# infrastructure 계층: 합성 사기사례 데이터셋(JSON) 로딩.
#
# TODO: 지금은 로컬 JSON 파일을 그대로 메모리에 올려서 쓴다. 데이터셋이 커지거나
#       postgres+pgvector로 옮길 때는 이 함수의 반환 타입(list[FraudCase])만
#       유지한 채, 내부 구현을 DB 조회로 바꾸면 된다.

import json
from pathlib import Path

from src.domain.entities import FraudCase

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "fraud_cases.json"


def load_fraud_cases(path: Path = DATA_FILE) -> list[FraudCase]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [FraudCase(**item) for item in raw]
