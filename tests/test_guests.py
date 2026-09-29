from helpers import add_guest, add_pledge, pledge


def test_duplicate_guests_are_refused_by_name_phone_or_email(owner, event):
    add_guest(owner, event["id"], name="Ngozi Eze", phone="08031234567", email="ngozi@example.com")
    for body in ({"name": "ngozi  EZE"}, {"name": "Someone", "phone": "+234 803 123 4567"}, {"name": "Other", "email": "NGOZI@example.com"}):
        assert owner.post(f"/api/events/{event['id']}/guests", body).status_code == 409


def test_bad_contact_details_are_refused(owner, event):
    assert owner.post(f"/api/events/{event['id']}/guests", {"name": "A", "email": "not-an-email"}).status_code == 400
    assert owner.post(f"/api/events/{event['id']}/guests", {"name": "A", "phone": "12"}).status_code == 400


def test_edit_updates_pledges_and_withdrawing_consent_closes_pages(owner, event):
    guest = add_guest(owner, event["id"], name="Tunde Bello", email="tunde@example.com")
    pledge_id = add_pledge(event["id"], guest)
    link = owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/deliver", {"channel": "copy"}).json()
    token = link["url"].rsplit("/", 1)[-1]
    assert owner.get(f"/api/pay/{token}").status_code == 200
    body = {"title": "Engr", "name": "Tunde Bello-Ade", "email": "tunde@example.com", "consent_to_contact": False}
    assert owner.patch(f"/api/events/{event['id']}/guests/{guest['id']}", body).status_code == 200
    assert pledge(pledge_id)["matched_name"] == "Tunde Bello-Ade"
    assert owner.get(f"/api/pay/{token}").status_code == 410
    history = owner.get(f"/api/events/{event['id']}/guests/{guest['id']}/history").json()
    assert any(row["label"] == "Guest edited" for row in history["history"])


def test_removed_guest_leaves_the_list_but_pledges_keep_the_name(owner, event):
    guest = add_guest(owner, event["id"], name="Kemi Ade")
    pledge_id = add_pledge(event["id"], guest)
    assert owner.delete(f"/api/events/{event['id']}/guests/{guest['id']}").status_code == 200
    state = owner.get(f"/api/events/{event['id']}").json()
    assert state["guests"] == [] and state["removed_guests"] == 1
    assert "Kemi Ade" not in state["key_terms"]["terms"]
    assert pledge(pledge_id)["matched_name"] == "Kemi Ade"


def test_import_preview_marks_problems_then_imports_only_good_rows(owner, event):
    add_guest(owner, event["id"], name="Existing Person")
    csv_text = ("title,name,phone,email,consent_to_contact,group\n"
                "Mr,New Person,08030000001,new@example.com,yes,Choir\n"
                ",Existing Person,,,,\n"
                ",Bad Email,,bad,,\n"
                ",New Person,,,,\n")
    preview = owner.post(f"/api/events/{event['id']}/guests/import/preview",
                         files={"file": ("guests.csv", csv_text.encode(), "text/csv")}).json()
    assert [row["status"] for row in preview["rows"]] == ["ok", "duplicate", "invalid", "duplicate"]
    result = owner.post(f"/api/events/{event['id']}/guests/import", {"rows": preview["rows"]}).json()
    assert result["imported"] == 1 and result["skipped"] == 3
    names = [g["name"] for g in result["state"]["guests"]]
    assert names == ["Existing Person", "New Person"]
    assert result["state"]["guests"][1]["consent_to_contact"] == 1


def test_csv_without_name_column_is_explained(owner, event):
    response = owner.post(f"/api/events/{event['id']}/guests/import/preview", files={"file": ("g.csv", b"full name\nA\n", "text/csv")})
    assert response.status_code == 400
    assert "name" in response.json()["detail"]
