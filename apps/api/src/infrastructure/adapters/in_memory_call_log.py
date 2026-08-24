# N-01 감사증적의 아주 단순한 v1 — 프로세스 메모리에만 쌓이고 재시작하면 사라진다.
# domain/ports.py의 CallLogPort를 구현한다.
#
# TODO: postgres로 교체. N-01(감사증적)은 "변경 불가(append-only)" 로그를 요구하므로,
#       실제로는 UPDATE/DELETE 권한이 없는 전용 감사 스키마로 설계하는 것을 고려할 것
#       (지금 이 인메모리 구현은 리스트에 append만 하므로 논리적으로는 append-only이지만,
#        프로세스 재시작 시 사라지므로 "감사증적"이라 부르기엔 아직 미흡함).

from collections import Counter

from src.domain.entities import CallAnalysisResult, CategoryCount, RiskLevel, StatsSummary


class InMemoryCallLogRepository:
    def __init__(self):
        self._records: list[CallAnalysisResult] = []

    def add(self, result: CallAnalysisResult) -> None:
        self._records.append(result)

    def list_recent(self, limit: int) -> list[CallAnalysisResult]:
        return list(reversed(self._records[-limit:]))

    def stats_summary(self) -> StatsSummary:
        risk_level_counts = Counter(r.risk_level.value for r in self._records)

        category_counter: Counter = Counter()
        category_labels: dict[str, str] = {}
        for record in self._records:
            for pattern in record.detected_patterns:
                category_counter[pattern.category] += 1
                category_labels[pattern.category] = pattern.category_label

        category_counts = [
            CategoryCount(category=category, category_label=category_labels[category], count=count)
            for category, count in category_counter.most_common()
        ]

        return StatsSummary(
            total_analyzed=len(self._records),
            risk_level_counts={level.value: risk_level_counts.get(level.value, 0) for level in RiskLevel},
            category_counts=category_counts,
        )
