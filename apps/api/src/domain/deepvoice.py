# domain 계층: F-03 딥보이스(AI 합성 음성) 판별 결과 모델. 외부 의존성 없음.

from dataclasses import dataclass, field


@dataclass
class DeepvoiceIndicator:
    """N-04(설명가능성): 딥보이스 판별에 사용한 개별 음향 지표 하나.

    "합성입니다"라고만 답하지 않고, 어떤 지표가 어떤 값으로 얼마나 벗어났는지를
    항상 함께 반환한다.
    """

    name: str
    description: str
    triggered: bool


@dataclass
class DeepvoiceVerdict:
    is_synthetic: bool | None  # None = 신호 부족 등으로 판단 보류
    confidence: float  # 0.0~1.0
    indicators: list[DeepvoiceIndicator] = field(default_factory=list)
    explanation: str = ""
