import Link from "next/link";
import type { CSSProperties } from "react";

// 채용용 포트폴리오 랜딩 페이지 — 대시보드(/dashboard)는 기존 F-06 관제 화면이고,
// 이 페이지는 자기소개 + 프로젝트 링크만 보여준다. 기존 대시보드처럼 별도 CSS
// 없이 인라인 style만 쓰는 컨벤션을 그대로 따른다(globals.css 토큰 재사용).
const monospace = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace';

const commentStyle: CSSProperties = {
  fontFamily: monospace,
  fontSize: "13px",
  color: "var(--series-3)",
  marginBottom: "10px",
};

const tagStyle: CSSProperties = {
  display: "inline-block",
  padding: "3px 10px",
  borderRadius: "20px",
  border: "1px solid var(--gridline)",
  background: "var(--track)",
  color: "var(--text-secondary)",
  fontSize: "12px",
  fontFamily: monospace,
  marginRight: "6px",
};

// "~/projects/personal/voice-phishing-detector" → prefix는 muted, 마지막 슬러그는
// 강조(흰색/굵게)해서 브레드크럼처럼 보이게 한다.
function splitPath(path: string): [string, string] {
  const idx = path.lastIndexOf("/");
  return [path.slice(0, idx + 1), path.slice(idx + 1)];
}

function ProjectCard({
  path,
  title,
  description,
  tags,
  href,
  external = false,
}: {
  path: string;
  title: string;
  description: string;
  tags: string[];
  href: string;
  external?: boolean;
}) {
  const [pathPrefix, pathSlug] = splitPath(path);

  const card = (
    <div
      style={{
        background: "var(--surface-1)",
        border: "1px solid var(--border)",
        borderRadius: "10px",
        padding: "20px 22px",
        marginBottom: "16px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          fontFamily: monospace,
          fontSize: "13px",
          color: "var(--text-muted)",
          marginBottom: "8px",
        }}
      >
        <span>
          {pathPrefix}
          <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{pathSlug}</span>
        </span>
        <span aria-hidden>↗</span>
      </div>
      <h3 style={{ fontSize: "17px", fontWeight: 700, margin: "0 0 8px" }}>{title}</h3>
      <p style={{ fontSize: "14px", color: "var(--text-secondary)", lineHeight: 1.6, margin: "0 0 12px" }}>
        {description}
      </p>
      <div>
        {tags.map((tag) => (
          <span key={tag} style={tagStyle}>
            {tag}
          </span>
        ))}
      </div>
    </div>
  );

  const linkStyle: CSSProperties = { display: "block", textDecoration: "none", color: "inherit" };

  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" style={linkStyle}>
        {card}
      </a>
    );
  }

  return (
    <Link href={href} style={linkStyle}>
      {card}
    </Link>
  );
}

export default function LandingPage() {
  return (
    // 바깥 div가 전체 뷰포트를 다크로 채우고, 안쪽 main은 그 위에서 컬럼만 중앙 정렬한다
    // (다크 배경을 max-width 컬럼에만 style로 주면 화면 좌우가 body의 기본 배경으로 남는다).
    <div className="portfolio-dark">
      <main style={{ maxWidth: "720px", margin: "0 auto", padding: "56px 24px 32px" }}>
        <div style={{ fontFamily: monospace, fontSize: "13px", color: "var(--series-3)", marginBottom: "16px" }}>
          ~/portfolio
        </div>
        <h1 style={{ fontSize: "40px", fontWeight: 700, letterSpacing: "0.15em", margin: "0 0 8px" }}>박민호</h1>
        <p style={{ fontSize: "16px", color: "var(--text-primary)", margin: "0 0 40px" }}>
          AI / Cloud Infrastructure Engineer를 목표로 커리어를 전환 중입니다.
        </p>

        <section style={{ marginBottom: "36px" }}>
          <div style={commentStyle}>// 자기소개</div>
          <p
            style={{
              borderLeft: "2px solid var(--series-1)",
              paddingLeft: "16px",
              color: "var(--series-1)",
              fontSize: "14px",
              lineHeight: 1.7,
              margin: 0,
            }}
          >
            ← 이 문단을 실제 자기소개서 내용으로 교체하세요. 지금까지의 경력 전환 배경, AI/클라우드
            인프라 엔지니어링에 관심을 갖게 된 계기, 강점을 3~5문장 정도로 정리하시면 됩니다.
          </p>
        </section>

        <section style={{ marginBottom: "40px" }}>
          <div style={commentStyle}>// 프로젝트</div>
          <ProjectCard
            path="~/projects/personal/voice-phishing-detector"
            title="보이스피싱 실시간 탐지 및 대응 시스템"
            description="← 프로젝트 한 줄 설명을 여기에 넣으세요 (예: 통화 내용을 실시간으로 분석해 위험도를 판별하고 딥보이스를 탐지하는 개인 프로젝트)."
            tags={["FastAPI", "RAG", "딥보이스 판별"]}
            href="/dashboard"
          />
          <ProjectCard
            path="~/projects/team/supersub"
            title="SUPERSUB"
            description="← 팀 프로젝트 한 줄 설명을 여기에 넣으세요 (예: 4인 팀 프로젝트, 담당 역할 포함)."
            tags={["Next.js", "FastAPI", "K3s", "팀 4인"]}
            href="https://supersub-ai.com"
            external
          />
        </section>

        <footer
          style={{
            borderTop: "1px solid var(--gridline)",
            paddingTop: "16px",
            display: "flex",
            justifyContent: "space-between",
            fontSize: "13px",
            color: "var(--text-muted)",
          }}
        >
          <span>Gangdong-gu, Seoul</span>
          <span>
            <a
              href="mailto:pmhllll12@gmail.com"
              style={{ color: "var(--text-secondary)", textDecoration: "underline", textDecorationStyle: "dotted" }}
            >
              이메일
            </a>
            {" · "}
            <a
              href="https://github.com/pmhllll12"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--series-3)", textDecoration: "underline", textDecorationStyle: "dotted" }}
            >
              GitHub
            </a>
          </span>
        </footer>
      </main>
    </div>
  );
}
