#!/usr/bin/env bash
# postgres 단일 장애점 완화 2/2 (1/2는 docker-compose.yaml의 restart: unless-stopped).
# restart 정책은 "프로세스가 죽었을 때 다시 켜는 것"만 해결하고, 볼륨 손상이나
# `DROP TABLE` 같은 실수로 데이터 자체가 사라지는 건 못 막는다 — 그건 이 스크립트
# (정기 pg_dump)가 커버한다. cron이나 systemd timer로 주기 실행하도록 등록해서 쓴다
# (이 저장소엔 스케줄러를 직접 등록해두지 않았다 — 배포 환경마다 방식이 달라서
# README "postgres 백업/복구" 절에 등록 예시만 남겨둔다).
#
# 복원: gunzip -c <백업파일> | PGPASSWORD=$POSTGRES_PASSWORD psql -h localhost \
#       -U $POSTGRES_USER -d $POSTGRES_DB

set -euo pipefail

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-vps-postgres}"
POSTGRES_USER="${POSTGRES_USER:-vps_app}"
POSTGRES_DB="${POSTGRES_DB:-vps_detector}"
BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
out_file="$BACKUP_DIR/${POSTGRES_DB}_${timestamp}.sql.gz"

docker exec "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$out_file"

echo "백업 완료: $out_file ($(du -h "$out_file" | cut -f1))"

# RETENTION_DAYS보다 오래된 백업은 정리한다 — 무한정 쌓이지 않도록.
find "$BACKUP_DIR" -name "${POSTGRES_DB}_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
