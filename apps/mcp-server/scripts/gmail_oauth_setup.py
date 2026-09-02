# 우선순위 2(SMS/email 실채널 연동): Gmail API에 최초 1회 동의를 받아 토큰을 저장하는
# 대화형 스크립트. 브라우저가 열리고 로그인/동의 후 자동으로 이 프로세스로 돌아온다.
#
# 사전 준비 (README "Gmail 이메일 채널 연동" 절 참고):
#   1. Google Cloud Console에서 프로젝트 생성(또는 재사용) 후 Gmail API 활성화
#   2. OAuth 동의 화면 구성(테스트 사용자로 이 Gmail 계정 추가)
#   3. OAuth 클라이언트 ID 생성 — 애플리케이션 유형 "데스크톱 앱"
#   4. 다운받은 JSON을 apps/mcp-server/gmail_client_secret.json으로 저장
#
# 실행 (apps/mcp-server 디렉터리에서):
#   .venv/bin/pip install -r requirements-gmail.txt   # 최초 1회만
#   .venv/bin/python scripts/gmail_oauth_setup.py
#
# 성공하면 apps/mcp-server/gmail_token.json이 생성된다 — 이 파일이 이후
# scripts/poll_gmail_inbox.py가 재로그인 없이 쓰는 자격증명이다. 토큰이 만료돼도
# refresh_token으로 자동 갱신된다(gmail_email_source_adapter.py의
# build_gmail_service() 참고). gmail_client_secret.json/gmail_token.json 둘 다
# .gitignore에 등록돼 있어야 한다 — 절대 커밋하지 말 것(비밀정보).

import pathlib

from google_auth_oauthlib.flow import InstalledAppFlow

_HERE = pathlib.Path(__file__).resolve().parent.parent
_CLIENT_SECRET_PATH = _HERE / "gmail_client_secret.json"
_TOKEN_PATH = _HERE / "gmail_token.json"
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def main() -> None:
    if not _CLIENT_SECRET_PATH.exists():
        raise SystemExit(
            f"{_CLIENT_SECRET_PATH}가 없습니다 — Google Cloud Console에서 OAuth 클라이언트(데스크톱 앱)를 "
            "만들고 다운받은 JSON을 이 경로에 저장하세요(README 'Gmail 이메일 채널 연동' 절 참고)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRET_PATH), _SCOPES)
    creds = flow.run_local_server(port=0)

    _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"인증 완료 — {_TOKEN_PATH}에 토큰을 저장했습니다.")
    print("이제 scripts/poll_gmail_inbox.py를 실행하면 됩니다.")


if __name__ == "__main__":
    main()
