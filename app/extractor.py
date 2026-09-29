from dataclasses import dataclass, replace
import re
from typing import Iterable, Optional

from .amounts import Amount, parse_amount
from .names import NameMatch, match_name, normalize_name


@dataclass
class Turn:
    text: str
    words: list[dict]
    start_ms: int
    end_ms: int
    name: Optional[str]
    amount: Amount
    name_match: Optional[NameMatch]
    # Set when the amount was spoken before the name in the same turn, for
    # example "₦500,000. Brother Segun." The amount usually closes the
    # previous announcement, so the two are not paired with each other.
    split_at: Optional[int] = None


def _name_phrase(text: str) -> Optional[str]:
    # Keep title plus up to three words. The title list mirrors names.py but
    # remains local so this extractor can work before a guest list is loaded.
    match = re.search(
        r"\b((?:Chief|Mrs\.?|Mr\.?|Barrister|Alhaji|Hajia|Deaconess|Deacon|Engineer|Dr\.?|Pastor|Prof\.?|Brother|Sister|Mama|Papa|Evangelist)\s+[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,2})",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip(" ,.!?") if match else None


SCALES = (("million", 1_000_000), ("thousand", 1_000), ("hundred", 100))
ITEM = re.compile(r"\b(?:bags? of cement|generator)\b", re.IGNORECASE)


def _largest_scale(phrase: str) -> int:
    lower = phrase.lower()
    return max((value for word, value in SCALES if word in lower), default=1)


def _one_amount(text: str, left: list[int], right: tuple[int, int]) -> bool:
    """Whether two neighbouring amount matches are parts of one spoken amount.

    "two hundred and fifty thousand" and "one million, five hundred thousand"
    are single amounts; "fifty thousand, seventy thousand" is two, and must
    stay two so the clip is sent to a person.
    """

    gap = text[left[1]:right[0]].strip(" ,").lower()
    if gap not in ("", "and"):
        return False
    first, second = text[left[0]:left[1]], text[right[0]:right[1]]
    if re.search(r"\d", first + second):
        return False
    if ITEM.search(second):
        # A small count before a gift: "one bag of cement".
        return not gap and _largest_scale(first) == 1 and not ITEM.search(first)
    if ITEM.search(first):
        return False
    first_scale, second_scale = _largest_scale(first), _largest_scale(second)
    multiplier = first_scale < 1_000 and second_scale >= 1_000 and not re.search(r"naira|dollar|pound", first, re.IGNORECASE)
    return first_scale > second_scale or multiplier


def _amount_phrase(text: str) -> str:
    candidates = [
        r"(?:₦|\$|£)\s*\d[\d,]*(?:\.\d+)?\s*(?:[kKmM]|million|thousand)?",
        r"\b\d[\d,]*(?:\.\d+)?\s*(?:k|thousand|million|naira|dollars?|pounds?)\b",
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|a hundred|one point five|one million|quarter(?: of)? a? million|half(?: a)? million)\b(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine|hundred|thousand|million|naira|dollars?|pounds?|k|only|point)\b)*",
        r"\b(?:quarter|half)\s+(?:of\s+)?(?:a\s+)?million\b",
        r"\b(?:what a million|two-fifty)\b",
        r"\b(?:a )?bag of cement\b|\bgenerator\b",
    ]
    spans = []
    for pattern in candidates:
        spans.extend((m.start(), m.end()) for m in re.finditer(pattern, text, flags=re.IGNORECASE) if m.group(0).strip(" ,.!?;"))
    # Several patterns can match the same spoken amount ("quarter of a
    # million" and "quarter of a million naira"). Merge overlapping matches,
    # and join a count to the gift that follows it ("one bag of cement"), so
    # only genuinely separate amounts can make a clip ambiguous.
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and (start <= merged[-1][1] or _one_amount(text, merged[-1], (start, end))):
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    found = [text[start:end] for start, end in merged]
    # A confirming transcript may contain two bare numbers in one clip. Do
    # not pick one silently: returning the full sentence makes the amount
    # parser flag the clip for an usher instead.
    bare_numbers = [match.group(0).strip(" ,.!?;") for match in re.finditer(
        r"(?:₦|\$|£)?\s*\d[\d,]*(?:\.\d+)?\s*(?:[kKmM]|million|thousand|naira|dollars?|pounds?)?",
        text,
        flags=re.IGNORECASE,
    )]
    bare_numbers = [item for item in bare_numbers if re.search(r"\d", item)]
    if len(bare_numbers) > 1:
        return "__AMBIGUOUS_AMOUNT__"
    found_unique = {item.strip(" ,.!?;").casefold() for item in found if item.strip(" ,.!?;")}
    if len(found_unique) > 1:
        return "__AMBIGUOUS_AMOUNT__"
    if not found and len(bare_numbers) == 1:
        return bare_numbers[0]
    return max((item.strip(" ,.!?;") for item in found), key=len, default=text)


def extract_turn(text: str, words: Optional[list[dict]], guests: Iterable[dict]) -> Turn:
    words = words or []
    start_ms = int(min((word.get("start", 0) for word in words), default=0))
    end_ms = int(max((word.get("end", 0) for word in words), default=0))
    guest_rows = list(guests)
    heard_name = None
    matched = None
    normalized_text = normalize_name(text)
    if re.search(r"\b(?:anonymous|a son of the soil|a daughter of the soil|son of the soil|daughter of the soil)\b", text, re.IGNORECASE):
        heard_name = "Anonymous donor"
        matched = NameMatch(heard_name, None, None, "anonymous", "Anonymous pledge — no follow-up call.")
    matched_guests = []
    for guest in guest_rows:
        guest_norm = normalize_name(guest["name"])
        if guest_norm and guest_norm in normalized_text:
            matched_guests.append(guest)
    if heard_name is None and len(matched_guests) == 1:
        guest = matched_guests[0]
        heard_name = guest["name"]
        matched = NameMatch(heard_name, guest["id"], guest["name"], "matched")
    elif heard_name is None and len(matched_guests) > 1:
        matched = NameMatch(text, None, None, "ambiguous", "More than one guest name was heard — please check.")
    if heard_name is None:
        heard_name = _name_phrase(text)
        if heard_name and matched is None:
            matched = match_name(heard_name, guest_rows)
    phrase = _amount_phrase(text)
    amount = parse_amount(phrase)
    turn = Turn(text, words, start_ms, end_ms, heard_name, amount, matched)
    turn.split_at = _amount_before_name(text, phrase, heard_name, matched_guests)
    return turn


NAME_START = re.compile(
    r"\b(?:anonymous|a son of the soil|a daughter of the soil|son of the soil|daughter of the soil|Chief|Mrs\.?|Mr\.?|Barrister|Alhaji|Hajia|Deaconess|Deacon|Engineer|Dr\.?|Pastor|Prof\.?|Brother|Sister|Mama|Papa|Evangelist)\b",
    re.IGNORECASE,
)


def _amount_before_name(text: str, phrase: str, heard_name: Optional[str], matched_guests: list[dict]) -> Optional[int]:
    """Return where the name starts when a clear amount comes first in the turn."""

    if not heard_name or not phrase or phrase == text:
        return None
    # An MC correction can deliberately contain two amounts, so
    # ``_amount_phrase`` returns the ambiguity sentinel.  It is still vital
    # to recognise that both amounts occurred before the next donor's name;
    # otherwise that donor inherits the corrected amount and every later
    # announcement can become shifted by one person.
    if phrase.startswith("__"):
        amount_marker = re.search(
            r"(?:₦|\$|£)\s*\d|\b\d[\d,]*(?:\.\d+)?\s*(?:k|thousand|million|naira|dollars?|pounds?)?\b|"
            r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|quarter|half)\b",
            text,
            re.IGNORECASE,
        )
        amount_at = amount_marker.start() if amount_marker else -1
        amount_end = amount_marker.end() if amount_marker else -1
    else:
        amount_at = text.find(phrase)
        amount_end = amount_at + len(phrase)
    if amount_at < 0:
        return None
    candidates = []
    title = NAME_START.search(text, amount_end)
    if title:
        candidates.append(title.start())
    for guest in matched_guests:
        first = guest["name"].split()[0]
        found = re.search(re.escape(first), text[amount_end:], re.IGNORECASE)
        if found:
            candidates.append(amount_end + found.start())
    if not candidates:
        return None
    name_at = min(candidates)
    if name_at <= amount_at or re.search(r"\b(?:from|by)\b", text[amount_at + len(phrase):name_at], re.IGNORECASE):
        return None
    # Only when the name really is not also before the amount.
    before = text[:amount_at]
    if NAME_START.search(before) or any(guest["name"].split()[0].lower() in before.lower() for guest in matched_guests):
        return None
    return name_at


NO_AMOUNT = "A name was heard without a clear amount. Was this a pledge?"


def split_turn(turn: Turn) -> tuple[Turn, Turn]:
    """Split an amount-first turn into the closing amount and the next name."""

    words_before = len(turn.text[:turn.split_at].split())
    words = turn.words or []
    boundary = words[words_before]["start"] if words_before < len(words) else turn.end_ms
    last_amount_word = words[words_before - 1]["end"] if 0 < words_before <= len(words) else turn.start_ms
    amount_part = replace(turn, text=turn.text[:turn.split_at].strip(), name=None, name_match=None, split_at=None,
                          end_ms=int(last_amount_word), words=words[:words_before])
    name_part = replace(turn, text=turn.text[turn.split_at:].strip(), amount=Amount(None, None, None, NO_AMOUNT), split_at=None,
                        start_ms=int(boundary), words=words[words_before:])
    return amount_part, name_part


class TurnWindow:
    """Pair names and amounts across adjacent final turns.

    A name that never receives an amount is kept in `unpaired` so the caller
    can show it to a person instead of letting it disappear.
    """

    def __init__(self, max_gap_ms: int = 6000):
        self.max_gap_ms = max_gap_ms
        self.pending_name: Optional[Turn] = None
        self.pending_amount: Optional[Turn] = None
        self.unpaired: list[Turn] = []

    def _fresh(self, current: Turn, pending: Optional[Turn]) -> bool:
        return pending is not None and current.start_ms - pending.end_ms <= self.max_gap_ms

    def _drop_name(self) -> None:
        if self.pending_name is not None:
            self.unpaired.append(replace(self.pending_name, amount=Amount(None, None, None, NO_AMOUNT)))
            self.pending_name = None

    def _drop_amount(self) -> None:
        if self.pending_amount is not None:
            self.unpaired.append(self.pending_amount)
            self.pending_amount = None

    def take_unpaired(self) -> list[Turn]:
        names, self.unpaired = self.unpaired, []
        return names

    def flush(self) -> list[Turn]:
        """At the end of listening, hand back any name or amount still waiting."""

        self._drop_name()
        self._drop_amount()
        return self.take_unpaired()

    def add(self, turn: Turn) -> tuple[Optional[Turn], Optional[Turn], Optional[str]]:
        if turn.split_at is not None:
            amount_part, name_part = split_turn(turn)
            if amount_part.amount.is_clear:
                result = self._add(amount_part)
            elif self.pending_name and self._fresh(amount_part, self.pending_name):
                # A correction such as "50,000, sorry, 70,000. Dr Tola"
                # belongs to the pending donor.  Keep it as one visible,
                # flagged line and start Dr Tola's announcement empty.
                prior = self.pending_name
                self.pending_name = None
                result = prior, amount_part, amount_part.amount.reason
            else:
                self._drop_name()
                self.unpaired.append(amount_part)
                result = (None, None, amount_part.amount.reason)
            # The amount closed an earlier announcement; it must not be
            # paired with the name that follows it.
            self._drop_amount()
            self._drop_name()
            self.pending_name = name_part
            return result
        return self._add(turn)

    def _add(self, turn: Turn) -> tuple[Optional[Turn], Optional[Turn], Optional[str]]:
        name_turn = turn if turn.name else None
        amount_turn = turn if turn.amount.is_clear else None

        if self.pending_name and not self._fresh(turn, self.pending_name):
            self._drop_name()
        if self.pending_amount and not self._fresh(turn, self.pending_amount):
            self._drop_amount()

        # First try same-turn pairing. A turn containing several names or
        # amounts has already been made ambiguous by extract_turn and will
        # not reach this branch.
        if name_turn and amount_turn:
            self._drop_name()
            self._drop_amount()
            return name_turn, amount_turn, None
        if name_turn and not amount_turn and "More than one amount" in (turn.amount.reason or ""):
            self._drop_name()
            self._drop_amount()
            return name_turn, turn, turn.amount.reason

        # Pair only adjacent final turns. This prevents an old name from
        # being attached to a later amount after another donor has spoken.
        if amount_turn and not name_turn:
            if self.pending_name:
                prior = self.pending_name
                self.pending_name = None
                return prior, amount_turn, None
            previous = self.pending_amount
            self.pending_amount = amount_turn
            if previous:
                return None, previous, "Amount heard but the name is unclear."
        if name_turn and not amount_turn:
            if self.pending_amount:
                prior = self.pending_amount
                self.pending_amount = None
                return name_turn, prior, None
            self._drop_name()
            self.pending_name = name_turn
        return None, None, None
