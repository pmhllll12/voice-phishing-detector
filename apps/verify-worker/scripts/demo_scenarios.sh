#!/usr/bin/env bash
# 역방향 신원확인 POC 시연 시나리오 3개 (verify-worker 8400 + api 경유)
# API: apps/api 주소(기본 8000). api가 이 기능이 들어간 코드로 재시작돼 있어야 한다 —
#      별도 포트로 띄웠다면 API=http://localhost:8010 ./demo_scenarios.sh 처럼 지정.
# 시연용 시드 자격증명(demo-bank-staff)은 폐기하지 않는다 — 시나리오 3은 새로 발급해서 폐기.
VW=${VW:-http://localhost:8400}; API=${API:-http://localhost:8000}
J='Content-Type: application/json'; K='X-API-Key: dev-handler-key'
code_of() { python3 -c 'import sys,json;print(json.load(sys.stdin)["code"])'; }

echo "## 시나리오 1: 정상 직원"
echo '$ POST /api/v1/proofs {"credential_id":"demo-bank-staff","purpose":"대출 상담 전화"}'
P=$(curl -s -X POST $VW/api/v1/proofs -H "$J" -d '{"credential_id":"demo-bank-staff","purpose":"대출 상담 전화"}'); echo "$P"
C=$(echo "$P" | code_of)
echo "\$ POST (api) /api/v1/calls/demo-call-1/verification {\"code\":\"$C\"}"
curl -s -X POST $API/api/v1/calls/demo-call-1/verification -H "$J" -H "$K" -d "{\"code\":\"$C\"}"; echo; echo

echo "## 시나리오 2: 사칭범 (발급된 적 없는 코드)"
echo '$ POST (api) /api/v1/calls/demo-call-2/verification {"code":"000000"}'
curl -s -X POST $API/api/v1/calls/demo-call-2/verification -H "$J" -H "$K" -d '{"code":"000000"}'; echo; echo

echo "## 시나리오 3: 퇴사자 (증명 생성 → 자격증명 폐기 → 검증)"
echo '$ POST /api/v1/credentials {"institution_name":"○○은행(모의)","staff_display_name":"최퇴사","role":"대출상담 직원"}'
CR=$(curl -s -X POST $VW/api/v1/credentials -H "$J" -d '{"institution_name":"○○은행(모의)","staff_display_name":"최퇴사","role":"대출상담 직원"}'); echo "$CR"
ID=$(echo "$CR" | python3 -c 'import sys,json;print(json.load(sys.stdin)["credential_id"])')
echo "\$ POST /api/v1/proofs {\"credential_id\":\"$ID\",\"purpose\":\"방문 상담\"}"
P=$(curl -s -X POST $VW/api/v1/proofs -H "$J" -d "{\"credential_id\":\"$ID\",\"purpose\":\"방문 상담\"}"); echo "$P"
C=$(echo "$P" | code_of)
echo "\$ POST /api/v1/credentials/$ID/revoke"
curl -s -X POST $VW/api/v1/credentials/$ID/revoke; echo
echo "\$ POST (api) /api/v1/calls/demo-call-3/verification {\"code\":\"$C\"}"
curl -s -X POST $API/api/v1/calls/demo-call-3/verification -H "$J" -H "$K" -d "{\"code\":\"$C\"}"; echo
