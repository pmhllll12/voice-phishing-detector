# 우선순위 2(크로스채널 상관관계 탐지): channel_signals(infra/db/init.sql)를 postgres에
# 저장/조회한다. domain/ports.py의 ChannelSignalRepositoryPort를 구현한다.
# 연결/재연결 패턴은 postgres_report_repository.py와 동일 — 그쪽 상단 주석 참고.
#
# channel_signals는 N-01 감사증적(call_analysis_results/report_records)과 성격이
# 다르다 — "판정 원본 기록"이 아니라 "상관관계 조회용 파생 인덱스"라 append-only
# 트리거가 없다(init.sql 참고).

import uuid
from datetime import datetime, timedelta

import psycopg

from domain.entities import Channel, ChannelSignal, CorrelationMatch, EntityType, ExtractedEntity


class PostgresChannelSignalRepository:
    def __init__(self, dsn: str, options: str | None = None):
        self._dsn = dsn
        self._options = options
        self._conn: psycopg.Connection | None = None

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, autocommit=True, options=self._options)

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _execute(self, query: str, params: tuple = ()):
        try:
            return self._get_conn().execute(query, params)
        except psycopg.OperationalError:
            self._conn = self._connect()
            return self._conn.execute(query, params)

    def ping(self) -> None:
        self._execute("SELECT 1")

    def record(self, signal: ChannelSignal) -> None:
        if not signal.entities:
            return
        signal_id = str(uuid.uuid4())
        # autocommit 연결이라 엔티티별 INSERT가 각각 즉시 커밋된다 — 한 signal의 엔티티
        # 여러 개를 원자적으로 묶을 필요는 없다(상관관계 조회는 엔티티 단위로 이뤄지므로
        # 일부만 먼저 보여도 정합성이 깨지지 않는다). report_records 같은 감사증적이
        # 아니므로 postgres_report_repository.py만큼 엄격할 필요가 없다.
        for entity in signal.entities:
            self._execute(
                "INSERT INTO channel_signals "
                "(signal_id, channel, entity_type, entity_value, occurred_at, context_excerpt) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    signal_id,
                    signal.channel.value,
                    entity.entity_type.value,
                    entity.value,
                    signal.occurred_at,
                    signal.context_excerpt,
                ),
            )

    def find_matches(
        self,
        entities: list[ExtractedEntity],
        exclude_channel: Channel,
        occurred_at: datetime,
        window_seconds: int,
    ) -> list[CorrelationMatch]:
        if not entities:
            return []

        entity_conditions = " OR ".join(["(entity_type = %s AND entity_value = %s)"] * len(entities))
        entity_params: list[str] = []
        for entity in entities:
            entity_params.extend([entity.entity_type.value, entity.value])

        window = timedelta(seconds=window_seconds)
        query = (
            "SELECT channel, entity_type, entity_value, occurred_at, context_excerpt "
            "FROM channel_signals "
            f"WHERE channel <> %s AND occurred_at BETWEEN %s AND %s AND ({entity_conditions}) "
            "ORDER BY occurred_at DESC"
        )
        params = (exclude_channel.value, occurred_at - window, occurred_at + window, *entity_params)

        rows = self._execute(query, params).fetchall()
        return [
            CorrelationMatch(
                entity_type=EntityType(entity_type),
                entity_value=entity_value,
                matched_channel=Channel(channel),
                matched_at=matched_at,
                context_excerpt=context_excerpt,
            )
            for channel, entity_type, entity_value, matched_at, context_excerpt in rows
        ]
