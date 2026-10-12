# F-01/F-02/F-05 v2 구현체: 키워드 규칙 대신 로컬 Ollama LLM(기본값 EXAONE 3.5 2.4B)이
# 통화/문자 텍스트의 문맥을 읽고 위험도와 판단 근거를 직접 산출한다.
# domain/ports.py의 CallAnalysisPort를 구현한다 (v1 RuleBasedCallAnalysisAdapter와
# 인터페이스 동일 — CallAnalysisResult 하나를 반환).
#
# WHY 모델 선택 (EXAONE 3.5 2.4B, Q4_K_M 양자화, ~1.5GB): 이 프로젝트는 이미 F-04에서
# GPU에 임베딩 모델(jhgan/ko-sroberta-multitask, VRAM 약 450MB)을 상시 로드해두고
# 있다. RTX 3050(8GB) 카드에서 두 모델을 "동시에" 띄워야 하므로, 7B급(Q4 기준
# 4.5~4.8GB)은 여유가 너무 빠듯해진다. 2~3B급 중에서, LG가 한국어·영어 이중언어로
# 직접 튜닝한 EXAONE 3.5를 1순위로 골랐다 (한국어 통화 텍스트가 입력이라는 이 도메인에
# 특히 유리). 대안으로 Qwen2.5:3b-instruct-q4_K_M(약 1.8GB)도 검증해뒀다 — JSON
# format 강제 출력 안정성이 더 필요하면 OLLAMA_MODEL 환경변수만 바꾸면 된다.
#
# WHY 자유 텍스트 파싱을 피했는가: LLM이 "네, 분석해보겠습니다..." 같은 군더더기를
# 섞어 답하면 정규식/문자열 파싱이 깨지기 쉽다. Ollama의 /api/generate가 지원하는
# format(JSON Schema)을 쓰면 모델이 스키마를 벗어난 토큰 자체를 생성할 수 없게
# 디코딩 단계에서 강제된다 (grammar-constrained decoding) — 그래서 이 스키마에 맞는
# JSON 문자열만 나온다는 게 보장되고, 남은 건 json.loads() 뿐이다.
#
# WHY 폴백이 필요한가: Ollama 프로세스가 안 떠 있거나, 모델이 아직 안 받아졌거나,
# 콜드 스타트로 로딩이 오래 걸려 타임아웃 나는 경우가 실제로 있다 (VRAM이 다른
# 프로세스에 밀려 모델을 못 올리는 경우도 포함). 이럴 때 통화 판정 자체가 아예
# 실패하면 안 되므로, v1(키워드 규칙)으로 안전하게 넘어간다 — 정확도는 떨어지지만
# "판정 불가"보다는 낫다는 판단.

import json
import logging
import os
import time

import httpx

from domain.entities import (
    CallAnalysisResult,
    CATEGORY_LABELS,
    DetectedPattern,
    PatternCategory,
    PatternDetectionResult,
    RiskAssessment,
    RiskExplanation,
    RISK_LEVEL_LABELS,
    RISK_LEVEL_THRESHOLDS,
)
from domain.ports import CallAnalysisPort
from infrastructure import metrics

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "exaone3.5:2.4b-instruct-q4_K_M"

_CATEGORY_VALUES = [c.value for c in PatternCategory]

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "detected_categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": _CATEGORY_VALUES},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                },
                "required": ["category", "evidence", "reasoning"],
            },
        },
    },
    "required": ["risk_score", "summary", "detected_categories"],
}

_CATEGORY_GUIDE = "\n".join(f"- {v} ({CATEGORY_LABELS[c]})" for c, v in zip(PatternCategory, _CATEGORY_VALUES))

_SYSTEM_PROMPT = f"""당신은 보이스피싱 탐지 전문가입니다. 주어진 통화/문자 텍스트를 읽고
아래 카테고리 중 실제로 해당하는 것만 골라 위험도를 판단하세요.

카테고리 목록:
{_CATEGORY_GUIDE}

규칙:
- risk_score는 0(전혀 위험하지 않음)~100(명백한 보이스피싱)
- detected_categories에는 실제로 텍스트에 근거가 있는 카테고리만 포함 (없으면 빈 배열)
- evidence는 반드시 원문에 실제로 등장하는 표현을 그대로 인용 (지어내지 말 것)
- reasoning은 그 카테고리로 판단한 이유를 한 문장으로
- summary는 전체 판단을 한두 문장으로 요약"""


def _resolve_model() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)


def _resolve_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)


# GPU(로컬 RTX 3050)에서는 20초면 충분하다고 실측됐지만(N-05 관련 테스트 참고), CPU
# 전용 인스턴스(예: EC2 t3.large, docs/design.md 4장 "1안")에서는 EXAONE 3.5 2.4B
# 추론이 20초를 넘겨 규칙 기반(v1)으로 계속 폴백되는 걸 실제 배포로 확인했다(2026-09-02).
# 환경변수로 오버라이드 가능하게 해서, 느린 CPU 환경에서는 값을 올려 v2(LLM) 판정이
# 실제로 완료되게 할 수 있다 — 기본값은 GPU 기준 그대로 20초 유지.
def _resolve_timeout_seconds() -> float:
    return float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "20.0"))


class OllamaCallAnalysisAdapter:
    def __init__(
        self,
        fallback: CallAnalysisPort,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self._fallback = fallback
        self._base_url = base_url or _resolve_base_url()
        self._model = model or _resolve_model()
        self._timeout = timeout_seconds if timeout_seconds is not None else _resolve_timeout_seconds()
        metrics.llm_model_info.info({"model_name": self._model, "base_url": self._base_url})

    def analyze(self, transcript: str) -> CallAnalysisResult:
        try:
            result = self._analyze_with_llm(transcript)
            metrics.llm_analysis_requests_total.labels(result="success").inc()
            return result
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                "Ollama 호출 실패 — 규칙 기반(v1)으로 폴백합니다: %s: %s",
                type(e).__name__,
                e,
            )
            metrics.llm_analysis_requests_total.labels(result="fallback").inc()
            return self._fallback.analyze(transcript)

    def _analyze_with_llm(self, transcript: str) -> CallAnalysisResult:
        start = time.perf_counter()
        response = httpx.post(
            f"{self._base_url}/api/generate",
            json={
                "model": self._model,
                "system": _SYSTEM_PROMPT,
                "prompt": f'다음 텍스트를 분석하세요:\n"""{transcript}"""',
                "format": _JSON_SCHEMA,
                "stream": False,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        elapsed = time.perf_counter() - start
        data = response.json()

        metrics.llm_inference_duration_seconds.observe(elapsed)
        metrics.llm_model_load_duration_seconds.set(data.get("load_duration", 0) / 1e9)
        self._update_gpu_metric()

        parsed = json.loads(data["response"])
        return self._to_domain(transcript, parsed)

    def _to_domain(self, transcript: str, parsed: dict) -> CallAnalysisResult:
        score = max(0, min(100, int(parsed["risk_score"])))
        level = self._level_for(score)

        detected_patterns: list[DetectedPattern] = []
        for item in parsed.get("detected_categories", []):
            try:
                category = PatternCategory(item["category"])
            except ValueError:
                # 스키마가 enum을 강제하므로 정상 상황에선 안 일어나지만, 방어적으로
                # 모르는 값은 무시하고 계속 진행한다 (한 카테고리 때문에 전체 판정이
                # 실패하면 안 되므로).
                logger.warning("알 수 없는 category 값 무시: %r", item.get("category"))
                continue
            detected_patterns.append(
                DetectedPattern(category=category, matched_keywords=item.get("evidence", []))
            )

        detection = PatternDetectionResult(transcript=transcript, detected_patterns=detected_patterns)
        risk = RiskAssessment(score=score, level=level, breakdown=[])
        explanation = self._build_explanation(parsed, detected_patterns, score, level)

        return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)

    @staticmethod
    def _level_for(score: int):
        for threshold, level in RISK_LEVEL_THRESHOLDS:
            if score >= threshold:
                return level
        return RISK_LEVEL_THRESHOLDS[-1][1]

    @staticmethod
    def _build_explanation(parsed: dict, detected_patterns, score: int, level) -> RiskExplanation:
        level_label = RISK_LEVEL_LABELS[level]
        llm_summary = parsed.get("summary", "").strip()
        summary = f"{level_label} 등급 (위험도 {score}점) — {llm_summary}"

        reasons = []
        for item, pattern in zip(parsed.get("detected_categories", []), detected_patterns):
            evidence = "、".join(item.get("evidence", [])[:3]) or "-"
            reasoning = item.get("reasoning", "").strip()
            reasons.append(f"[{pattern.category_label}] {reasoning} (근거: {evidence})")

        narrative = summary
        if reasons:
            narrative += "\n\n근거:\n" + "\n".join(f"- {r}" for r in reasons)

        return RiskExplanation(summary=summary, reasons=reasons, narrative=narrative)

    def _update_gpu_metric(self) -> None:
        try:
            ps = httpx.get(f"{self._base_url}/api/ps", timeout=5.0).json()
        except httpx.HTTPError:
            return
        for m in ps.get("models", []):
            if m.get("name") == self._model or m.get("model") == self._model:
                metrics.llm_gpu_memory_bytes.set(m.get("size_vram", 0))
                return
        metrics.llm_gpu_memory_bytes.set(0)
