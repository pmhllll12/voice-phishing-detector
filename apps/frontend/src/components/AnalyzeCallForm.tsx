"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";

import { analyzeCall, analyzeCallAudio, ApiError, type CallAnalysis } from "@/lib/api";
import { CitizenVerifyPanel } from "@/components/verify/CitizenVerifyPanel";
import { StaffProofPanel } from "@/components/verify/StaffProofPanel";
import { MOCK_NOTICE } from "@/lib/verify";

// F-05: 텍스트 입력과 별개로, 마이크로 녹음한 오디오를 바로 업로드해 분석할 수 있다
// (stt-worker가 텍스트로 변환한 뒤 동일한 판정 경로를 탄다 — apps/api/src/main.py
// analyze_call_audio 참고). 두 경로를 하나의 폼에 묶은 이유는 F-01(통화 텍스트 분석)이
// "텍스트 입력"과 "오디오 입력" 둘 다를 위한 진입점이기 때문이다.
const RECORDING_MIME_CANDIDATES = ["audio/webm", "audio/mp4", "audio/ogg"];

// getUserMedia 실패는 원인이 제각각인데 브라우저가 전부 한 catch로 몰아준다 — 원인별로
// DOMException.name이 다르므로, 사용자가 실제로 뭘 고쳐야 하는지 구분해서 보여준다.
// (가장 흔한 함정: WSL2 포트포워딩 등으로 localhost가 아닌 IP/호스트명으로 접속하면
// getUserMedia 자체가 보안 컨텍스트가 아니라서 막힌다 — 아래 isSecureContext 체크 참고.)
function describeMicError(err: unknown): string {
  if (err instanceof DOMException) {
    switch (err.name) {
      case "NotAllowedError":
      case "PermissionDeniedError":
        return "마이크 접근 권한이 차단돼 있습니다. 브라우저 주소창의 자물쇠(사이트 정보) 아이콘에서 마이크 권한을 '허용'으로 바꾼 뒤 다시 시도하세요.";
      case "NotFoundError":
      case "DevicesNotFoundError":
        return "사용 가능한 마이크 장치를 찾을 수 없습니다.";
      case "NotReadableError":
        return "다른 프로그램이 마이크를 사용 중이라 접근할 수 없습니다.";
      case "SecurityError":
        return "보안 연결(HTTPS 또는 localhost)에서만 마이크를 사용할 수 있습니다. 접속 주소를 확인하세요.";
      default:
        return `마이크를 사용할 수 없습니다 (${err.name}).`;
    }
  }
  return "마이크 접근 권한이 거부됐거나 사용할 수 없습니다.";
}

// 역방향 신원확인 POC(모의 시제품): 방금 분석한 통화가 기관사칭/고위험이면 "AI는 의심만
// 하고, 확정은 신원확인이 한다"는 안내와 함께, 직원 쪽(코드 만들기)과 고객 쪽(코드 입력)
// 화면을 대시보드 안에 나란히 띄운다 — 세 화면을 따로 열지 않고 한 화면에서 흐름 전체를
// 볼 수 있게. 고객 패널은 이 통화의 call_id에 묶여 있어서, 검증 결과가 아래 "최근 탐지 현황"
// 의 이 통화 행 배지로 바로 나타난다. 단독 페이지(/verify/*)도 같은 컴포넌트를 쓴다.
function PhoneFrame({ title, caption, children }: { title: string; caption: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "14px",
        background: "var(--page-plane)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--border)", background: "var(--surface-1)" }}>
        <strong style={{ fontSize: "14px" }}>📱 {title}</strong>
        <span style={{ fontSize: "12px", color: "var(--text-muted)", marginLeft: "8px" }}>{caption}</span>
      </div>
      <div className="verify-scope" style={{ padding: "16px" }}>
        {children}
      </div>
    </div>
  );
}

function IdentityVerificationSection({ call, onVerified }: { call: CallAnalysis; onVerified: () => void }) {
  if (!call.verification_prompt?.required) return null;
  return (
    <section
      aria-label="상대 신원 확인 (모의)"
      style={{
        border: "1px solid var(--series-1)",
        borderRadius: "8px",
        padding: "12px",
        fontSize: "14px",
        background: "var(--surface-1)",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      <div>
        <strong>🪪 상대 신원 확인 권장</strong>
        <p style={{ margin: "4px 0 0", color: "var(--text-secondary)" }}>{call.verification_prompt.message}</p>
        <p style={{ margin: "4px 0 0", color: "var(--text-secondary)" }}>
          아래 왼쪽은 전화를 건 직원의 휴대폰, 오른쪽은 전화를 받은 고객의 휴대폰을 흉내 낸 화면입니다. 왼쪽에서 만든
          확인 코드를 오른쪽에 입력해 보세요.
        </p>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "12px" }}>
        <PhoneFrame title="직원 휴대폰 (모의)" caption="전화를 건 쪽">
          <StaffProofPanel />
        </PhoneFrame>
        <PhoneFrame title="고객 휴대폰 (모의)" caption="전화를 받은 쪽 · 이 통화에 결과가 기록됨">
          {/* key: 다른 통화를 분석하면 이전 통화의 입력/결과 상태를 버리고 새로 시작한다. */}
          <CitizenVerifyPanel key={call.call_id} callId={call.call_id} resultMinHeight="0" onVerified={onVerified} />
        </PhoneFrame>
      </div>
      <p style={{ margin: 0, fontSize: "12px", color: "var(--text-muted)" }}>
        {MOCK_NOTICE} · 단독 화면으로 보기:{" "}
        <Link href="/verify/staff" target="_blank" style={{ color: "var(--series-1)" }}>
          직원용
        </Link>{" "}
        /{" "}
        <Link
          href={`/verify/citizen?call_id=${encodeURIComponent(call.call_id)}`}
          target="_blank"
          style={{ color: "var(--series-1)" }}
        >
          고객용
        </Link>
      </p>
    </section>
  );
}

// 역방향 신원확인 시연용 예시. 분석 결과가 신원확인 대상(기관사칭 또는 고위험)이어야 아래
// 직원/고객 패널이 뜨므로, 기관사칭 + 긴급송금유도가 분명한 문장을 쓴다(합성 문장, 실제 통화 아님).
const AUTHORITY_IMPERSONATION_EXAMPLE =
  "서울중앙지검 수사관입니다. 고객님 명의 계좌가 범죄에 연루돼 안전계좌로 이체하셔야 합니다";

export function AnalyzeCallForm({ onAnalyzed }: { onAnalyzed: () => void }) {
  const [transcript, setTranscript] = useState("");
  const [lastAnalysis, setLastAnalysis] = useState<CallAnalysis | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [audioLoading, setAudioLoading] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await runTextAnalysis(transcript);
  }

  // 시연용: 예시 문장을 입력칸에 넣고 곧바로 분석까지 한다 — 넣기와 분석을 따로 누르게 하면
  // 처음 보는 사람이 두 번째 클릭을 놓쳐 신원확인 패널까지 가지 못한다. 분석 중에는 입력칸에
  // 예시가 보여서 무엇을 분석하는지 알 수 있다.
  async function analyzeExample() {
    setTranscript(AUTHORITY_IMPERSONATION_EXAMPLE);
    await runTextAnalysis(AUTHORITY_IMPERSONATION_EXAMPLE);
  }

  async function runTextAnalysis(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;

    setTextLoading(true);
    setTextError(null);
    // 이전 통화의 신원확인 안내/링크가 새 결과가 올 때까지 남아 있으면, 그 링크로 들어가 검증한
    // 결과가 엉뚱한(이전) 통화 기록에 붙는다 — 새 분석을 시작하는 순간 지운다.
    setLastAnalysis(null);
    try {
      setLastAnalysis(await analyzeCall(trimmed));
      setTranscript("");
      onAnalyzed();
    } catch (err) {
      setTextError(err instanceof ApiError ? err.message : "분석 요청에 실패했습니다.");
    } finally {
      setTextLoading(false);
    }
  }

  async function startRecording() {
    setAudioError(null);
    if (!window.isSecureContext) {
      setAudioError(
        "보안 연결(HTTPS 또는 localhost)에서만 마이크를 사용할 수 있습니다 — 지금 주소창의 URL이 " +
          "localhost가 아니라 IP/다른 호스트명이라면 그게 원인입니다."
      );
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setAudioError("이 브라우저는 마이크 녹음을 지원하지 않습니다.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = RECORDING_MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        setAudioLoading(true);
        setLastAnalysis(null);
        try {
          setLastAnalysis(await analyzeCallAudio(blob));
          onAnalyzed();
        } catch (err) {
          setAudioError(err instanceof ApiError ? err.message : "음성 분석 요청에 실패했습니다.");
        } finally {
          setAudioLoading(false);
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch (err) {
      setAudioError(describeMicError(err));
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  }

  return (
    // 고객 패널(CitizenVerifyPanel)이 자체 <form>을 가지므로 분석 <form> 밖에 둔다(form 중첩 불가).
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="예: 검찰청 수사관인데 계좌가 범죄에 연루돼서 지금 즉시 안전계좌로 이체해야 한다고 전화왔어"
          rows={3}
          style={{
            resize: "vertical",
            padding: "10px 12px",
            borderRadius: "6px",
            border: "1px solid var(--border)",
            background: "var(--surface-1)",
            color: "var(--text-primary)",
            fontFamily: "inherit",
            fontSize: "14px",
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          <button
            type="submit"
            disabled={textLoading || !transcript.trim()}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "none",
              background: "var(--series-1)",
              color: "#ffffff",
              fontSize: "14px",
              cursor: textLoading ? "default" : "pointer",
              opacity: textLoading || !transcript.trim() ? 0.6 : 1,
            }}
          >
            {textLoading ? "분석 중…" : "텍스트로 분석하기"}
          </button>

          <button
            type="button"
            onClick={isRecording ? stopRecording : startRecording}
            disabled={audioLoading}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: isRecording ? "1px solid var(--status-critical)" : "1px solid var(--border)",
              background: isRecording ? "var(--status-critical)" : "var(--surface-1)",
              color: isRecording ? "#ffffff" : "var(--text-primary)",
              fontSize: "14px",
              cursor: audioLoading ? "default" : "pointer",
              opacity: audioLoading ? 0.6 : 1,
            }}
          >
            {audioLoading ? "음성 분석 중…" : isRecording ? "■ 녹음 중지" : "🎤 음성으로 분석"}
          </button>

          <button
            type="button"
            onClick={analyzeExample}
            disabled={textLoading}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "1px dashed var(--series-1)",
              background: "transparent",
              color: "var(--series-1)",
              fontSize: "14px",
              cursor: textLoading ? "default" : "pointer",
            }}
          >
            {textLoading ? "분석 중…" : "기관사칭 예시로 바로 분석"}
          </button>

          {textError && <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>{textError}</span>}
          {audioError && <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>{audioError}</span>}
        </div>
      </form>
      {/* 신원확인 패널은 분석 결과가 대상일 때만 뜨므로, 그 전에는 기능이 있다는 걸 알 수 없다 —
          패널이 떠 있지 않을 때만 이 안내를 보여준다. */}
      {!lastAnalysis?.verification_prompt?.required && (
        <p style={{ margin: 0, fontSize: "13px", color: "var(--text-secondary)" }}>
          🪪 기관사칭이 의심되는 통화는 분석 결과 아래에서 <strong>상대 신원 확인(모의)</strong>까지 시연할 수
          있습니다 — &ldquo;기관사칭 예시로 바로 분석&rdquo;을 눌러 보세요.
        </p>
      )}
      {lastAnalysis && <IdentityVerificationSection call={lastAnalysis} onVerified={onAnalyzed} />}
    </div>
  );
}
