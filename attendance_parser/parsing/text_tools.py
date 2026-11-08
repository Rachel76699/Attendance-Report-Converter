import re


_EXTRA_ONE_BEFORE_MONTH_PATTERN = re.compile(r"(?<!\d)(\d{2})1(\d{2}/\d{4})(?!\d)")
_EXTRA_ONE_IN_JANUARY_YEAR_PATTERN = re.compile(r"(?<![\d/])(\d{1,2})/11(\d{2})(?!\d)")
_EXTRA_ONE_AFTER_JANUARY_DAY_PATTERN = re.compile(r"(?<![\d/])(\d{1,2})11/(\d{2})(?![\d/])")
_JANUARY_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})/1/\d{2,4}(?!\d)")
_STANDALONE_O_PATTERN = re.compile(r"(?<!\S)O(?!\S)")


def normalize_ocr_text(text: str) -> str:
    """Repair date and zero OCR errors observed in the sample attendance reports."""
    has_january_dates = bool(_JANUARY_DATE_PATTERN.search(text))
    text = _EXTRA_ONE_BEFORE_MONTH_PATTERN.sub(r"\1/\2", text)
    text = _EXTRA_ONE_IN_JANUARY_YEAR_PATTERN.sub(r"\1/1/\2", text)
    if has_january_dates:
        text = _EXTRA_ONE_AFTER_JANUARY_DAY_PATTERN.sub(r"\1/1/\2", text)
    return _STANDALONE_O_PATTERN.sub("0", text)


def reconstruct_ocr_rows(words: list[tuple[float, float, float, str]]) -> str:
    """Rebuild scanned table rows from OCR word positions."""
    sorted_words = sorted(words, key=lambda word: (word[1], word[0]))
    row_groups: list[list[tuple[float, float, float, str]]] = []

    for word in sorted_words:
        x, y, height, _ = word
        matching_group = next(
            (
                group for group in reversed(row_groups)
                if abs(sum(item[1] for item in group) / len(group) - y) <= max(9.0, height * 0.6)
            ),
            None
        )
        if matching_group is None:
            row_groups.append([word])
        else:
            matching_group.append(word)

    lines = []
    for group in row_groups:
        group.sort(key=lambda word: word[0])
        line_text = ""
        previous_right = None
        for x, _, _, text in group:
            if previous_right is None:
                line_text = text
            elif x - previous_right > 18:
                line_text += " | " + text
            else:
                line_text += text
            previous_right = x
        lines.append(line_text)
    return "\n".join(lines)
