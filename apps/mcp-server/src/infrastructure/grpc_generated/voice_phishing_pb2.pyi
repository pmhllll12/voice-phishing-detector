from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AnalyzeRequest(_message.Message):
    __slots__ = ("transcript",)
    TRANSCRIPT_FIELD_NUMBER: _ClassVar[int]
    transcript: str
    def __init__(self, transcript: _Optional[str] = ...) -> None: ...

class DetectedPattern(_message.Message):
    __slots__ = ("category", "category_label", "matched_keywords")
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_LABEL_FIELD_NUMBER: _ClassVar[int]
    MATCHED_KEYWORDS_FIELD_NUMBER: _ClassVar[int]
    category: str
    category_label: str
    matched_keywords: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, category: _Optional[str] = ..., category_label: _Optional[str] = ..., matched_keywords: _Optional[_Iterable[str]] = ...) -> None: ...

class SimilarCase(_message.Message):
    __slots__ = ("case_id", "title", "category", "summary", "source_note", "similarity")
    CASE_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SOURCE_NOTE_FIELD_NUMBER: _ClassVar[int]
    SIMILARITY_FIELD_NUMBER: _ClassVar[int]
    case_id: str
    title: str
    category: str
    summary: str
    source_note: str
    similarity: float
    def __init__(self, case_id: _Optional[str] = ..., title: _Optional[str] = ..., category: _Optional[str] = ..., summary: _Optional[str] = ..., source_note: _Optional[str] = ..., similarity: _Optional[float] = ...) -> None: ...

class AnalyzeResponse(_message.Message):
    __slots__ = ("detected_patterns", "pattern_count", "has_risk_indicators", "risk_score", "risk_level", "explanation_summary", "explanation_reasons", "explanation", "similar_cases")
    DETECTED_PATTERNS_FIELD_NUMBER: _ClassVar[int]
    PATTERN_COUNT_FIELD_NUMBER: _ClassVar[int]
    HAS_RISK_INDICATORS_FIELD_NUMBER: _ClassVar[int]
    RISK_SCORE_FIELD_NUMBER: _ClassVar[int]
    RISK_LEVEL_FIELD_NUMBER: _ClassVar[int]
    EXPLANATION_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    EXPLANATION_REASONS_FIELD_NUMBER: _ClassVar[int]
    EXPLANATION_FIELD_NUMBER: _ClassVar[int]
    SIMILAR_CASES_FIELD_NUMBER: _ClassVar[int]
    detected_patterns: _containers.RepeatedCompositeFieldContainer[DetectedPattern]
    pattern_count: int
    has_risk_indicators: bool
    risk_score: int
    risk_level: str
    explanation_summary: str
    explanation_reasons: _containers.RepeatedScalarFieldContainer[str]
    explanation: str
    similar_cases: _containers.RepeatedCompositeFieldContainer[SimilarCase]
    def __init__(self, detected_patterns: _Optional[_Iterable[_Union[DetectedPattern, _Mapping]]] = ..., pattern_count: _Optional[int] = ..., has_risk_indicators: _Optional[bool] = ..., risk_score: _Optional[int] = ..., risk_level: _Optional[str] = ..., explanation_summary: _Optional[str] = ..., explanation_reasons: _Optional[_Iterable[str]] = ..., explanation: _Optional[str] = ..., similar_cases: _Optional[_Iterable[_Union[SimilarCase, _Mapping]]] = ...) -> None: ...
