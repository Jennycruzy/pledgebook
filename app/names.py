from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Iterable, Optional


TITLES = {
    "chief", "mrs", "mr", "barrister", "alhaji", "hajia", "deaconess", "deacon",
    "engineer", "dr", "pastor", "prof", "brother", "sister", "mama", "papa", "evangelist",
}


@dataclass(frozen=True)
class NameMatch:
    heard: str
    guest_id: Optional[int]
    guest_name: Optional[str]
    kind: str
    reason: Optional[str] = None


def normalize_name(name: str) -> str:
    words = re.findall(r"[a-z]+", name.lower())
    words = [word for word in words if word not in TITLES]
    return "".join(words)


def match_name(heard: str, guests: Iterable[dict]) -> NameMatch:
    heard_norm = normalize_name(heard)
    if not heard_norm:
        return NameMatch(heard, None, None, "flagged", "Name unclear — please confirm.")
    candidates = []
    for guest in guests:
        norm = normalize_name(guest["name"])
        if norm == heard_norm:
            return NameMatch(heard, guest["id"], guest["name"], "matched")
        ratio = SequenceMatcher(None, heard_norm, norm).ratio()
        if heard_norm in norm or norm in heard_norm:
            ratio = max(ratio, 0.88)
        candidates.append((ratio, guest))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates and candidates[0][0] >= 0.78 and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.08):
        guest = candidates[0][1]
        return NameMatch(heard, guest["id"], guest["name"], "suggested", f"Did you mean {guest['name']}?")
    return NameMatch(heard, None, None, "walk_in", "Name not on the guest list — please confirm.")
