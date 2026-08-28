// apps/api 호출용 클라이언트. F-06 대시보드가 쓰는 엔드포인트를 감싼다.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  raw_transcript: string;
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript }),
  });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  return res.json();
}

export async function listCalls(limit = 20): Promise<CallAnalysis[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/calls?limit=${limit}`);
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  const data = await res.json();
  return data.calls;
}

export async function getStatsSummary(): Promise<StatsSummary> {
  const res = await fetch(`${API_BASE_URL}/api/v1/stats/summary`);
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_summary: caseSummary, risk_level: riskLevel }),
  });
  if (!res.ok) {
    throw new ApiError(await parseErrorDetail(res), res.status);
  }
  return res.json();
}
