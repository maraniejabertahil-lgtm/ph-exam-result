import unittest

from handoff import (EVENT, HandoffError, build_successful_list_event, handoff_key, select_list_link)

ANNOUNCEMENT = ("https://www.prc.gov.ph/article/november-2026-aeronautical-engineers-"
                "computer-based-licensure-examination-results-released")
DRIVE = "https://drive.google.com/file/d/1l0ZIpp8YVqjb14tscA_WN8OIlCbgMmuv/view?usp=sharing"
DRIVE_OTHER = "https://drive.google.com/file/d/ZZZZZZZZZZZZZZZZZZZZ/view"


class BuildEventTests(unittest.TestCase):
    def test_exact_five_fields_in_order(self):
        event = build_successful_list_event("Aeronautical Engineering",
                                            "November 2026 Computer-Based Licensure Examination",
                                            ANNOUNCEMENT, DRIVE)
        self.assertEqual(list(event), ["event", "profession", "examination",
                                       "prc_announcement_url", "successful_examinees_url"])
        self.assertEqual(event["event"], EVENT)

    def test_rejects_non_prc_announcement(self):
        with self.assertRaises(HandoffError):
            build_successful_list_event("X", "Y", "https://example.com/article/x", DRIVE)

    def test_rejects_http_and_credentials(self):
        with self.assertRaises(HandoffError):
            build_successful_list_event("X", "Y", ANNOUNCEMENT.replace("https", "http"), DRIVE)
        with self.assertRaises(HandoffError):
            build_successful_list_event("X", "Y", "https://user:pw@www.prc.gov.ph/article/x", DRIVE)

    def test_rejects_non_exact_drive_links(self):
        for bad in [
            "https://drive.google.com/uc?export=download&id=1l0ZIpp8YVqjb14tscA_WN8OIlCbgMmuv",
            "https://docs.google.com/spreadsheets/d/abc/edit",
            "http://drive.google.com/file/d/1l0ZIpp8YVqjb14tscA_WN8OIlCbgMmuv/view",
            "https://evil.example.com/files/list.pdf",
            "https://www.prc.gov.ph/files/list.html",
        ]:
            with self.subTest(bad=bad), self.assertRaises(HandoffError):
                build_successful_list_event("X", "Y", ANNOUNCEMENT, bad)

    def test_rejects_missing_fields(self):
        with self.assertRaises(HandoffError):
            build_successful_list_event("", "Y", ANNOUNCEMENT, DRIVE)


class SelectLinkTests(unittest.TestCase):
    def test_picks_list_and_ignores_top10_schools_and_full_text(self):
        status, href = select_list_link([
            ("Full Text of the Official Result", "https://drive.google.com/file/d/FULLTEXTAAAAAAAAAA/view"),
            ("Top 10 Examinees", "https://drive.google.com/file/d/TOPTENAAAAAAAAAAAA/view"),
            ("Performance of Schools", "https://drive.google.com/file/d/SCHOOLAAAAAAAAAAAA/view"),
            ("List of Successful Examinees", DRIVE),
        ])
        self.assertEqual((status, href), ("found", DRIVE))

    def test_keeps_school_names_in_list_labels(self):
        status, _ = select_list_link([
            ("List of Successful Examinees for Secondary School Teachers", DRIVE),
        ])
        self.assertEqual(status, "found")

    def test_accepts_label_variations(self):
        self.assertEqual(select_list_link([("Successful Examinees (PDF)", DRIVE)])[0], "found")

    def test_waits_instead_of_guessing(self):
        self.assertEqual(select_list_link([("Top 10 Examinees", DRIVE)]), ("awaiting", None))

    def test_holds_when_two_different_lists(self):
        status, hrefs = select_list_link([
            ("List of Successful Examinees", DRIVE),
            ("List of Successful Examinees", DRIVE_OTHER),
        ])
        self.assertEqual(status, "ambiguous")
        self.assertEqual(len(hrefs), 2)

    def test_duplicates_are_one_link(self):
        self.assertEqual(select_list_link([("List of Successful Examinees", DRIVE)] * 2),
                         ("found", DRIVE))

    def test_accepts_prc_hosted_pdf(self):
        pdf = "https://www.prc.gov.ph/sites/default/files/list-of-successful-examinees.pdf"
        self.assertEqual(select_list_link([("List of Successful Examinees", pdf)]), ("found", pdf))

    def test_never_selects_other_hosts(self):
        self.assertEqual(select_list_link([
            ("List of Successful Examinees", "https://evil.example.com/list.pdf")
        ]), ("awaiting", None))

    def test_accepts_prc_pdf_as_event_list_url(self):
        pdf = "https://www.prc.gov.ph/files/list.pdf"
        self.assertEqual(build_successful_list_event("X", "Y", ANNOUNCEMENT, pdf)["successful_examinees_url"], pdf)


class DedupeKeyTests(unittest.TestCase):
    def test_same_list_same_key_and_correction_new_key(self):
        a = build_successful_list_event("X", "Y", ANNOUNCEMENT, DRIVE)
        b = build_successful_list_event("X", "Y", ANNOUNCEMENT, DRIVE)
        c = build_successful_list_event("X", "Y", ANNOUNCEMENT, DRIVE_OTHER)
        self.assertEqual(handoff_key(a), handoff_key(b))
        self.assertNotEqual(handoff_key(a), handoff_key(c))


if __name__ == "__main__":
    unittest.main()


class WriteHandoffTests(unittest.TestCase):
    def setUp(self):
        import os, tempfile
        self.dir = tempfile.mkdtemp()
        self.env_before = os.environ.pop("HANDOFF_ENFORCE", None)

    def tearDown(self):
        import os
        if self.env_before is not None:
            os.environ["HANDOFF_ENFORCE"] = self.env_before
        else:
            os.environ.pop("HANDOFF_ENFORCE", None)

    def test_shadow_mode_records_blocked_without_raising(self):
        import json, os
        from handoff import write_handoff
        rec = write_handoff(self.dir, profession="X", examination="Y",
                            announcement_url=ANNOUNCEMENT, list_url="https://evil.example.com/a.pdf")
        self.assertEqual(rec["status"], "blocked")
        self.assertEqual(json.load(open(os.path.join(self.dir, "handoff.json")))["status"], "blocked")

    def test_enforce_mode_raises_on_blocked(self):
        import os
        from handoff import write_handoff
        os.environ["HANDOFF_ENFORCE"] = "1"
        with self.assertRaises(HandoffError):
            write_handoff(self.dir, profession="X", examination="Y",
                          announcement_url=ANNOUNCEMENT, list_url="https://evil.example.com/a.pdf")

    def test_ready_record_has_event_and_key(self):
        from handoff import write_handoff
        rec = write_handoff(self.dir, profession="X", examination="Y",
                            announcement_url=ANNOUNCEMENT, list_url=DRIVE)
        self.assertEqual(rec["status"], "ready")
        self.assertEqual(rec["event"]["successful_examinees_url"], DRIVE)
        self.assertEqual(len(rec["key"]), 64)
