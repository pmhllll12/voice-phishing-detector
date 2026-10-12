// 역방향 신원확인 POC 클라이언트. 실제 모바일신분증과 연동하지 않는 모의 시제품이다.
//
// - 직원용 화면(/verify/staff)은 verify-worker를 직접 호출한다(자격증명 목록, 증명 생성).
// - 국민용 화면(/verify/citizen)은 apps/api를 거친다 — 검증 결과를 통화 기록에 붙이고,
//   확인 불가면 보호자 알림(mock)을 남기는 건 api의 책임이기 때문이다
//   (apps/api/src/main.py verify_call_identity 참고).

import { ApiError } from "@/lib/api";

const VERIFY_WORKER_URL = process.env.NEXT_PUBLIC_VERIFY_WORKER_URL ?? "http://localhost:8400";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
// lib/api.ts와 같은 데모용 handler 키(그쪽 상단 주석의 한계를 그대로 공유한다).
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "dev-handler-key";

// 대시보드를 거치지 않고 국민용 화면에 바로 들어온 시연도 같은 경로로 기록한다.
export const STANDALONE_CALL_ID = "standalone";

export const MOCK_NOTICE = "모의 시연 화면이며 실제 모바일신분증과 연동되지 않습니다.";

export interface StaffCredential {
  credential_id: string;
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

export interface CallVerification {
  call_id: string;
  verified: boolean;
  reason: string;
  message: string;
  verified_at: string;
  institution_name?: string;
  staff_display_name?: string;
  purpose?: string;
  expires_at?: string;
  guardian_notification: { notification_id: string; status: string; note: string } | null;
}

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
  if (!res.ok) throw new ApiError(await parseErrorDetail(res), res.status);
  return res.json();
}
