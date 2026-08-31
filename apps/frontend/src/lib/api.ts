// apps/api 호출용 클라이언트. F-06 대시보드가 쓰는 엔드포인트를 감싼다.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// N-02: api의 조회/처리 엔드포인트는 X-API-Key를 요구한다(apps/api/src/infrastructure/
// adapters/api_key_role_auth.py 참고). 대시보드는 조회(목록/통계)와 처리(분석 실행/신고
// 접수)를 모두 하므로 handler 키가 필요하다. NEXT_PUBLIC_*는 브라우저 번들에 그대로
// 노출되므로 이건 "진짜" 비밀키가 아니라 로그인 시스템이 없는 지금 단계의 데모용
// 타협이다 — 실제 서비스라면 사용자별 세션을 Next.js 서버(BFF)가 들고 api를 대신
// 호출해야 한다(TODO, 아직 미착수).
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "dev-handler-key";
const AUTH_HEADERS = { "X-API-Key": API_KEY };

export type RiskLevel = "low" | "medium" | "high";

export interface DetectedPattern {
  category: string;
  category_label: string;
  matched_keywords: string[];
}

export interface SimilarCase {
  case_id: string;
  title: string;
  category: string;
  summary: string;
  source_note: string;
  similarity: number;
}

export interface CallAnalysis {
  call_id: string;
  analyzed_at: string;
  // N-03: 항상 마스킹된 버전만 온다(전화번호/계좌번호/이름 등 제거). raw_transcript(원문)는
  // N-02 RBAC상 ADMIN 키로 호출했을 때만 응답에 포함되므로 optional — 이 대시보드는 기본
  // handler 키를 쓰므로(dev-handler-key) 평소엔 안 온다(apps/api/src/main.py
  // _serialize_call_result 참고).
  masked_transcript: string;
  raw_transcript?: string;
  risk_score: number;
  risk_level: RiskLevel;
  detected_patterns: DetectedPattern[];
  explanation_summary: string;
  explanation: string;
  similar_cases: SimilarCase[];
}

export interface CategoryCount {
  category: string;
  category_label: string;
  count: number;
}

export interface StatsSummary {
  total_analyzed: number;
  risk_level_counts: Record<RiskLevel, number>;
  category_counts: CategoryCount[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // 응답이 JSON이 아니면 그냥 상태 텍스트로 대체
  }
  return `${res.status} ${res.statusText}`;
}

export async function checkApiHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function analyzeCall(transcript: string): Promise<CallAnalysis> {
  const res = await fetch(`${API_BASE_URL}/api/v1/calls/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...AUTH_HEADERS },
    body: JSON.stringify({ transcript }),
  });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  return res.json();
}

// F-05: 오디오 파일을 업로드해 stt-worker(faster-whisper)로 변환한 뒤 analyzeCall과
// 동일한 판정 경로를 태운다(apps/api/src/main.py analyze_call_audio). Content-Type을
// 직접 지정하지 않는다 — FormData를 fetch에 넘기면 브라우저가 multipart 경계(boundary)를
// 포함한 헤더를 자동으로 붙이는데, 수동으로 지정하면 그 경계가 빠져 서버가 파싱하지 못한다.
export async function analyzeCallAudio(audioBlob: Blob): Promise<CallAnalysis> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.webm");
  const res = await fetch(`${API_BASE_URL}/api/v1/calls/analyze-audio`, {
    method: "POST",
    headers: AUTH_HEADERS,
    body: formData,
  });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  return res.json();
}

export async function listCalls(limit = 20): Promise<CallAnalysis[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/calls?limit=${limit}`, { headers: AUTH_HEADERS });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  const data = await res.json();
  return data.calls;
}

export async function getStatsSummary(): Promise<StatsSummary> {
  const res = await fetch(`${API_BASE_URL}/api/v1/stats/summary`, { headers: AUTH_HEADERS });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  return res.json();
}

export interface ReportResult {
  report_id: string;
  status: string;
  channel: "auto" | "manual";
  submitted_at: string;
  note: string;
}

// F-07: 신고 접수(mock) — 실제 112/경찰청 신고 API는 호출하지 않는다 (docs/RFP.md 4장).
export async function submitReport(caseSummary: string, riskLevel: RiskLevel): Promise<ReportResult> {
  const res = await fetch(`${API_BASE_URL}/api/v1/reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...AUTH_HEADERS },
    body: JSON.stringify({ case_summary: caseSummary, risk_level: riskLevel }),
  });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  return res.json();
}
