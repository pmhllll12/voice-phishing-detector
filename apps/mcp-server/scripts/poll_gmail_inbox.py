# 우선순위 2(SMS/email 실채널 연동): Gmail 받은편지함을 폴링해 새 메일을 apps/api의
# POST /api/v1/calls/analyze(channel="email")로 판정 요청한다. apps/api가 F-01/F-02/F-05
# 판정 + 크로스채널 상관관계 + N-01 감사증적(postgres) 적재를 전부 하므로, 결과가
# F-06 대시보드(이메일 탭)에도 그대로 뜬다 — mcp-server 로컬 CallAnalysisService를
# 직접 쓰던 첫 버전(터미널에만 결과가 나오고 대시보드엔 안 보이던 버전)에서 전환함
# (2026-09-02, 대시보드 이메일 탭 요청에 따라 — application/services.py의
# EmailIngestionService 상단 주석 참고).
#
# 사전 준비: scripts/gmail_oauth_setup.py를 먼저 실행해 apps/mcp-server/gmail_token.json
# 을 만들어둬야 한다(README "Gmail 이메일 채널 연동" 절 참고). apps/api가 먼저 떠
# 있어야 한다(기본 http://localhost:8000, API_BASE_URL로 오버라이드 가능).
#
# 실행 (apps/mcp-server 디렉터리에서):
#   .venv/bin/python scripts/poll_gmail_inbox.py            # 1회만 폴링하고 종료
#   .venv/bin/python scripts/poll_gmail_inbox.py --loop 60  # 60초 간격으로 계속 폴링

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from application.services import EmailIngestionService  # noqa: E402
from infrastructure.adapters.api_email_analysis_adapter import ApiEmailAnalysisAdapter  # noqa: E402
from infrastructure.adapters.gmail_email_source_adapter import (  # noqa: E402
    GmailEmailSourceAdapter,
    build_gmail_service,
)

_HERE = pathlib.Path(__file__).resolve().parent.parent
_DEFAULT_TOKEN_PATH = _HERE / "gmail_token.json"

# apps/api 주소/자격증명 — 프런트 대시보드가 쓰는 것과 같은 N-02 handler 키 기본값
# (apps/frontend/src/lib/api.ts의 NEXT_PUBLIC_API_KEY 기본값과 동일, 로컬 개발 전용).
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_HANDLER_KEY = os.environ.get("API_HANDLER_KEY", "dev-handler-key")


def _run_once(service: EmailIngestionService) -> None:
    results = service.poll_once()
    if not results:
        print("새 메일 없음")
        return

    for email, analysis in results:
        print(
            f"[{analysis['risk_level'].upper()}] {email.subject!r} "
            f"(위험도 {analysis['risk_score']}점, message_id={email.message_id}, "
            f"call_id={analysis['call_id']})"
        )
        print(f"  {analysis['explanation_summary']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail 받은편지함 폴링 (우선순위 2 SMS/email 실채널 연동)")
    parser.add_argument("--token", default=str(_DEFAULT_TOKEN_PATH), help="OAuth 토큰 경로")
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        metavar="SECONDS",
        help="주어지면 이 간격(초)으로 계속 폴링한다. 0(기본값)이면 한 번만 폴링하고 종료",
    )
    args = parser.parse_args()

    if not pathlib.Path(args.token).exists():
        raise SystemExit(f"{args.token}가 없습니다 — 먼저 scripts/gmail_oauth_setup.py를 실행하세요.")

    email_source = GmailEmailSourceAdapter(build_gmail_service(args.token))
    analysis_sink = ApiEmailAnalysisAdapter(API_BASE_URL, API_HANDLER_KEY)
    ingestion_service = EmailIngestionService(email_source, analysis_sink)

    if args.loop <= 0:
        _run_once(ingestion_service)
        return

    print(f"{args.loop}초 간격으로 폴링합니다 (Ctrl+C로 종료)")
    while True:
        _run_once(ingestion_service)
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
