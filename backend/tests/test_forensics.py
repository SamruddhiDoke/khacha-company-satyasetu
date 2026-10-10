from datetime import date

from app.pipeline.forensics import analyse


def cats(findings, check):
    return [f["category"] for f in findings if f["check"] == check]


CIRCULAR = """GOVERNMENT OF MAHARASHTRA
Department of School Education
Circular No. SE/2025/1187
Dated: 14/03/2025 (Friday)

All schools shall remain closed on 31/02/2025. Students must register on or before 10/03/2025.
Registration fee Rs 200 to be paid via UPI to edu.help@ybl.
Contact: schooledu.maharashtra@gmail.com or call 9876543210.
"""


def test_circular_findings():
    f = analyse([CIRCULAR], today=date(2026, 1, 1))
    assert "confirmed_inconsistency" in cats(f, "impossible_date")       # 31/02
    assert "confirmed_inconsistency" in cats(f, "deadline_before_issue")  # 10/03 before 14/03
    assert "warning" in cats(f, "free_mail_contact")
    assert "warning" in cats(f, "payment_request")
    assert "could_not_check" in cats(f, "reference_number")
    assert "could_not_check" in cats(f, "metadata")
    # 14/03/2025 really was a Friday -> no weekday mismatch
    assert not cats(f, "weekday_mismatch")


def test_weekday_mismatch():
    f = analyse(["Notice dated Monday, 12 March 2025 regarding holidays."], today=date(2026, 1, 1))
    assert cats(f, "weekday_mismatch") == ["confirmed_inconsistency"]  # 12 March 2025 was a Wednesday


def test_clean_document_passes_and_is_not_called_fake():
    text = "Ministry of Education\nDated: 03/02/2025\nApplications close on or before 28/02/2025.\nContact: helpdesk@education.gov.in"
    f = analyse([text], metadata={"producer": "Microsoft Word"}, today=date(2026, 1, 1))
    assert not [x for x in f if x["category"] == "confirmed_inconsistency"]
    assert "passed" in cats(f, "deadline_order")
    assert "passed" in cats(f, "official_email")


def test_editor_metadata_is_only_a_warning():
    f = analyse(["Government of India notice dated 01/01/2025"], metadata={"producer": "Canva"}, today=date(2026, 1, 1))
    assert cats(f, "editing_software") == ["warning"]


def test_empty_text():
    f = analyse([""])
    assert f[0]["category"] == "could_not_check"
