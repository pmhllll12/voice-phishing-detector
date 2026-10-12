"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";

import { analyzeCall, analyzeCallAudio, ApiError, type CallAnalysis } from "@/lib/api";
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
// 하고, 확정은 신원확인이 한다"는 안내와 국민용 확인 화면 링크를 붙인다. 링크에 call_id를
// 실어 보내 검증 결과가 이 통화 기록에 붙게 한다(apps/api verify_call_identity).
function VerificationPromptNotice({ call }: { call: CallAnalysis }) {
  if (!call.verification_prompt?.required) return null;
  return (
    <div
      role="status"
      style={{
        border: "1px solid var(--series-1)",
        borderRadius: "6px",
        padding: "10px 12px",
        fontSize: "14px",
        background: "var(--surface-1)",
      }}
    >
      <strong>🪪 상대 신원 확인 권장</strong>
      <p style={{ margin: "4px 0 6px", color: "var(--text-secondary)" }}>{call.verification_prompt.message}</p>
      <Link href={`/verify/citizen?call_id=${encodeURIComponent(call.call_id)}`} style={{ color: "var(--series-1)" }}>
        상대 신원 확인 화면 열기 →
      </Link>
      <p style={{ margin: "6px 0 0", fontSize: "12px", color: "var(--text-muted)" }}>{MOCK_NOTICE}</p>
    </div>
  );
}

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
    const trimmed = transcript.trim();
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

        {textError && <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>{textError}</span>}
        {audioError && <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>{audioError}</span>}
      </div>
      {lastAnalysis && <VerificationPromptNotice call={lastAnalysis} />}
    </form>
  );
}
