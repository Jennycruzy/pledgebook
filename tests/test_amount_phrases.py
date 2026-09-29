import pytest

from app.extractor import extract_turn


# None means the clip must go to a person: two amounts were spoken.
CASES = {
    "fifty thousand, seventy thousand naira": None,
    "Emeka fifty thousand. Ngozi twenty thousand.": None,
    "two hundred thousand, two hundred thousand naira": None,
    "fifty thousand and seventy thousand": None,
    "Alhaji Ibrahim Musa, fifty thousand, sorry, seventy thousand naira.": None,
    "50K. Alhaji Ibrahim Musa, quarter million.": None,
    "fifty thousand and a generator": None,
    "Chief Emeka Okonkwo, two hundred and fifty thousand naira.": 250_000,
    "one million, five hundred thousand naira": 1_500_000,
    "Hajia Aisha Bello, quarter of a million naira.": 250_000,
    "half a million naira": 500_000,
    "twenty thousand naira": 20_000,
    "seventy five thousand naira": 75_000,
    "seven hundred thousand": 700_000,
    "one hundred thousand naira only": 100_000,
    "Brother Segun, 10,000.": 10_000,
    "Chief Emeka Okonkwo, ₦250,000. Make we now clap for him.": 250_000,
}


@pytest.mark.parametrize("text,expected", CASES.items())
def test_spoken_amounts_are_read_once_or_sent_to_a_person(text, expected):
    assert extract_turn(text, [], []).amount.minor == expected


def test_a_counted_gift_is_one_in_kind_pledge():
    amount = extract_turn("Mama Blessing Okoro, one bag of cement.", [], []).amount
    assert amount.item == "one bag of cement" and amount.minor is None
