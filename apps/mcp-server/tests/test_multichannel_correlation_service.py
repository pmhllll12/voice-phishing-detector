# MultichannelCorrelationService 단위 테스트 — 실제 DB 없이 가짜 저장소로 검증한다.
# postgres 연동 자체는 tests/test_postgres_channel_signal_repository.py에서 검증한다.

import datetime

from application.services import MultichannelCorrelationService
from domain.entities import Channel, ChannelSignal, CorrelationMatch, EntityType, ExtractedEntity, RiskLevel


class _FakeChannelSignalRepository:
    def __init__(self, matches: list[CorrelationMatch] | None = None):
        self._matches = matches or []
        self.recorded: list[ChannelSignal] = []

    def record(self, signal: ChannelSignal) -> None:
        self.recorded.append(signal)

    def find_matches(self, entities, exclude_channel, occurred_at, window_seconds) -> list[CorrelationMatch]:
        return self._matches


_NOW = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.timezone.utc)
_PHONE = ExtractedEntity(EntityType.PHONE, "01012345678")


def test_records_signal_even_when_no_matches_found():
    repo = _FakeChannelSignalRepository(matches=[])
    service = MultichannelCorrelationService(repo)

    result = service.correlate(Channel.CALL, [_PHONE], occurred_at=_NOW, context_excerpt="통화 발췌")

    assert result.matches == []
    assert result.risk_boost == 0
    assert len(repo.recorded) == 1
    assert repo.recorded[0].channel == Channel.CALL
    assert repo.recorded[0].entities == [_PHONE]


def test_match_in_another_channel_produces_risk_boost_and_reason():
    match = CorrelationMatch(
        entity_type=EntityType.PHONE,
        entity_value="01012345678",
        matched_channel=Channel.SMS,
        matched_at=_NOW - datetime.timedelta(minutes=12),
        context_excerpt="문자 발췌",
    )
    repo = _FakeChannelSignalRepository(matches=[match])
    service = MultichannelCorrelationService(repo)

    result = service.correlate(Channel.CALL, [_PHONE], occurred_at=_NOW, context_excerpt="통화 발췌")

    assert result.risk_boost == 15
    assert len(result.matches) == 1
    assert "12분 전 문자 채널" in result.reasons[0]
    assert "5678" in result.reasons[0]  # 표시값은 끝 4자리만 남기고 마스킹됨
    assert not result.reasons[0].startswith("12분 전 문자 채널에서 동일 전화번호(01012345678)")


def test_risk_boost_is_capped_when_many_matches():
    matches = [
        CorrelationMatch(EntityType.PHONE, "01012345678", Channel.SMS, _NOW, "발췌1"),
        CorrelationMatch(EntityType.ACCOUNT, "12345678901234", Channel.EMAIL, _NOW, "발췌2"),
        CorrelationMatch(EntityType.URL, "evil.example.com", Channel.SMS, _NOW, "발췌3"),
    ]
    repo = _FakeChannelSignalRepository(matches=matches)
    service = MultichannelCorrelationService(repo)

    result = service.correlate(Channel.CALL, [_PHONE], occurred_at=_NOW, context_excerpt="통화 발췌")

    assert result.risk_boost == 30  # 3건 * 15점 = 45점이지만 상한(30점)에서 잘림


def test_updated_risk_score_and_level_are_none_without_current_risk_score():
    match = CorrelationMatch(EntityType.PHONE, "01012345678", Channel.SMS, _NOW, "발췌")
    repo = _FakeChannelSignalRepository(matches=[match])
    service = MultichannelCorrelationService(repo)

    result = service.correlate(Channel.CALL, [_PHONE], occurred_at=_NOW, context_excerpt="통화 발췌")

    assert result.updated_risk_score is None
    assert result.updated_risk_level is None


def test_updated_risk_score_is_recomputed_and_capped_at_100_when_current_risk_score_given():
    match = CorrelationMatch(EntityType.PHONE, "01012345678", Channel.SMS, _NOW, "발췌")
    repo = _FakeChannelSignalRepository(matches=[match])
    service = MultichannelCorrelationService(repo)

    result = service.correlate(
        Channel.CALL, [_PHONE], occurred_at=_NOW, context_excerpt="통화 발췌", current_risk_score=95
    )

    assert result.updated_risk_score == 100
    assert result.updated_risk_level == RiskLevel.HIGH


def test_no_entities_skips_lookup_and_record():
    repo = _FakeChannelSignalRepository(matches=[CorrelationMatch(EntityType.PHONE, "x", Channel.SMS, _NOW, "y")])
    service = MultichannelCorrelationService(repo)

    result = service.correlate(Channel.CALL, [], occurred_at=_NOW, context_excerpt="통화 발췌")

    assert result.matches == []
    assert repo.recorded == []
