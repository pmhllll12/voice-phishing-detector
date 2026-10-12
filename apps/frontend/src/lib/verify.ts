// 역방향 신원확인 POC 클라이언트. 실제 모바일신분증과 연동하지 않는 모의 시제품이다.
//
// - 직원용 화면(/verify/staff)은 verify-worker를 직접 호출한다(자격증명 목록, 증명 생성).
// - 국민용 화면(/verify/citizen)은 apps/api를 거친다 — 검증 결과를 통화 기록에 붙이고,
//   확인 불가면 보호자 알림(mock)을 남기는 건 api의 책임이기 때문이다
//   (apps/api/src/main.py verify_call_identity 참고).

import { ApiError, type IdentityVerification } from "@/lib/api";

const VERIFY_WORKER_URL = process.env.NEXT_PUBLIC_VERIFY_WORKER_URL ?? "http://localhost:8400";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
// lib/api.ts와 같은 데모용 handler 키(그쪽 상단 주석의 한계를 그대로 공유한다).
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "dev-handler-key";

// 대시보드를 거치지 않고 국민용 화면에 바로 들어온 시연도 같은 경로로 기록한다.
export const STANDALONE_CALL_ID = "standalone";

// 방문용 QR에 담을 국민용 화면 주소의 기준. 비워 두면 지금 연 화면의 origin을 쓴다 — 휴대폰
// 카메라로 시연하려면 휴대폰이 열 수 있는 주소(같은 Wi-Fi의 PC IP 등)를 넣어야 한다(README 참고).
const CITIZEN_BASE_URL = process.env.NEXT_PUBLIC_CITIZEN_BASE_URL ?? "";

// QR 내용: 국민용 화면 주소 + 코드. 국민 화면은 코드를 입력칸에 미리 채우기만 하고 확인 버튼은
// 사람이 누른다. 링크를 여는 방식은 시연 편의용이다 — 실제 구조에서는 정부 앱 안에서 QR을 읽어야
// 한다(아무 링크나 여는 습관을 들이면 가짜 QR 링크 피싱에 그대로 노출된다).
export function citizenVerifyUrl(code: string): string {
  const base = CITIZEN_BASE_URL || (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/verify/citizen?code=${encodeURIComponent(code)}`;
}

// 직원 화면의 목적 선택지. 기관명처럼 방문 목적도 모의 시연임을 표시한다.
export const PROOF_PURPOSES = ["대출 상담 전화", "복지 상담 전화", "가스 점검 방문(모의)"] as const;

export const MOCK_NOTICE = "모의 시연 화면이며 실제 모바일신분증과 연동되지 않습니다.";

export interface StaffCredential {
  credential_id: string;
  issuer_id: string; // 발급 모의 기관(GET /api/v1/issuers의 공개키 레지스트리 항목)
  institution_name: string;
  staff_display_name: string;
  role: string;
  issued_at: string;
  revoked: boolean;
}

export interface CreatedProof {
  code: string;
  purpose: string;
  expires_at: string;
  ttl_seconds: number;
}

export type CallVerification = IdentityVerification;

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // JSON이 아니면 상태 텍스트로 대체
  }
  return `${res.status} ${res.statusText}`;
}

// fetch 자체가 실패(서버 꺼짐)하면 TypeError가 나서 사용자는 원인을 알 수 없다 — api의 502
// 응답처럼 실행 방법을 같이 알려준다.
async function fetchVerifyWorker(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${VERIFY_WORKER_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `verify-worker(${VERIFY_WORKER_URL})에 연결할 수 없습니다. 먼저 실행하세요 ` +
        "(cd apps/verify-worker && source .venv/bin/activate && uvicorn src.main:app --port 8400)."
    );
  }
}

export async function listStaffCredentials(): Promise<StaffCredential[]> {
  const res = await fetchVerifyWorker("/api/v1/credentials");
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status);
  const data = await res.json();
  return data.credentials;
}

export async function createProof(credentialId: string, purpose: string): Promise<CreatedProof> {
  const res = await fetchVerifyWorker("/api/v1/proofs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential_id: credentialId, purpose }),
  });
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status);
  return res.json();
}

export async function verifyCallIdentity(callId: string, code: string): Promise<CallVerification> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/calls/${encodeURIComponent(callId)}/verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ code }),
    });
  } catch {
    throw new ApiError(`api(${API_BASE_URL})에 연결할 수 없습니다.`);
  }
  // 429(짧은 시간에 너무 많이 틀림, reason=rate_limited)는 오류가 아니라 판정 결과다 — 본문이
  // 일반 검증 결과와 같은 형식(verified=false)이라 그대로 돌려주면 국민 화면이 확인 불가(빨강)로
  // 보여준다. "잠시 후 다시 시도" 안내를 하지 않는 이유: 제한에 걸릴 만큼 틀렸다면 끊는 게 맞다.
  if (res.status === 429) return res.json();
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status);
  return res.json();
}
