# 우선순위 2(SMS/email 실채널 연동): Gmail 받은편지함을 폴링해 새 메일을 F-01/F-02/F-05
# 판정 + 크로스채널 상관관계(channel=email)에 결합한다. server.py와 완전히 같은
# CallAnalysisService/MultichannelCorrelationService 배선을 재사용한다(import server) —
# 판정 로직/Safe Browsing/RAG_WORKER_URL 등 환경변수 처리를 여기서 다시 만들지 않는다.
#
# 사전 준비: scripts/gmail_oauth_setup.py를 먼저 실행해 apps/mcp-server/gmail_token.json
# 을 만들어둬야 한다(README "Gmail 이메일 채널 연동" 절 참고).
#
# 실행 (apps/mcp-server 디렉터리에서, mcp-server REST가 쓰는 것과 같은 postgres/Ollama
# 환경변수가 필요하면 그대로 export하고):
#   .venv/bin/python scripts/poll_gmail_inbox.py            # 1회만 폴링하고 종료
#   .venv/bin/python scripts/poll_gmail_inbox.py --loop 60  # 60초 간격으로 계속 폴링

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import server  # noqa: E402 — sys.path 조정 후에 임포트해야 한다
from application.services import EmailIngestionService  # noqa: E402
from infrastructure.adapters.gmail_email_source_adapter import (  # noqa: E402
    GmailEmailSourceAdapter,
    build_gmail_service,
)

_HERE = pathlib.Path(__file__).resolve().parent.parent
_DEFAULT_TOKEN_PATH = _HERE / "gmail_token.json"


def _run_once(service: EmailIngestionService) -> None:
    results = service.poll_once()
    if not results:
        print("새 메일 없음")
        return

    for email, analysis in results:
        print(
            f"[{analysis.risk.level.value.upper()}] {email.subject!r} "
            f"(위험도 {analysis.risk.score}점, message_id={email.message_id})"
        )
        print(f"  {analysis.explanation.summary}")


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
    ingestion_service = EmailIngestionService(email_source, server.call_analysis_service)

    if args.loop <= 0:
        _run_once(ingestion_service)
        return

    print(f"{args.loop}초 간격으로 폴링합니다 (Ctrl+C로 종료)")
    while True:
        _run_once(ingestion_service)
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
