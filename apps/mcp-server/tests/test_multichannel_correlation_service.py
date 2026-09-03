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


# --- 우선순위 2(선택 항목): Google Safe Browsing 결합 ---

_URL = ExtractedEntity(EntityType.URL, "evil.example.com")


class _FakeThreatIntelligence:
    def __init__(self, flagged: list[str] | None = None):
        self._flagged = flagged or []
        self.received: list[str] | None = None

    def check_urls(self, urls: list[str]) -> list[str]:
        self.received = urls
        return [u for u in urls if u in self._flagged]


def test_malicious_url_produces_risk_boost_and_reason_even_without_channel_match():
    repo = _FakeChannelSignalRepository(matches=[])  # 크로스채널 매치 없음(첫 등장)
    threat_intel = _FakeThreatIntelligence(flagged=["evil.example.com"])
    service = MultichannelCorrelationService(repo, threat_intelligence_port=threat_intel)

    result = service.correlate(Channel.SMS, [_URL], occurred_at=_NOW, context_excerpt="문자 발췌")

    assert result.risk_boost == 40
    assert result.flagged_urls == ["evil.example.com"]
    assert result.matches == []  # 크로스채널 매치는 여전히 없음(근거가 분리돼 있음)
    assert any("Google Safe Browsing" in r for r in result.reasons)
    assert any("evil.example.com" in r for r in result.reasons)


def test_channel_match_and_malicious_url_boosts_combine():
    match = CorrelationMatch(EntityType.URL, "evil.example.com", Channel.CALL, _NOW, "통화 발췌")
    repo = _FakeChannelSignalRepository(matches=[match])
    threat_intel = _FakeThreatIntelligence(flagged=["evil.example.com"])
    service = MultichannelCorrelationService(repo, threat_intelligence_port=threat_intel)

    result = service.correlate(Channel.SMS, [_URL], occurred_at=_NOW, context_excerpt="문자 발췌")

    assert result.risk_boost == 15 + 40  # 크로스채널 매치 1건 + 악성 URL 확인


def test_only_non_flagged_url_produces_no_boost():
    repo = _FakeChannelSignalRepository(matches=[])
    threat_intel = _FakeThreatIntelligence(flagged=[])  # Safe Browsing이 아무것도 안 걸림
    service = MultichannelCorrelationService(repo, threat_intelligence_port=threat_intel)

    result = service.correlate(Channel.SMS, [_URL], occurred_at=_NOW, context_excerpt="문자 발췌")

    assert result.risk_boost == 0
    assert result.flagged_urls == []


def test_threat_intelligence_receives_only_url_entities():
    repo = _FakeChannelSignalRepository(matches=[])
    threat_intel = _FakeThreatIntelligence()
    service = MultichannelCorrelationService(repo, threat_intelligence_port=threat_intel)

    service.correlate(Channel.SMS, [_PHONE, _URL], occurred_at=_NOW, context_excerpt="문자 발췌")

    assert threat_intel.received == ["evil.example.com"]


def test_multiple_flagged_urls_do_not_multiply_boost():
    """확인된 악성 URL이 몇 개든 가산점은 한 번만 — services.py 상단 주석 참고."""
    urls = [ExtractedEntity(EntityType.URL, "evil1.example.com"), ExtractedEntity(EntityType.URL, "evil2.example.com")]
    repo = _FakeChannelSignalRepository(matches=[])
    threat_intel = _FakeThreatIntelligence(flagged=["evil1.example.com", "evil2.example.com"])
    service = MultichannelCorrelationService(repo, threat_intelligence_port=threat_intel)

    result = service.correlate(Channel.SMS, urls, occurred_at=_NOW, context_excerpt="문자 발췌")

    assert result.risk_boost == 40
    assert set(result.flagged_urls) == {"evil1.example.com", "evil2.example.com"}


def test_no_threat_intelligence_port_is_a_no_op():
    repo = _FakeChannelSignalRepository(matches=[])
    service = MultichannelCorrelationService(repo)  # threat_intelligence_port 없음

    result = service.correlate(Channel.SMS, [_URL], occurred_at=_NOW, context_excerpt="문자 발췌")

    assert result.risk_boost == 0
    assert result.flagged_urls == []
