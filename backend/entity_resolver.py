from dataclasses import dataclass
from difflib import SequenceMatcher
import re


DOMAIN_ENTITIES = (
    "GenLab",
    "Akshen",
    "Gowri",
    "Kabil",
    "Reshma",
    "Britta",
    "Nagercoil",
    "Bengaluru",
    "Brand Studio",
    "AI Forge",
    "Launchpad",
    "Gen Z",
)

_ALIASES = {
    "jindlab": "GenLab",
    "jenlav": "GenLab",
    "jenlab": "GenLab",
    "nagarkoi": "Nagercoil",
}
_TOKEN_PATTERN = re.compile(r"[\w&.-]+", flags=re.UNICODE)
_FUZZY_THRESHOLD = 0.82
_FUZZY_MARGIN = 0.10


@dataclass(frozen=True)
class EntityResolution:
    raw_transcript: str
    corrected_transcript: str
    corrections: tuple[tuple[str, str], ...]


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _resolve_candidate(candidate: str) -> str | None:
    normalized = _normalize(candidate)
    is_multiword = len(_TOKEN_PATTERN.findall(candidate)) > 1
    if not normalized:
        return None

    for entity in DOMAIN_ENTITIES:
        if normalized == _normalize(entity) and (
            len(_TOKEN_PATTERN.findall(entity)) > 1
        ) == is_multiword:
            return entity

    alias_match = _ALIASES.get(normalized)
    if alias_match:
        return alias_match

    ranked = sorted(
        (
            SequenceMatcher(None, normalized, _normalize(entity)).ratio(),
            entity,
        )
        for entity in DOMAIN_ENTITIES
        if (len(_TOKEN_PATTERN.findall(entity)) > 1) == is_multiword
    )
    best_score, best_entity = ranked[-1]
    next_score = ranked[-2][0] if len(ranked) > 1 else 0.0
    if best_score >= _FUZZY_THRESHOLD and best_score - next_score >= _FUZZY_MARGIN:
        return best_entity
    return None


def resolve_domain_entities(raw_transcript: str) -> EntityResolution:
    """Correct confident domain-entity matches without rewriting unrelated words."""
    tokens = list(_TOKEN_PATTERN.finditer(raw_transcript))
    replacements: list[tuple[int, int, str, str]] = []
    token_index = 0

    while token_index < len(tokens):
        match: tuple[int, str, str] | None = None
        for token_count in (2, 1):
            end_index = token_index + token_count
            if end_index > len(tokens):
                continue
            candidate_tokens = tokens[token_index:end_index]
            candidate = raw_transcript[
                candidate_tokens[0].start() : candidate_tokens[-1].end()
            ]
            entity = _resolve_candidate(candidate)
            if entity:
                match = (end_index, candidate, entity)
                break

        if match is None:
            token_index += 1
            continue

        end_index, candidate, entity = match
        span_start = tokens[token_index].start()
        span_end = tokens[end_index - 1].end()
        replacements.append((span_start, span_end, candidate, entity))
        token_index = end_index

    corrected = raw_transcript
    for span_start, span_end, _, entity in reversed(replacements):
        corrected = corrected[:span_start] + entity + corrected[span_end:]

    corrections = tuple((candidate, entity) for _, _, candidate, entity in replacements if candidate != entity)
    return EntityResolution(
        raw_transcript=raw_transcript,
        corrected_transcript=corrected,
        corrections=corrections,
    )
