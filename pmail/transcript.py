"""Heuristics for reading routing instructions out of a voice-note transcript.

This is a first pass, not the author of the email. It pulls out *who* the
speaker addressed and any subject hint so those can be confirmed against the
address book; the prose of the mail is written by the assistant reading the
same transcript. Everything here is advisory and shown to a human before send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contacts import EMAIL_RE

# Where a recipient list stops. Spoken sentences run on, so we cut at the point
# the speaker switches from addressing to dictating.
_STOP = (
    r"saying|to say|and say|say that|about|regarding|re |letting|to let|let them|"
    r"telling|to tell|tell them|that|with the|the message|the content|"
    r"message is|body|subject|asking|to ask|ask them|and mention|mentioning|"
    r"and copy|copying|and cc|and bcc|please|thanks"
)

# Where the speaker's sentence ends. A bare "." is not enough: it would cut
# "acme.com" in half, so a full stop only terminates when whitespace follows.
_SENTENCE_END = r"[;!?\n]|\.(?=\s|$)|$"

# Markers that hand off from "who and how" to "what to say".
_BODY_MARKERS = [
    r"\bsaying\b", r"\bto say\b", r"\bsay that\b", r"\btell them\b",
    r"\bletting them know\b", r"\blet them know\b", r"\bthe message is\b",
    r"\bbody\s*:", r"\bcontent\s*:", r"\bmessage\s*:",
]
_BODY_STOP = "|".join(m.strip("\\b") for m in _BODY_MARKERS)


def _term(stop: str = _STOP) -> str:
    return rf"(?=\s+(?:{stop})\b|{_SENTENCE_END})"


_TO_PATTERNS = [
    rf"\bsend(?:\s+(?:an|a|the))?\s+(?:email|mail|e-?mail|note|message|reply)\s+to\s+(?P<t>.+?){_term()}",
    rf"\b(?:email|mail|e-?mail|write|message|reply\s+to)\s+(?P<t>.+?){_term()}",
    rf"\bto\s*:\s*(?P<t>.+?)(?={_SENTENCE_END})",
    rf"\baddressed?\s+to\s+(?P<t>.+?){_term()}",
    # "Let Sara know that ...", "Tell the dev team about ..."
    r"\b(?:let|tell|remind|update|notify)\s+(?P<t>.+?)\s+(?:know|that|about)\b",
    # "Shoot Raj an email saying ...", "Send Sara a note about ..."
    r"\b(?:send|shoot|drop|fire off)\s+(?P<t>.+?)\s+an?\s+(?:email|mail|note|message|line)\b",
]

_CC_PATTERNS = [
    rf"\bcc\s*:?\s*(?P<t>.+?){_term()}",
    rf"\b(?:copy|loop|cc)\s+in\s+(?P<t>.+?){_term()}",
    r"\bkeep\s+(?P<t>.+?)\s+in\s+(?:the\s+)?loop\b",
    r"\bwith\s+(?P<t>.+?)\s+in\s+copy\b",
]

_BCC_PATTERNS = [
    rf"\bbcc\s*:?\s*(?P<t>.+?){_term()}",
    rf"\bblind\s+(?:copy|cc)\s+(?P<t>.+?){_term()}",
]

# Subject hints stop where dictation starts, so "subject X, saying Y" keeps X.
_SUBJECT_PATTERNS = [
    rf"\bsubject(?:\s+line)?\s*(?:is|should be|:)?\s*[\"']?(?P<t>.+?)(?=\s*[,.]?\s*(?:{_BODY_STOP})\b|[\"'{_SENTENCE_END[1:]})",
    rf"\btitle\s+it\s+[\"']?(?P<t>.+?)(?=\s*[,.]?\s*(?:{_BODY_STOP})\b|[\"']|{_SENTENCE_END})",
    rf"\bre\s*:\s*(?P<t>.+?)(?={_SENTENCE_END})",
    rf"\b(?:about|regarding)\s+(?P<t>.+?)(?=\s*[,.]?\s*(?:{_BODY_STOP})\b|\s+and\s+|{_SENTENCE_END})",
]

# Arabic (including Egyptian dialect) keywords. Routing is deliberately NOT
# parsed from Arabic: attached prepositions ("لسارة" = "to Sara") and dialect
# make regex extraction unreliable, and a wrong recipient cannot be recalled.
# Instead Arabic is detected and flagged so the caller supplies --to directly.
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

_INTERNAL_AR = re.compile(r"(داخلي|داخلية|داخليا|للفريق|لفريق العمل|بينا)")

_URGENT_AR = re.compile(r"(مستعجل|عاجل|ضروري|بسرعة|حالا|فورا|في أسرع وقت)")

_INTERNAL = re.compile(
    r"\b(internal(?:ly)?|in-?house|to the team|our team|internal note)\b", re.I
)

_URGENT = re.compile(
    r"\b(urgent|asap|as soon as possible|high priority|right away|immediately)\b",
    re.I,
)

_SPLIT = re.compile(r"\s*(?:,|;|&|\band\b|\bplus\b|\bas well as\b)\s*", re.I)

# Trailing routing instructions that belong to the envelope, not the message.
_ROUTING_TAIL = re.compile(
    r"[,.;]?\s*(?:and\s+|also\s+)?(?:please\s+)?"
    r"(?:cc|bcc|copy\s+in|loop\s+in|blind\s+copy)\b.*$",
    re.I | re.S,
)

_NOISE = {
    "", "the", "them", "him", "her", "everyone", "everybody", "all", "team",
    "guys", "folks", "people", "also", "too", "please", "him/her", "they",
}


def _split_recipients(blob: str) -> list[str]:
    """Turn 'Sarah, Raj and finance@acme.com' into three tokens."""
    blob = re.sub(r"^\s*(?:to|at|the)\s+", "", blob.strip(), flags=re.I)
    tokens = []
    for piece in _SPLIT.split(blob):
        piece = piece.strip().strip("\"'`,;:!?").strip()
        # Only strip a trailing full stop when it is not part of a domain.
        piece = re.sub(r"\.$", "", piece)
        piece = re.sub(r"^(?:to|and|also|plus|our|my|the)\s+", "", piece, flags=re.I)
        if piece.lower() in _NOISE or not piece:
            continue
        # Guard against a run-on clause being read as a name.
        if len(piece.split()) > 4 and not EMAIL_RE.search(piece):
            continue
        tokens.append(piece)
    return tokens


def _collect(text: str, patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            found.extend(_split_recipients(match.group("t")))
    # De-duplicate, preserving the order the speaker used.
    seen: set[str] = set()
    ordered = []
    for token in found:
        if token.lower() not in seen:
            seen.add(token.lower())
            ordered.append(token)
    return ordered


@dataclass
class ParsedVN:
    text: str
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    subject_hint: str = ""
    body_hint: str = ""
    urgent: bool = False
    internal: bool = False
    arabic: bool = False
    needs_manual_routing: bool = False
    literal_addresses: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.to or self.cc or self.bcc)


def normalise_spoken_addresses(text: str) -> str:
    """Speech-to-text writes addresses as 'sarah at acme dot com'."""
    text = re.sub(
        r"\b([\w.+-]+)\s+at\s+([\w-]+)\s+dot\s+(\w+)\b", r"\1@\2.\3", text, flags=re.I
    )
    # Handle multi-label domains: "raj at mail dot acme dot com".
    return re.sub(
        r"\b([\w.+-]+)@([\w.-]+)\s+dot\s+(\w+)\b", r"\1@\2.\3", text, flags=re.I
    )


def parse(text: str) -> ParsedVN:
    """Extract routing hints from a transcript. Never raises on odd input."""
    text = (text or "").strip()
    if not text:
        return ParsedVN(text="")

    normalised = normalise_spoken_addresses(text)

    cc = _collect(normalised, _CC_PATTERNS)
    bcc = _collect(normalised, _BCC_PATTERNS)

    # Anything already claimed as cc/bcc must not also land in To.
    claimed = {t.lower() for t in cc + bcc}
    to = [t for t in _collect(normalised, _TO_PATTERNS) if t.lower() not in claimed]

    subject_hint = ""
    for pattern in _SUBJECT_PATTERNS:
        if match := re.search(pattern, normalised, re.I):
            candidate = match.group("t").strip().strip("\"',")
            if candidate:
                subject_hint = candidate
                break

    body_hint = ""
    for marker in _BODY_MARKERS:
        if match := re.search(marker, normalised, re.I):
            body_hint = normalised[match.end():].strip().lstrip(":").strip()
            body_hint = _ROUTING_TAIL.sub("", body_hint).strip()
            break

    arabic = bool(ARABIC_RE.search(text))

    return ParsedVN(
        text=text,
        to=to,
        cc=cc,
        bcc=bcc,
        subject_hint=subject_hint,
        body_hint=body_hint,
        urgent=bool(_URGENT.search(normalised)) or bool(_URGENT_AR.search(text)),
        internal=bool(_INTERNAL.search(normalised)) or bool(_INTERNAL_AR.search(text)),
        arabic=arabic,
        # An Arabic note that yielded no recipients has not been understood,
        # which is different from a note that named nobody. Say so loudly.
        needs_manual_routing=arabic and not (to or cc or bcc),
        literal_addresses=EMAIL_RE.findall(normalised),
    )
