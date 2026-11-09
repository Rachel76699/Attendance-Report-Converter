import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from domain.models import ReportType
from parsing.text_tools import normalize_ocr_text


_TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_TYPE_B_KEYWORDS = (
    "כרטיס עובד", "כרטסת עובד", "כרטסת", "שעת כניסה",
    "שענת כניסה", "שעת יציאה", "יום בשבוע", "הערות",
    "סה\"כ שעות חודשיות", "מחיר לשעה",
)
_TYPE_A_KEYWORDS = ("125%", "150%", "100%", "שבת", "גליליון")


@dataclass(frozen=True)
class ClassificationEvidence:
    normalized_text: str
    text: str


def _normalized_parts(raw_text: str) -> tuple[str, str]:
    normalized_text = normalize_ocr_text(raw_text or "").lower()
    return normalized_text, re.sub(r"\s+", " ", normalized_text).strip()


def _type_b_row_count(normalized_text: str) -> int:
    count = 0
    for line in normalized_text.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if (
            3 <= len(parts) - 1 <= 5
            and _NUMBER_PATTERN.fullmatch(parts[0]) is not None
            and len(_TIME_PATTERN.findall(line)) == 2
        ):
            count += 1
    return count


def _type_a_score(evidence: ClassificationEvidence) -> int:
    return sum(keyword in evidence.text for keyword in _TYPE_A_KEYWORDS)


def _type_b_score(evidence: ClassificationEvidence) -> int:
    if _type_b_row_count(evidence.normalized_text) >= 3:
        return 10_000
    type_b_score = sum(keyword in evidence.text for keyword in _TYPE_B_KEYWORDS)
    type_a_score = _type_a_score(evidence)
    if type_b_score and (
        type_b_score >= type_a_score or "כרטיס עובד" in evidence.text
    ):
        return type_b_score
    return 0


ClassifierScorer = Callable[[ClassificationEvidence], int]
CLASSIFIER_SCORERS: Mapping[ReportType, ClassifierScorer] = MappingProxyType({
    ReportType.TYPE_A: _type_a_score,
    ReportType.TYPE_B: _type_b_score,
})
_CLASSIFIER_PRIORITY: Mapping[ReportType, int] = MappingProxyType({
    ReportType.TYPE_A: 0,
    ReportType.TYPE_B: 1,
})


def classify_report_type(raw_text: str) -> ReportType | None:
    """
    מזהה את סוג הדו"ח באופן מדויק על סמך טקסט ה-OCR.
    """
    normalized_text, text = _normalized_parts(raw_text)
    if not text:
        return None
    evidence = ClassificationEvidence(normalized_text, text)

    scores = {
        report_type: scorer(evidence)
        for report_type, scorer in CLASSIFIER_SCORERS.items()
    }
    candidates = [
        (score, _CLASSIFIER_PRIORITY.get(report_type, 0), report_type)
        for report_type, score in scores.items()
        if score > 0
    ]
    if not candidates:
        return None
    return max(candidates)[2]