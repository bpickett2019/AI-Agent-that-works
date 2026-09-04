import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]


class RRCompilerTests(unittest.TestCase):
    def compile_with_registration_sheet(self, sheet_name):
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary)
            workbook = Workbook()
            workbook.remove(workbook.active)

            event = workbook.create_sheet("Event Details")
            event["A1"] = "Event Location"
            event["B1"] = "Test Venue, Test City, TS"

            links = workbook.create_sheet("Helpful & Social Media Links")
            links["B28"] = "No"

            registration = workbook.create_sheet(sheet_name)
            registration["B1"] = "No processing fee"
            registration["T4"] = "Advance"
            registration["U4"] = "Onsite 01/01/2030 - 01/02/2030"
            registration["B5"] = "REG-1"
            registration["C5"] = "Test registration type"
            registration["D5"] = "ACTIVATE"
            registration["E5"] = "ITEM-1"
            registration["F5"] = "Test admission item"
            registration["T5"] = 10
            registration["U5"] = 20

            workbook.create_sheet("Discount Code Template")
            workbook.create_sheet("Show Questions")
            workbook.save(job_dir / "input.xlsx")
            workbook.close()

            environment = os.environ.copy()
            environment["CVENT_JOB_DIR"] = str(job_dir)
            completed = subprocess.run(
                [sys.executable, str(ROOT / "rr_compiler.py")],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            result = json.loads(completed.stdout)
            expected = json.loads((job_dir / "expected-domains.json").read_text())
            return result, expected

    def test_accepts_supported_registration_sheet_names_and_records_exact_source(self):
        for sheet_name in ("NEW Reg Types & Pricing", "Reg Types & Pricing"):
            with self.subTest(sheet_name=sheet_name):
                result, expected = self.compile_with_registration_sheet(sheet_name)
                self.assertTrue(result["ok"])
                item = expected["domains"]["registration_types"]["items"][0]
                self.assertEqual(item["fields"]["registration_code"]["source"], f"{sheet_name}!B5")
                pricing = expected["domains"]["pricing"]
                self.assertEqual(
                    [tier["source"] for tier in pricing["tierHeaders"]],
                    [f"{sheet_name}!T4", f"{sheet_name}!U4"],
                )
                self.assertEqual(expected["rr"]["authority"], "uploaded_rr")

    def test_current_rr_layout_compiles_normal_configuration_without_scope_approvals(self):
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary)
            workbook = Workbook()
            event = workbook.active
            event.title = "Event Details"
            event.append(["Event Name", "RR name must not replace selected event"])
            event.append(["Event Location", "Test Center, Test City, TS"])
            workbook.create_sheet("Helpful & Social Media Links")
            registration = workbook.create_sheet("Reg Types & Pricing")
            headers = ["REG CODE", "REG TYPE NAME", "ACTIVATE / NOT NEEDED", "ADMISSION ITEM CODE", "ADMISSION ITEM",
                       "ADMISSION ITEM ADDITIONAL TEXT", "Can this reg type register another person?", "registration path",
                       "Admission Item Description", "Badge Description", "Registration Method", "Reported?", "Approval Needed?",
                       "Pre-Approval", "Advanced Pre-Registration", "qualified reg type", "Badge Color", "Early", "Onsite"]
            for column, value in enumerate(headers, 1): registration.cell(4, column, value)
            values = ["ATT", "Attendee", "ACTIVATE", "FULL", "Full Access", None, "Yes", "ATT", "All access", "Conference",
                      "Web & Staff", "Yes", "No", "No", "No", "Yes", "#123456", 10, 20]
            for column, value in enumerate(values, 1): registration.cell(5, column, value)
            discounts = workbook.create_sheet("Discount Code Template")
            for column, value in enumerate(["Name", "Discount Code", "Discount Type", "Method", "Amount/Percentage", "Effective From",
                                            "Effective To", "Capacity", "Stackable", "This discount can be used by",
                                            "Also counts guests towards capacity", "Active", "Internal Note", "Admission Items"], 1):
                discounts.cell(3, column, value)
            for column, value in enumerate(["Test discount", "TEST10", "Discount", "Amount off", 10, None, None, None, "No",
                                            "Invitees", "No", "Yes", None, "FULL"], 1):
                discounts.cell(4, column, value)
            questions = workbook.create_sheet("Show Questions")
            questions.cell(5, 1, "Show Questions")
            questions.cell(5, 2, "TESTQ")
            questions.cell(5, 3, "Individual")
            questions.cell(5, 4, "Test question?")
            questions.cell(5, 7, "Single Select")
            questions.cell(5, 8, "Yes")
            questions.cell(5, 10, "ATT")
            workbook.save(job_dir / "input.xlsx")
            workbook.close()
            environment = os.environ.copy()
            environment.update({"CVENT_JOB_DIR": str(job_dir), "CVENT_AUTHORIZED_EVENT_ID": "event-id"})
            subprocess.run([sys.executable, str(ROOT / "rr_compiler.py")], cwd=ROOT, env=environment, check=True, capture_output=True)
            expected = json.loads((job_dir / "expected-domains.json").read_text())
            self.assertEqual(expected["target"]["eventId"], "event-id")
            self.assertEqual(expected["counts"]["registrationTypeRecords"], 1)
            self.assertEqual(expected["counts"]["admissionRecords"], 1)
            self.assertEqual(expected["counts"]["discountRecords"], 1)
            self.assertEqual(expected["domains"]["questions"]["items"][0]["fields"]["internal_name"]["value"], "TESTQ")
            self.assertNotIn("scopeId", json.dumps(expected))


if __name__ == "__main__":
    unittest.main()
