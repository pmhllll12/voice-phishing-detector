# PostgresChannelSignalRepository를 실제 로컬 postgres(docker vps-postgres, infra/db/init.sql
# 스키마)로 검증하는 통합 테스트. 격리 전략/스킵 조건은 test_postgres_report_repository.py와
# 동일 — 그쪽 상단 주석 참고.

import datetime
import os
import pathlib
import uuid

import psycopg
import pytest

from domain.entities import Channel, ChannelSignal, EntityType, ExtractedEntity
from infrastructure.adapters.postgres_channel_signal_repository import PostgresChannelSignalRepository

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vps_app:vps_dev_password@localhost:5432/vps_detector"
)
INIT_SQL = (pathlib.Path(__file__).resolve().parent.parent.parent.parent / "infra" / "db" / "init.sql").read_text(
    encoding="utf-8"
)

try:
    psycopg.connect(TEST_DSN, connect_timeout=2).close()
    _POSTGRES_AVAILABLE = True
except psycopg.OperationalError:
    _POSTGRES_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _POSTGRES_AVAILABLE, reason="로컬 postgres(vps-postgres)가 떠 있지 않음")


@pytest.fixture
def repository():
    schema = f"test_{uuid.uuid4().hex[:8]}"
    setup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    setup_conn.execute(f"CREATE SCHEMA {schema}")
    setup_conn.execute(f"SET search_path TO {schema}, public")
    setup_conn.execute(INIT_SQL)
    setup_conn.close()

    repo = PostgresChannelSignalRepository(TEST_DSN, options=f"-c search_path={schema}")
    yield repo

    cleanup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    cleanup_conn.execute(f"DROP SCHEMA {schema} CASCADE")
    cleanup_conn.close()


_NOW = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.timezone.utc)
_PHONE = ExtractedEntity(EntityType.PHONE, "01012345678")
_ACCOUNT = ExtractedEntity(EntityType.ACCOUNT, "12345678901234")


def test_find_matches_returns_empty_when_nothing_recorded_yet(repository):
    matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)

    assert matches == []


def test_find_matches_finds_same_entity_in_a_different_channel_within_window(repository):
    repository.record(ChannelSignal(Channel.SMS, [_PHONE], _NOW - datetime.timedelta(minutes=12), "문자 발췌"))

    matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)

    assert len(matches) == 1
    assert matches[0].matched_channel == Channel.SMS
    assert matches[0].entity_value == "01012345678"


def test_find_matches_excludes_same_channel_signals(repository):
    repository.record(ChannelSignal(Channel.CALL, [_PHONE], _NOW - datetime.timedelta(minutes=5), "통화 발췌"))

    matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)

    assert matches == []


def test_find_matches_excludes_signals_outside_time_window(repository):
    repository.record(ChannelSignal(Channel.SMS, [_PHONE], _NOW - datetime.timedelta(minutes=45), "문자 발췌"))

    matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)

    assert matches == []


def test_find_matches_only_matches_requested_entities(repository):
    repository.record(ChannelSignal(Channel.SMS, [_ACCOUNT], _NOW - datetime.timedelta(minutes=5), "문자 발췌"))

    matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)

    assert matches == []


def test_record_with_multiple_entities_are_all_queryable(repository):
    repository.record(ChannelSignal(Channel.EMAIL, [_PHONE, _ACCOUNT], _NOW - datetime.timedelta(minutes=1), "이메일 발췌"))

    phone_matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)
    account_matches = repository.find_matches([_ACCOUNT], Channel.CALL, _NOW, window_seconds=1800)

    assert len(phone_matches) == 1
    assert len(account_matches) == 1


def test_record_with_no_entities_is_a_no_op(repository):
    repository.record(ChannelSignal(Channel.SMS, [], _NOW, "빈 신호"))

    matches = repository.find_matches([_PHONE], Channel.CALL, _NOW, window_seconds=1800)

    assert matches == []


def test_ping_succeeds_when_reachable(repository):
    repository.ping()
