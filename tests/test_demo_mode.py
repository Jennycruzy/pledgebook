from app.main import invented_guests


def test_demo_guests_are_small_and_do_not_use_the_old_repeated_persona():
    guests = invented_guests()

    assert len(guests) == 3
    assert all("Emeka Okonkwo" not in guest["name"] for guest in guests)
    assert all(guest["consent_to_contact"] is False for guest in guests)
