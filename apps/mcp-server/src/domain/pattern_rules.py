# F-01 패턴 탐지 규칙 정의.
#
# 지금은 키워드 기반 규칙(rule-based)으로 시작한다. RFP 5장 제약사항에 따라 실제
# 보이스피싱 통화 녹음은 사용할 수 없으므로, 아래 키워드는 뉴스·경찰청/금융감독원이
# 공개적으로 설명하는 보이스피싱 수법(기관사칭, 공포조성, 긴급송금유도 등)을 참고해
# 직접 정리한 예시 목록이다 (실제 사건 녹취록이 아님).
#
# 2026-08-28: data/synthetic_call_transcripts.json(합성 데이터셋, docs/RFP.md 4장)로
# 정밀도/재현율을 검증했다 (tests/test_synthetic_dataset_calibration.py 참고).
#   - 정밀도: 정상 통화 대조군 6건 전부 0점 — 오탐 없음.
#   - 재현율: 키워드와 정확히 겹치는 "교과서적" 문구는 15건 전부 정확히 탐지.
#     다만 같은 수법을 자연스러운 구어체로 표현하면(가족사칭/지인사칭/대출빙자/환급빙자
#     등, G-01~G-05) 이 키워드 목록은 전부 놓친다 — 기관명/금융 전문용어가 없는 문장은
#     애초에 이 리스트가 다루는 어휘 범위 밖이기 때문. 이게 규칙 기반 → LLM 기반(v2,
#     ollama_call_analysis_adapter.py) 전환이 필요했던 실제 근거였고, 실측 결과 v2는
#     이 사각지대 5건 중 4건(G-01/G-03/G-04/G-05)을 고위험으로 정확히 잡아낸다
#     (나머지 1건 G-02는 URL 스미싱이라 v1/v2 모두 놓침 — 공격 벡터 자체가 다름).
# TODO: 위 사각지대 중 재사용 가능한 어휘(예: "합의금", "핸드폰이 고장나서")를
#       키워드로 추가할지는 별도 검토 — 지금 이 리스트는 "기관사칭형" 어휘 중심이라
#       가족/지인 사칭형 자연어를 섣불리 추가하면 오탐이 늘 수 있다(정상적인 가족 간
#       급전 요청과 구분이 어려움). LLM 백엔드가 기본값인 지금은 우선순위가 낮다.
#
# N-06(확장성): 새 카테고리를 추가하려면
#   1) domain/entities.py의 PatternCategory에 항목 추가
#   2) 아래 PATTERN_RULES에 키워드셋 추가
#   3) 아래 CATEGORY_WEIGHTS에 F-02 위험도 가중치 추가
# 만 하면 되고, 탐지/스코어링 로직(application/services.py)은 수정할 필요가 없다.

from .entities import PatternCategory

PATTERN_RULES: dict[PatternCategory, list[str]] = {
    PatternCategory.AUTHORITY_IMPERSONATION: [
        "검찰청",
        "검찰",
        "검사입니다",
        "경찰청",
        "금융감독원",
        "금감원",
        "국세청",
        "법원",
        "수사관",
        "형사님",
        "제 신분증을 보여드리겠습니다",
        "은행 보안팀",
        "금융결제원",
    ],
    PatternCategory.FEAR_INDUCEMENT: [
        "체포영장",
        "구속영장",
        "구속",
        "체포",
        "수사 대상",
        "범죄에 연루",
        "명의도용",
        "계좌가 범죄에 이용",
        "출금 정지",
        "계좌 동결",
        "불이익을 받으실 수",
        "형사처벌",
    ],
    PatternCategory.URGENT_TRANSFER: [
        "지금 즉시",
        "당장 송금",
        "즉시 이체",
        "안전계좌",
        "안전 계좌로 옮기",
        "현금을 인출",
        "대포통장",
        "직접 만나서 전달",
        "원격조종 프로그램",
        "앱을 설치",
        "인증번호를 알려주",
    ],
    PatternCategory.PERSONAL_INFO_REQUEST: [
        "주민등록번호",
        "계좌번호와 비밀번호",
        "보안카드 번호",
        "OTP 번호",
        "공인인증서 비밀번호",
    ],
}


# F-02 위험도 스코어링 가중치.
#
# 카테고리 하나가 매칭될 때마다 해당 가중치를 더하고(최대 100점), 점수 구간에 따라
# 저/중/고 등급을 매긴다 (domain/entities.py의 RISK_LEVEL_THRESHOLDS 참고).
# 설계 의도: 실제 보이스피싱은 "기관사칭 + 공포조성 + 긴급송금유도"가 함께 등장하는
# 경우가 전형적이므로, 카테고리가 여러 개 겹칠수록 합산 점수가 빠르게 高등급으로
# 올라가도록 가중치를 잡았다 (단일 카테고리만 매칭되면 저위험, 3개 겹치면 고위험).
#
# 2026-08-28: data/synthetic_call_transcripts.json으로 점수 분포를 검증한 결과, 이
# 가중치 조합은 위 설계 의도(1개 카테고리→저위험, 2개→중위험, 3개 이상→고위험)를
# 정확히 만족한다 — 2개 카테고리 조합 6가지 전부 40~69점(중위험) 구간에, 3개 이상
# 조합 5가지 전부 70점 이상(고위험)에 들어간다. 가중치/임계값(entities.py의
# RISK_LEVEL_THRESHOLDS) 변경 불필요.
CATEGORY_WEIGHTS: dict[PatternCategory, int] = {
    PatternCategory.AUTHORITY_IMPERSONATION: 30,
    PatternCategory.FEAR_INDUCEMENT: 30,
    PatternCategory.URGENT_TRANSFER: 35,
    PatternCategory.PERSONAL_INFO_REQUEST: 25,
}
