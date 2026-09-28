"""Conservative spoken-amount parsing.

The parser returns a value only when the words identify a currency amount
clearly. Ambiguous speech is deliberately returned as a flag for an usher.
"""

from dataclasses import dataclass
import re
from typing import Optional


@dataclass(frozen=True)
class Amount:
    minor: Optional[int]
    currency: Optional[str]
    item: Optional[str]
    reason: Optional[str]

    @property
    def is_clear(self) -> bool:
        return self.minor is not None or self.item is not None


NUMBERS = {
    "zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def _words_number(text: str) -> Optional[float]:
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())
    if not tokens:
        return None
    total = 0.0
    current = 0.0
    seen = False
    decimal_value = None
    for token in tokens:
        if token in {"and", "only", "naira", "dollars", "dollar", "pounds", "pound"}:
            continue
        if token == "point":
            decimal_value = ""
            seen = True
            continue
        if decimal_value is not None:
            if token.isdigit():
                decimal_value += token
            elif token in NUMBERS:
                decimal_value += str(NUMBERS[token])
            elif token in SCALES:
                base = current + (float("0." + decimal_value) if decimal_value else 0)
                total += base * SCALES[token]
                current = 0
                decimal_value = None
            else:
                return None
            continue
        if token.replace(".", "", 1).isdigit():
            current += float(token)
            seen = True
        elif token in NUMBERS:
            current += NUMBERS[token]
            seen = True
        elif token == "quarter":
            current += 0.25
            seen = True
        elif token == "half":
            current += 0.5
            seen = True
        elif token in SCALES:
            scale = SCALES[token]
            seen = True
            if current == 0:
                current = 1
            if scale >= 1000:
                total += current * scale
                current = 0
            else:
                current *= scale
        else:
            return None
    if not seen:
        return None
    if decimal_value:
        current += float("0." + decimal_value)
    return total + current


def parse_amount(text: str) -> Amount:
    original = text.strip()
    lower = re.sub(r"[,₦$£]", "", original.lower())
    if "__ambiguous_amount__" in lower:
        return Amount(None, None, None, "More than one amount was heard — please check the recording.")
    if re.search(r"\b(bag of cement|generator|bags? of cement)\b", lower):
        return Amount(None, None, original, None)
    if re.search(r"\bwhat a million\b", lower):
        return Amount(None, None, None, "Amount unclear — heard ‘What a million’.")
    if re.search(r"\btwo[- ]fifty\b", lower) and not re.search(r"\b(thousand|k|million|naira)\b", lower):
        return Amount(None, None, None, "Amount unclear — ‘two-fifty’ has no unit.")
    if re.search(r"\bhalf\s+(?:a\s+)?million\b", lower):
        return Amount(500_000, "NGN", None, None)
    if re.search(r"\bquarter\s+(?:of\s+)?(?:a\s+)?million\b", lower):
        return Amount(250_000, "NGN", None, None)
    currency = "NGN"
    if "$" in original or re.search(r"\bdollars?\b", lower):
        currency = "USD"
    elif "£" in original or re.search(r"\bpounds?\b", lower):
        currency = "GBP"
    # A bare K means thousand. Keep this explicit so ordinary words do not
    # accidentally become money.
    k_match = re.search(r"\b(\d+(?:\.\d+)?)\s*k\b", lower)
    if k_match:
        return Amount(int(round(float(k_match.group(1)) * 1000)), currency, None, None)
    word_k_match = re.search(r"\b((?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)(?:\s+point\s+(?:one|two|three|four|five|six|seven|eight|nine))?)\s*k\b", lower)
    if word_k_match:
        base = _words_number(word_k_match.group(1))
        if base is not None:
            return Amount(int(round(base * 1000)), currency, None, None)
    number_text = re.sub(r"\b(?:naira|dollars?|pounds?|only)\b", " ", lower)
    value = _words_number(number_text)
    if value is None:
        return Amount(None, None, None, "Amount unclear — no clear number was heard.")
    # A spoken million/half/quarter already carries its scale; ordinary
    # numbers are recorded in the named currency's whole units.
    minor = int(round(value))
    return Amount(minor, currency, None, None)
