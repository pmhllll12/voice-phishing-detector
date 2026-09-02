# 우선순위 2(크로스채널 상관관계 탐지) 시나리오 검증 — data/synthetic_multichannel_signals.json의
# 각 시나리오를 순서대로 재생하며 기대한 시점에만 매칭이 나오는지 확인한다.
# F-01/F-02의 test_synthetic_dataset_calibration.py와 같은 목적(합성 데이터셋으로 실측
# 검증)의 우선순위 2 버전. 실제 postgres 조회 로직 자체는
# test_postgres_channel_signal_repository.py에서 이미 검증했으므로, 여기서는 그 조회
# 규칙(채널 제외/시간 윈도우/엔티티 일치)을 흉내 낸 순수 파이썬 인메모리 저장소로
# MultichannelCorrelationService 전체 흐름만 확인한다.

import datetime
import json
import pathlib

import pytest

from application.services import MultichannelCorrelationService
from domain.entities import Channel, ChannelSignal, CorrelationMatch, EntityType
from domain.entity_extraction import extract_entities

DATA_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "synthetic_multichannel_signals.json"
SCENARIOS = json.loads(DATA_PATH.read_text(encoding="utf-8"))["scenarios"]

_BASE_TIME = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.timezone.utc)
_WINDOW_SECONDS = 30 * 60


class _InMemoryChannelSignalRepository:
    """PostgresChannelSignalRepository.find_matches와 동일한 조회 규칙(채널 다름 +
    시간 윈도우 이내 + 엔티티 일치)을 순수 파이썬으로 재현한다."""

    def __init__(self):
        self._signals: list[ChannelSignal] = []

    def record(self, signal: ChannelSignal) -> None:
        if signal.entities:
            self._signals.append(signal)

    def find_matches(self, entities, exclude_channel, occurred_at, window_seconds) -> list[CorrelationMatch]:
        window = datetime.timedelta(seconds=window_seconds)
        wanted = {(e.entity_type, e.value) for e in entities}
        matches = []
        for signal in self._signals:
            if signal.channel == exclude_channel:
                continue
            if not (occurred_at - window <= signal.occurred_at <= occurred_at + window):
                continue
            for entity in signal.entities:
                if (entity.entity_type, entity.value) in wanted:
                    matches.append(
                        CorrelationMatch(
                            entity_type=entity.entity_type,
                            entity_value=entity.value,
                            matched_channel=signal.channel,
                            matched_at=signal.occurred_at,
                            context_excerpt=signal.context_excerpt,
                        )
                    )
        return matches


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["scenario_id"] for s in SCENARIOS])
def test_scenario_matches_expectations_at_each_step(scenario):
    repository = _InMemoryChannelSignalRepository()
    service = MultichannelCorrelationService(repository, window_seconds=_WINDOW_SECONDS)

    for event in scenario["events"]:
        occurred_at = _BASE_TIME + datetime.timedelta(minutes=event["minutes_offset"])
        entities = extract_entities(event["text"])
        assert entities, f"{scenario['scenario_id']}: 이벤트 텍스트에서 엔티티가 하나도 추출되지 않음 — 시나리오 데이터 확인 필요"

        result = service.correlate(
            Channel(event["channel"]), entities, occurred_at=occurred_at, context_excerpt=event["text"][:200]
        )

        if event["expect_match"]:
            assert result.matches, f"{scenario['scenario_id']}: {event['channel']} 단계에서 매칭이 기대됐지만 없음"
            assert any(m.matched_channel.value == event["expect_matched_channel"] for m in result.matches)
            assert any(m.entity_type.value == event["expect_entity_type"] for m in result.matches)
            assert result.risk_boost > 0
        else:
            assert not result.matches, f"{scenario['scenario_id']}: {event['channel']} 단계에서 매칭이 없어야 하는데 발견됨: {result.matches}"
            assert result.risk_boost == 0
