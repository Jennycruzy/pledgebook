from dataclasses import dataclass
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


def _name_phrase(text: str) -> Optional[str]:
    # Keep title plus up to three words. The title list mirrors names.py but
    # remains local so this extractor can work before a guest list is loaded.
    match = re.search(
        r"\b((?:Chief|Mrs\.?|Mr\.?|Barrister|Alhaji|Hajia|Deaconess|Deacon|Engineer|Dr\.?|Pastor|Prof\.?|Brother|Sister|Mama|Papa|Evangelist)\s+[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,2})",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip(" ,.!?") if match else None


def _amount_phrase(text: str) -> str:
    candidates = [
        r"(?:₦|\$|£)\s*\d[\d,]*(?:\.\d+)?\s*(?:[kKmM]|million|thousand)?",
        r"\b\d[\d,]*(?:\.\d+)?\s*(?:k|thousand|million|naira|dollars?|pounds?)\b",
        r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|fifty|hundred|a hundred|one point five|one million|quarter(?: of)? a? million|half(?: a)? million)(?:[\s-]+(?:hundred|thousand|million|naira|dollars?|pounds?|k|only|point|five))*",
        r"\b(?:quarter|half)\s+(?:of\s+)?(?:a\s+)?million\b",
        r"\b(?:what a million|two-fifty)\b",
        r"\b(?:a )?bag of cement\b|\bgenerator\b",
    ]
    found = []
    for pattern in candidates:
        found.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
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
    amount = parse_amount(_amount_phrase(text))
    return Turn(text, words, start_ms, end_ms, heard_name, amount, matched)


class TurnWindow:
    def __init__(self, max_gap_ms: int = 6000):
        self.max_gap_ms = max_gap_ms
        self.pending_name: Optional[Turn] = None
        self.pending_amount: Optional[Turn] = None

    def _fresh(self, current: Turn, pending: Optional[Turn]) -> bool:
        return pending is not None and current.start_ms - pending.end_ms <= self.max_gap_ms

    def add(self, turn: Turn) -> tuple[Optional[Turn], Optional[Turn], Optional[str]]:
        name_turn = turn if turn.name else None
        amount_turn = turn if turn.amount.is_clear else None

        if self.pending_name and not self._fresh(turn, self.pending_name):
            self.pending_name = None
        if self.pending_amount and not self._fresh(turn, self.pending_amount):
            self.pending_amount = None

        # First try same-turn pairing. A turn containing several names or
        # amounts has already been made ambiguous by extract_turn and will
        # not reach this branch.
        if name_turn and amount_turn:
            self.pending_name = None
            self.pending_amount = None
            return name_turn, amount_turn, None
        if name_turn and not amount_turn and "More than one amount" in (turn.amount.reason or ""):
            self.pending_name = None
            self.pending_amount = None
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
                self.pending_amount = amount_turn
                return None, previous, "Amount heard but the name is unclear."
        if name_turn and not amount_turn:
            if self.pending_amount:
                prior = self.pending_amount
                self.pending_amount = None
                return name_turn, prior, None
            self.pending_name = name_turn
        return None, None, None
