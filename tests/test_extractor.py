from app.amounts import parse_amount
from app.extractor import TurnWindow, _amount_phrase, extract_turn


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


def test_anonymous_donor_is_explicit_and_has_no_guest_match():
    turn = extract_turn("A son of the soil, fifty thousand naira", [], [])
    assert turn.name == "Anonymous donor"
    assert turn.name_match.kind == "anonymous"
    assert turn.amount.minor == 50_000


def test_same_turn_multiple_amounts_are_returned_for_a_visible_flag():
    guests = [{"id": 1, "name": "Aisha Bello"}]
    turn = extract_turn("Mrs Aisha Bello, 50K, quarter million", [], guests)
    name_turn, amount_turn, reason = TurnWindow().add(turn)
    assert name_turn is not None and amount_turn is not None
    assert "More than one amount" in reason


def _words(text, start):
    return [{"text": w, "start": start + i * 300, "end": start + i * 300 + 250} for i, w in enumerate(text.split())]


def test_an_amount_that_closes_the_last_announcement_is_not_given_to_the_next_name():
    # Real Realtime segmentation from the owner's recording: the previous
    # donor's amount and the next donor's name arrived in one turn.
    guests = [{"id": 1, "name": "Segun Ogunleye"}, {"id": 2, "name": "Oluwaseun Adebayo"}]
    window = TurnWindow()
    window.add(extract_turn("Mrs. Oluwaseun Adebayo, ₦1 million.", _words("Mrs. Oluwaseun Adebayo, ₦1 million.", 0), guests))
    name, amount, _ = window.add(extract_turn("₦500,000. Brother Segun Ogunleye.", _words("₦500,000. Brother Segun Ogunleye.", 4000), guests))
    assert name is None and amount is None
    stray = window.take_unpaired()
    assert [(t.name, t.amount.minor) for t in stray] == [(None, 500_000)]
    name, amount, _ = window.add(extract_turn("₦10,000. Now, so we do.", _words("₦10,000. Now, so we do.", 8000), guests))
    assert name.name == "Segun Ogunleye" and amount.amount.minor == 10_000


def test_amount_then_from_name_stays_one_pledge():
    guests = [{"id": 1, "name": "Segun Ogunleye"}]
    turn = extract_turn("Five hundred thousand naira from Brother Segun Ogunleye!", _words("x", 0), guests)
    assert turn.split_at is None
    name, amount, _ = TurnWindow().add(turn)
    assert name.name == "Segun Ogunleye" and amount.amount.minor == 500_000


def test_corrected_amount_before_next_name_stays_with_pending_donor():
    """Regression from speaker A: a correction must not shift every later donor."""

    guests = [{"id": 1, "name": "Ibrahim Musa"}, {"id": 2, "name": "Tola Adeyemi"}]
    window = TurnWindow()
    window.add(extract_turn("Alhaji Ibrahim Musa.", _words("Alhaji Ibrahim Musa.", 0), guests))

    text = "₦50,000— sorry, ₦70,000. Dr. Tola Adeyemi."
    name, amount, reason = window.add(extract_turn(text, _words(text, 3000), guests))

    assert name.name == "Ibrahim Musa"
    assert amount.amount.minor is None
    assert "More than one amount" in reason
    assert window.pending_name.name == "Tola Adeyemi"

    name, amount, reason = window.add(extract_turn("₦1 million.", _words("₦1 million.", 7000), guests))
    assert name.name == "Tola Adeyemi"
    assert amount.amount.minor == 1_000_000
    assert reason is None


def test_correction_split_across_turns_is_flagged_without_shifting_donors():
    """Exact speaker-1 shape: "sorry" ended one turn and its amount began the next."""

    guests = [{"id": 1, "name": "Ibrahim Musa"}, {"id": 2, "name": "Tola Adeyemi"}]
    window = TurnWindow()
    first = "Alhaji Ibrahim Musa. ₦50,000. Sorry."
    assert window.add(extract_turn(first, _words(first, 0), guests)) == (None, None, None)

    second = "₦70,000. Dr. Tola Adeyemi."
    # Explicit corrections get a longer bound than ordinary name/amount
    # pairing; the real music recording crossed the six-second threshold.
    name, amount, reason = window.add(extract_turn(second, _words(second, 10_000), guests))
    assert name.name == "Ibrahim Musa"
    assert amount.amount.minor is None
    assert "correction" in reason.lower()
    assert window.pending_name.name == "Tola Adeyemi"

    name, amount, reason = window.add(extract_turn("₦1 million.", _words("₦1 million.", 13_000), guests))
    assert name.name == "Tola Adeyemi"
    assert amount.amount.minor == 1_000_000
    assert reason is None


def test_unfinished_correction_is_flushed_for_a_person():
    guests = [{"id": 1, "name": "Ibrahim Musa"}]
    window = TurnWindow()
    text = "Alhaji Ibrahim Musa, ₦50,000, sorry."
    window.add(extract_turn(text, _words(text, 0), guests))
    left = window.flush()
    assert len(left) == 1
    assert left[0].name == "Ibrahim Musa"
    assert left[0].amount.minor is None
    assert "correction" in left[0].amount.reason.lower()


def test_amount_before_next_name_closes_pending_announcement_without_a_cascade():
    """Regression from script C: Bukola's amount and the following Chief shared a turn."""

    guests = [{"id": 1, "name": "Bukola Ajayi"}, {"id": 2, "name": "Nwachukwu Ezenwa"}]
    window = TurnWindow()
    window.add(extract_turn("Mrs Bukola Ajayi.", _words("Mrs Bukola Ajayi.", 0), guests))

    text = "₦60,000. Chief Nwachukwu Ezenwa is adding another"
    name, amount, reason = window.add(extract_turn(text, _words(text, 3000), guests))
    assert name.name == "Bukola Ajayi"
    assert amount.amount.minor == 60_000
    assert reason is None
    assert window.pending_name.name == "Nwachukwu Ezenwa"

    name, amount, _ = window.add(extract_turn("₦50,000.", _words("₦50,000.", 7000), guests))
    assert name.name == "Nwachukwu Ezenwa"
    assert amount.amount.minor == 50_000


def test_a_name_that_never_gets_an_amount_is_handed_back():
    guests = [{"id": 1, "name": "Emeka Okonkwo"}]
    window = TurnWindow()
    window.add(extract_turn("Chief Emeka Okonkwo.", _words("Chief Emeka Okonkwo.", 0), guests))
    left = window.flush()
    assert [t.name for t in left] == ["Emeka Okonkwo"]
    assert "without a clear amount" in left[0].amount.reason
