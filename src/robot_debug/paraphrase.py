"""Instruction paraphrases and the word edits between two wordings (ADR 0032, breadth pack).

Two halves with different homes:

*Local* (the workstation, Python 3.11): :func:`request_paraphrases` asks Nemotron on Token Factory
for varied rewordings of a task instruction and validates them. The API key never leaves the
workstation and never enters a Job.

*Job-safe* (also imported by the ``paraphrase-screen`` / ``paraphrase-reduce`` Job modes, so
Python 3.8 compatible and standard library only): :func:`tokenize`, :func:`word_edits` and
:func:`apply_edits`. The word edits between the original instruction and a failing paraphrase are
the items delta debugging reduces: each edit is independent, so any subset of them applied to the
original is a (possibly odd, but well-formed) instruction.

Edits come from ``difflib`` opcodes over tokens (words, with their internal hyphens and
apostrophes, and single punctuation marks), so they are deterministic. A candidate text is the
original's tokens with the chosen edits applied, joined with the spacing each token had in its
own source text; the empty subset is the original wording and the full set is the paraphrase.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Coordinator, October 15, 2026: the measured comparison (ADR 0030 rule) chose Nemotron 3 Super
# for paraphrase generation. A spec may override it with ``paraphrase.model``.
PARAPHRASE_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_COUNT = 10
MAX_COUNT = 12
EXTRA_REQUESTED = 2              # asked for beyond the wanted count, to absorb rejected duplicates
MAX_REPLY_ITEMS = 40
MIN_CHARS, MAX_CHARS = 1, 200
# Task language Faultline has verified against the benchmark, by (suite, task). Any other task
# needs ``paraphrase.instruction`` in the spec (the text the benchmark gives that task).
KNOWN_INSTRUCTIONS = {
    ("libero_object", 0): "pick up the alphabet soup and place it in the basket",
}

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['\-][A-Za-z0-9]+)*|[^\sA-Za-z0-9]")
_SPACES = re.compile(r"\s+")
# Typographic characters models like to emit, mapped to the ASCII the task instructions use.
_ASCII_FIXES = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "…": "...", " ": " ",
}

SYSTEM_PROMPT = (
    "You rewrite one instruction given to a robot manipulation policy. Return exactly one JSON "
    'object of the form {"paraphrases": ["...", "..."]} and nothing else. Each paraphrase must ask '
    "for exactly the same action on exactly the same object and target as the original, so only the "
    "wording changes. Vary synonyms, word order, politeness, verbosity, terseness and register across "
    "the paraphrases (some polite, some curt, some wordy, some plain). Use plain ASCII only, no "
    "numbering, no quotation marks around the whole text, each under 120 characters, and every "
    "paraphrase different from the others and from the original."
)


class ParaphraseError(ValueError):
    """A paraphrase or edit is invalid; the message is a fixed reason code, never model text."""


# --- Job-safe: tokens, edits ---------------------------------------------------------------------


def normalize(text: str) -> str:
    """The text with its whitespace collapsed to single spaces and trimmed."""

    return _SPACES.sub(" ", text).strip()


def tokenize(text: str) -> List[str]:
    """Words (letters and digits, with inner hyphens and apostrophes) and single punctuation marks."""

    return [match.group(0) for match in _TOKEN.finditer(text)]


def _spaced_tokens(text: str) -> List[Tuple[str, bool]]:
    """``(token, preceded_by_whitespace)`` for every token of ``text``."""

    return [(match.group(0), match.start() > 0 and text[match.start() - 1].isspace())
            for match in _TOKEN.finditer(text)]


def _join(pieces: Sequence[Tuple[str, bool]]) -> str:
    out = ""
    for index, (token, spaced) in enumerate(pieces):
        if index and (spaced or (out[-1].isalnum() and token[0].isalnum())):
            out += " "
        out += token
    return out


def word_edits(original: str, paraphrase: str) -> List[Dict[str, Any]]:
    """The independent token edits that turn ``original`` into ``paraphrase``, in order.

    Each edit is ``{"id", "start", "end", "original", "replacement", "spaced", "next_spaced"}``: it
    replaces the original tokens ``[start, end)`` (an insertion has ``start == end``, a deletion an
    empty ``replacement``) with ``replacement``; ``spaced`` says, per replacement token, whether it
    had whitespace before it in the paraphrase, and ``next_spaced`` whether the token right after
    the edit did (``None`` at the end), so a hybrid never gains or loses a space next to inserted
    punctuation ("Please, pick" not "Please,pick"). Edits never overlap, are ordered by position and are
    numbered from 0. The result is JSON-clean and deterministic.
    """

    old = tokenize(original)
    new = _spaced_tokens(paraphrase)
    matcher = difflib.SequenceMatcher(None, old, [token for token, _ in new], autojunk=False)
    edits = []  # type: List[Dict[str, Any]]
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        edits.append({
            "id": len(edits), "start": i1, "end": i2, "original": old[i1:i2],
            "replacement": [token for token, _ in new[j1:j2]], "spaced": [spaced for _, spaced in new[j1:j2]],
            "next_spaced": new[j2][1] if j2 < len(new) else None,
        })
    return edits


def validate_edits(original: str, edits: Any) -> List[Dict[str, Any]]:
    """The edits as a clean list, or :class:`ParaphraseError`; checks them against ``original``."""

    if type(edits) is not list:
        raise ParaphraseError("invalid_edits")
    old = tokenize(original)
    clean = []  # type: List[Dict[str, Any]]
    position = 0
    keys = {"id", "start", "end", "original", "replacement", "spaced", "next_spaced"}
    for edit in edits:
        if type(edit) is not dict or set(edit) != keys:
            raise ParaphraseError("invalid_edits")
        start, end = edit["start"], edit["end"]
        if (type(edit["id"]) is not int or type(start) is not int or type(end) is not int
                or not position <= start <= end <= len(old)):
            raise ParaphraseError("invalid_edits")
        for name in ("original", "replacement"):
            tokens = edit[name]
            if type(tokens) is not list or any(
                    type(token) is not str or not token or _TOKEN.fullmatch(token) is None
                    for token in tokens):
                raise ParaphraseError("invalid_edits")
        spaced = edit["spaced"]
        if (type(spaced) is not list or len(spaced) != len(edit["replacement"])
                or any(type(item) is not bool for item in spaced)):
            raise ParaphraseError("invalid_edits")
        if edit["original"] != old[start:end] or (start == end and not edit["replacement"]) or (
                start != end and edit["original"] == edit["replacement"]):
            raise ParaphraseError("invalid_edits")
        # Adjacent edits would be one edit; an insertion directly after another edit likewise.
        if clean and start == clean[-1]["end"]:
            raise ParaphraseError("invalid_edits")
        if edit["next_spaced"] is not None and type(edit["next_spaced"]) is not bool:
            raise ParaphraseError("invalid_edits")
        clean.append({"id": edit["id"], "start": start, "end": end, "original": list(edit["original"]),
                      "replacement": list(edit["replacement"]), "spaced": list(spaced),
                      "next_spaced": edit["next_spaced"]})
        position = end
    if len({edit["id"] for edit in clean}) != len(clean):
        raise ParaphraseError("invalid_edits")
    return clean


def apply_edits(original: str, edits: Sequence[Mapping[str, Any]]) -> str:
    """``original`` with the given edits (any ordered, non-overlapping subset) applied.

    Raises :class:`ParaphraseError` when an edit does not belong to ``original`` or the result
    would be empty. No edits gives back the original wording (whitespace normalised).
    """

    old = _spaced_tokens(original)
    pieces = []  # type: List[Tuple[str, bool]]
    cursor = 0
    for edit in edits:
        start, end = edit["start"], edit["end"]
        if not cursor <= start <= end <= len(old) or [t for t, _ in old[start:end]] != list(edit["original"]):
            raise ParaphraseError("invalid_edits")
        pieces.extend(old[cursor:start])
        pieces.extend(zip(edit["replacement"], edit["spaced"]))
        cursor = end
        if edit.get("next_spaced") is not None and cursor < len(old):
            # The token after an edit takes the paraphrase's spacing, not the original's.
            token, _ = old[cursor]
            old = old[:cursor] + [(token, bool(edit["next_spaced"]))] + old[cursor + 1:]
    pieces.extend(old[cursor:])
    if not pieces:
        raise ParaphraseError("empty_text")
    return _join(pieces)


def edit_label(edit: Mapping[str, Any]) -> str:
    """A short human reading of one edit, e.g. ``"pick up" -> "grab"`` or ``insert "please"``."""

    before, after = " ".join(edit["original"]), " ".join(edit["replacement"])
    if not before:
        return 'insert "{}"'.format(after)
    if not after:
        return 'delete "{}"'.format(before)
    return '"{}" -> "{}"'.format(before, after)


# --- meaning check (Job-safe, pure) --------------------------------------------------------------

MEANING_KEPT = "kept"
MEANING_DROPPED = "object_or_target_dropped"
# Words of four or more letters that are not objects or targets: action verbs, prepositions, articles
# and fillers. A paraphrase may reword these freely; every other long word of the original (the object,
# its qualifiers, the target) must still be there. October 15, 2026: a Nemotron Nano paraphrase said
# "container" for "basket" and failed, which proved nothing about wording.
MEANING_STOPWORDS = frozenset((
    "pick", "place", "put", "move", "take", "grab", "lift", "open", "close", "turn", "push", "pull",
    "carry", "drop", "bring", "give", "both", "into", "inside", "onto", "over", "with", "from", "then",
    "and", "the", "them", "that", "this", "those", "these", "next", "also", "each", "please", "kindly",
    "would", "could", "will", "your", "have", "there", "their", "they",
))
_WORD_PARTS = re.compile(r"[a-z0-9]+")


def _content_words(text: str) -> List[str]:
    words = []  # type: List[str]
    for token in tokenize(text.lower()):
        for part in _WORD_PARTS.findall(token):
            if len(part) >= 4 and part not in MEANING_STOPWORDS and part not in words:
                words.append(part)
    return words


def _present(word: str, available: Sequence[str]) -> bool:
    return any(item == word or item == word + "s" or item + "s" == word for item in available)


def meaning_check(original: str, paraphrase: str) -> str:
    """``"kept"``, or ``"object_or_target_dropped"`` when a content word of ``original`` is missing.

    A content word is a word of four or more letters that is not in :data:`MEANING_STOPWORDS`. It
    counts as present when the paraphrase has it, case-insensitively and allowing a trailing "s" on
    either side (hyphenated words are compared by their parts). A cheap guard against a "failure" that
    comes from a changed task (a different object or target) rather than from the wording alone; it
    cannot tell a synonym from a different object, so a flagged paraphrase may be a harmless reword.
    """

    available = []  # type: List[str]
    for token in tokenize(paraphrase.lower()):
        available.extend(_WORD_PARTS.findall(token))
    for word in _content_words(original):
        if not _present(word, available):
            return MEANING_DROPPED
    return MEANING_KEPT


# --- local: validation and generation ---------------------------------------------------------------


def clean_instruction(text: Any) -> str:
    """A normalised instruction of 1 to 200 printable ASCII characters, else :class:`ParaphraseError`."""

    if type(text) is not str:
        raise ParaphraseError("not_text")
    for char, fix in _ASCII_FIXES.items():
        text = text.replace(char, fix)
    text = normalize(text)
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        raise ParaphraseError("bad_length")
    if any(not 32 <= ord(char) < 127 for char in text):
        raise ParaphraseError("not_ascii")
    if any(char in text for char in "${}"):
        # The harness loads evaluator configs with OmegaConf interpolation; ${...} would be expanded.
        raise ParaphraseError("interpolation_characters")
    return text


def has_words(text: str) -> bool:
    """Whether ``text`` has at least one word token (not only punctuation)."""

    return any(token[0].isalnum() for token in tokenize(text))


def _fingerprint(text: str) -> str:
    return "".join(text.lower().split())


def validate_paraphrases(original: str, candidates: Sequence[Any],
                         count: int = DEFAULT_COUNT) -> Tuple[List[str], List[Dict[str, str]]]:
    """``(accepted, rejected)``: up to ``count`` distinct paraphrases of 1 to 200 printable ASCII
    characters, none identical to the original or to an earlier one (case and spacing ignored).

    ``rejected`` lists ``{"text", "reason"}`` for every candidate dropped (text clipped to 200).
    """

    seen = {_fingerprint(clean_instruction(original))}
    accepted = []  # type: List[str]
    rejected = []  # type: List[Dict[str, str]]
    for candidate in candidates:
        try:
            text = clean_instruction(candidate)
            if not has_words(text):
                raise ParaphraseError("no_words")
            if _fingerprint(text) in seen:
                raise ParaphraseError("duplicate")
        except ParaphraseError as error:
            rejected.append({"text": candidate[:MAX_CHARS] if type(candidate) is str else "", "reason": str(error)})
            continue
        if len(accepted) >= count:
            rejected.append({"text": text, "reason": "over_count"})
            continue
        seen.add(_fingerprint(text))
        accepted.append(text)
    return accepted, rejected


def build_prompt(instruction: str, count: int) -> Dict[str, str]:
    """The system and user message for ``count`` paraphrases of ``instruction``."""

    text = clean_instruction(instruction)
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise ValueError("count must be an integer from 1 to {}".format(MAX_COUNT))
    user = json.dumps({"instruction": text, "paraphrase_count": count + EXTRA_REQUESTED},
                      ensure_ascii=True, separators=(",", ":"))
    return {"system": SYSTEM_PROMPT, "user": user}


def _pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-standard constant")


def parse_reply(content: Any) -> List[Any]:
    """The ``paraphrases`` list of a strict ``{"paraphrases": [...]}`` reply, else :class:`ParaphraseError`."""

    if type(content) is not str:
        raise ParaphraseError("invalid_json")
    try:
        data = json.loads(content, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ParaphraseError("invalid_json") from None
    if type(data) is not dict or set(data) != {"paraphrases"}:
        raise ParaphraseError("invalid_shape")
    items = data["paraphrases"]
    if type(items) is not list or not items or len(items) > MAX_REPLY_ITEMS:
        raise ParaphraseError("invalid_shape")
    if any(type(item) is not str for item in items):
        raise ParaphraseError("invalid_shape")
    return items


def request_paraphrases(instruction: str, count: int, api_key: str, model: str = PARAPHRASE_MODEL,
                        transport: Optional[Any] = None) -> Dict[str, Any]:
    """Ask Nemotron on Token Factory for ``count`` varied paraphrases of ``instruction``.

    One catalog read and at most one bounded POST (temperature 0.7, thinking off, JSON object).
    Nothing raises for a model or network problem: the result has an empty ``paraphrases`` list and a
    fixed ``fallback_reason`` code instead. A malformed ``instruction`` or ``count`` raises
    ``ValueError`` before any call.

    Returns ``original`` (the cleaned instruction), ``paraphrases`` (validated, at most ``count``),
    ``rejected`` (``{"text", "reason"}`` for every dropped candidate), ``model``, ``fallback_reason``,
    ``provenance`` and ``raw_content`` (the model text; never one containing the key).
    """

    from . import token_factory

    prompt = build_prompt(instruction, count)
    result = {"original": clean_instruction(instruction), "paraphrases": [], "rejected": [], "model": model,
              "fallback_reason": None, "provenance": None, "raw_content": None}  # type: Dict[str, Any]
    reply = token_factory.request_paraphrase_reply(prompt, api_key, model=model, transport=transport)
    result["provenance"], result["raw_content"] = reply["provenance"], reply["content"]
    if reply["content"] is None:
        result["fallback_reason"] = reply["fallback_reason"] or "invalid_response"
        return result
    try:
        items = parse_reply(reply["content"])
    except ParaphraseError as error:
        result["fallback_reason"] = str(error)
        return result
    accepted, rejected = validate_paraphrases(result["original"], items, count)
    result["paraphrases"], result["rejected"] = accepted, rejected
    if not accepted:
        result["fallback_reason"] = "no_valid_paraphrases"
    return result


__all__ = [
    "DEFAULT_COUNT", "KNOWN_INSTRUCTIONS", "MAX_CHARS", "MAX_COUNT", "MEANING_DROPPED", "MEANING_KEPT",
    "MEANING_STOPWORDS", "PARAPHRASE_MODEL", "has_words", "meaning_check", "ParaphraseError", "SYSTEM_PROMPT",
    "apply_edits", "build_prompt", "clean_instruction", "edit_label", "normalize", "parse_reply",
    "request_paraphrases", "tokenize", "validate_edits", "validate_paraphrases", "word_edits",
]
