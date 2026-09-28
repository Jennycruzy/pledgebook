from app.amounts import parse_amount
from app.extractor import TurnWindow, _amount_phrase


def test_one_bare_number_can_be_extracted_from_a_recheck_sentence():
    phrase = _amount_phrase("Brother Segun Ogunleye, 10,000.")
    assert parse_amount(phrase).minor == 10_000


def test_two_amounts_in_one_recheck_clip_are_flagged():
    phrase = _amount_phrase("500,000. Brother Segun Ogunleye, 10,000.")
    amount = parse_amount(phrase)
    assert amount.minor is None
    assert amount.reason


def test_word_and_numeric_amounts_in_one_clip_are_flagged():
    phrase = _amount_phrase("50K. Alhaji Ibrahim Musa, quarter million.")
    amount = parse_amount(phrase)
    assert amount.minor is None
    assert amount.reason


def test_turn_window_pairs_adjacent_name_and_amount_turns():
    guests = [{"id": 1, "name": "Emeka Okonkwo"}]
    from app.extractor import extract_turn

    name = extract_turn("Chief Emeka Okonkwo", [{"start": 1000, "end": 2000}], guests)
    amount = extract_turn("250,000 naira", [{"start": 2500, "end": 3500}], guests)
    window = TurnWindow()
    paired_name, paired_amount, reason = window.add(name)
    assert paired_name is None and paired_amount is None and reason is None
    paired_name, paired_amount, reason = window.add(amount)
    assert paired_name.name == "Emeka Okonkwo"
    assert paired_amount.amount.minor == 250_000
    assert reason is None


def test_turn_window_does_not_reuse_an_old_name_after_another_turn():
    guests = [{"id": 1, "name": "Emeka Okonkwo"}, {"id": 2, "name": "Aisha Bello"}]
    from app.extractor import extract_turn

    window = TurnWindow()
    window.add(extract_turn("Chief Emeka Okonkwo", [{"start": 1000, "end": 2000}], guests))
    window.add(extract_turn("Mrs Aisha Bello", [{"start": 3000, "end": 4000}], guests))
    paired_name, paired_amount, reason = window.add(extract_turn("250,000 naira", [{"start": 4500, "end": 5500}], guests))
    assert paired_name is not None
    assert paired_name.name == "Aisha Bello"
