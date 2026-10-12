"use client";

// 역방향 신원확인 POC — 국민용 화면(모의). 본문은 CitizenVerifyPanel(관제 대시보드와 공용).
// call_id 쿼리(대시보드의 "새 창으로 열기" 링크가 붙여줌)가 있으면 그 통화 기록에 결과를
// 붙이고, 없으면 STANDALONE_CALL_ID로 기록한다.

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { CitizenVerifyPanel } from "@/components/verify/CitizenVerifyPanel";
import { STANDALONE_CALL_ID } from "@/lib/verify";

function CitizenVerifyFromQuery() {
  const searchParams = useSearchParams();
  return <CitizenVerifyPanel callId={searchParams.get("call_id") || STANDALONE_CALL_ID} />;
}

export default function CitizenVerifyPage() {
  // useSearchParams는 정적 빌드 시 Suspense 경계가 필요하다(Next.js 14).
  return (
    <Suspense fallback={null}>
      <CitizenVerifyFromQuery />
    </Suspense>
  );
}
