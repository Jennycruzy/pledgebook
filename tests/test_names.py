from app.names import match_name, normalize_name


GUESTS = [{"id": 1, "name": "Aisha Bello"}, {"id": 2, "name": "Emeka Okonkwo"}]


def test_titles_and_spacing_are_ignored_for_matching():
    assert normalize_name("Chief Aisha Bello") == "aishabello"
    result = match_name("Chief Aishabelu", GUESTS)
    assert result.kind in {"suggested", "matched"}
    assert result.guest_id == 1


def test_unknown_name_is_a_walk_in_question():
    result = match_name("Pastor New Person", GUESTS)
    assert result.guest_id is None
    assert result.kind == "walk_in"
    assert result.reason
