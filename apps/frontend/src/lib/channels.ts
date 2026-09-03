import type { Channel } from "./api";

// SMS/email 실채널 연동(2026-09-02) — "최근 탐지 현황" 탭/컬럼에 쓰는 채널 표시 메타.
// sms는 아직 실연동이 없지만(설계만, docs/design.md 7장) 타입/UI는 미리 대비해둔다.
export const CHANNEL_META: Record<Channel, { label: string; icon: string }> = {
  call: { label: "통화", icon: "📞" },
  email: { label: "이메일", icon: "✉️" },
  sms: { label: "문자", icon: "💬" },
};

export const CHANNEL_TABS: { key: Channel | "all"; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "call", label: "통화" },
  { key: "email", label: "이메일" },
];
