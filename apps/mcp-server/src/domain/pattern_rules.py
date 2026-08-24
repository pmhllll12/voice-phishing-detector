# F-01 패턴 탐지 규칙 정의.
#
# 지금은 키워드 기반 규칙(rule-based)으로 시작한다. RFP 5장 제약사항에 따라 실제
# 보이스피싱 통화 녹음은 사용할 수 없으므로, 아래 키워드는 뉴스·경찰청/금융감독원이
# 공개적으로 설명하는 보이스피싱 수법(기관사칭, 공포조성, 긴급송금유도 등)을 참고해
# 직접 정리한 예시 목록이다 (실제 사건 녹취록이 아님).
#
# TODO: docs/RFP.md 4장의 합성 데이터셋을 실제로 만든 뒤, 이 키워드 리스트의
#       재현율/정밀도를 검증하고 보강할 것. 이후 규칙 기반 → LLM 기반 분류로
#       고도화 예정 (application/services.py의 PatternDetectionService 참고).
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
# TODO: 합성 데이터셋으로 점수 분포를 검증한 뒤 가중치를 보정할 것.
CATEGORY_WEIGHTS: dict[PatternCategory, int] = {
    PatternCategory.AUTHORITY_IMPERSONATION: 30,
    PatternCategory.FEAR_INDUCEMENT: 30,
    PatternCategory.URGENT_TRANSFER: 35,
    PatternCategory.PERSONAL_INFO_REQUEST: 25,
}
