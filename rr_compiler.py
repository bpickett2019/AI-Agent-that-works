#!/usr/bin/env python3
"""Build confirmed, applicable Forge Intake expectations directly from the current RR."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from scope_manifest import load_manifest

ROOT = Path(__file__).resolve().parent
JOB_DIR = Path(os.environ.get("CVENT_JOB_DIR", ROOT / "data/current"))
RR = JOB_DIR / "input.xlsx"
OUT = JOB_DIR / "expected-domains.json"
TARGET = {
    "name": os.environ.get("CVENT_AUTHORIZED_EVENT_NAME", "(C+D) Medtrade Testing Clone 2"),
    "eventKey": os.environ.get("CVENT_AUTHORIZED_EVENT_KEY", "e712e34c-6117-4d13-bf4c-8ed54cf2b495"),
    "eventCode": os.environ.get("CVENT_AUTHORIZED_EVENT_CODE", ""),
    "mustRemainUnpublished": True,
}


def normalized(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def yes_no(value):
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true"}:
        return True
    if text in {"no", "n", "false"}:
        return False
    return value


def field(value, scope_id, source, **extra):
    item = {"value": normalized(value), "scopeId": scope_id, "source": source}
    item.update(extra)
    return item


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def value_map(ws):
    return {
        str(ws.cell(row, 1).value).strip(): ws.cell(row, 2).value
        for row in range(1, ws.max_row + 1)
        if ws.cell(row, 1).value not in (None, "")
    }


def worksheet_by_alias(workbook, purpose, *names):
    matches = [name for name in names if name in workbook.sheetnames]
    if not matches:
        raise ValueError(f"RR is missing the required {purpose} worksheet; expected one of: {', '.join(names)}")
    if len(matches) > 1:
        raise ValueError(f"RR has multiple {purpose} worksheets; keep exactly one of: {', '.join(names)}")
    name = matches[0]
    return name, workbook[name]


def choice_rows(ws, start, next_start):
    choices = []
    for row in range(start + 1, next_start):
        code, text = ws.cell(row, 5).value, ws.cell(row, 6).value
        if text not in (None, ""):
            choices.append({"code": normalized(code), "text": normalized(text)})
    return choices


manifest = load_manifest()
confirmed = set(manifest["confirmedIds"])
wb_formula = load_workbook(RR, data_only=False, read_only=False)
wb_values = load_workbook(RR, data_only=True, read_only=False)
try:
    event_ws = wb_values["Event Details"]
    event = value_map(event_ws)
    event_fields = {}
    if event.get("Event Location"):
        location = str(event["Event Location"]).strip()
        parts = [part.strip() for part in location.rsplit(",", 2)]
        if len(parts) == 3 and all(parts):
            event_fields["venue_name"] = field(parts[0], "scope-007", "Event Details!B10")
            event_fields["city"] = field(parts[1], "scope-008", "Event Details!B10")
            event_fields["state"] = field(parts[2], "scope-009", "Event Details!B10")
        else:
            event_fields["venue_name"] = field(location, "scope-007", "Event Details!B10", combinedLocation=True)
    if event.get("Time Zone for Event Location"):
        event_fields["time_zone"] = field(event["Time Zone for Event Location"], "scope-010", "Event Details!B11")
    if event.get("Show Hours"):
        event_fields["show_hours"] = field(event["Show Hours"], "scope-014", "Event Details!B19")
    if event.get("Total Estimated Registration") is not None:
        event_fields["registration_goal"] = field(event["Total Estimated Registration"], "scope-016", "Event Details!B22")

    theme_fields = {}
    if event.get("Event Theme"):
        theme_fields["event_theme"] = field(event["Event Theme"], "scope-017", "Event Details!B14")
    if event.get("Branding Colors (Enter Hex Codes)"):
        colors = re.findall(r"#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])", str(event["Branding Colors (Enter Hex Codes)"]))
        if colors:
            theme_fields["brand_primary_colors"] = field(colors, "scope-019", "Event Details!B15")

    links_ws = wb_values["Helpful & Social Media Links"]
    link_scope = {
        "Show Hours": "scope-024",
        "Show Policy": "scope-025",
        "Emerald Privacy Policy": "scope-026",
        "Browse Sessions": "scope-027",
        "Review Pricing": "scope-028",
        "Registration Status": "scope-029",
        "FAQ": "scope-030",
        "Contact Us Button": "scope-031",
        "Exhibitor Resource Center \n(Exhibitor flow only)": "scope-032",
    }
    footer_links = []
    for row, audience in list((r, "attendee_media") for r in range(3, 11)) + list((r, "exhibitor") for r in range(15, 24)):
        label = links_ws.cell(row, 1).value
        if label not in link_scope:
            continue
        sid = link_scope[label]
        values = {}
        visible = links_ws.cell(row, 2).value
        target = links_ws.cell(row, 3).value
        if visible not in (None, ""):
            values["visible"] = field(yes_no(visible), sid, f"Helpful & Social Media Links!B{row}")
        if target not in (None, ""):
            values["target"] = field(target, sid, f"Helpful & Social Media Links!C{row}")
        footer_links.append({"audience": audience, "label": label, "fields": values})

    social = []
    for row in range(32, 37):
        network, url = links_ws.cell(row, 1).value, links_ws.cell(row, 3).value
        if network and url:
            social.append({"network": network, "fields": {"visible": field(True, "scope-034", f"Helpful & Social Media Links!C{row}"), "url": field(url, "scope-034", f"Helpful & Social Media Links!C{row}")}})
    header_footer_body = {
        "footerLinks": footer_links,
        "countdown": {"fields": {
            "enabled": field(yes_no(links_ws["B28"].value), "scope-033", "Helpful & Social Media Links!B28"),
            "text": field(links_ws["B29"].value, "scope-033", "Helpful & Social Media Links!B29"),
        }},
        "social": social,
        "alreadyRegistered": {"fields": {"visible": field(yes_no(event.get("Already Registered Link on Landing Page")), "scope-035", "Event Details!B35")}},
    }

    # The current RR has no post-registration redirect field.
    registration_paths = {"paths": []}

    reg_sheet, reg_ws = worksheet_by_alias(
        wb_values, "registration types and pricing", "NEW Reg Types & Pricing", "Reg Types & Pricing",
    )
    reg_types, admissions, prices = [], [], []
    for row in range(5, 28):
        state = str(reg_ws.cell(row, 4).value or "").strip().upper()
        if state not in {"ACTIVATE", "REQUIRED"}:
            continue
        reg_code = reg_ws.cell(row, 2).value
        reg_name = reg_ws.cell(row, 3).value
        admission_code = reg_ws.cell(row, 5).value
        admission_name = reg_ws.cell(row, 6).value
        description = reg_ws.cell(row, 10).value
        if reg_code:
            reg_types.append({
                "rrNameReference": reg_name,
                "sourceRow": row,
                "fields": {"code": field(str(reg_code).strip(), "scope-037", f"{reg_sheet}!B{row}")},
            })
        if admission_name:
            ai_fields = {}
            if description:
                ai_fields["description"] = field(description, "scope-039", f"{reg_sheet}!J{row}")
            if reg_name:
                ai_fields["registration_type_availability"] = field(reg_name, "scope-040", f"{reg_sheet}!C{row}")
            admissions.append({"admissionNameReference": admission_name, "admissionCodeReference": str(admission_code).strip() if admission_code else None, "sourceRow": row, "fields": ai_fields})
        tier_values = [reg_ws.cell(row, col).value for col in (20, 21)]
        if any(value is not None for value in tier_values):
            price_fields = {}
            for key, value, sid, col in zip(("advance_price", "onsite_price"), tier_values, ("scope-044", "scope-045"), ("T", "U")):
                if value is not None:
                    price_fields[key] = field(value, sid, f"{reg_sheet}!{col}{row}")
            prices.append({"registrationTypeReference": reg_name, "admissionNameReference": admission_name, "sourceRow": row, "fields": price_fields})
    tier_headers = [reg_ws["T4"].value, reg_ws["U4"].value]
    pricing = {
        "fields": {
            "tier_date_ranges": field(tier_headers, "scope-041", f"{reg_sheet}!T4:U4"),
            "processing_fee_note": field(reg_ws["B1"].value, "scope-046", f"{reg_sheet}!B1"),
        },
        "items": prices,
    }
    onsite_header = str(reg_ws["U4"].value or "")
    onsite_dates = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", onsite_header)
    if len(onsite_dates) == 2:
        event_fields["registration_deadline"] = field(onsite_dates[1], "scope-015", f"{reg_sheet}!U4")

    discount_scope = {
        "name": "scope-047", "code": "scope-048", "method": "scope-049", "amount_or_percentage": "scope-050",
        "effective_from": "scope-051", "effective_to": "scope-051", "capacity": "scope-052", "stackable": "scope-053",
        "usable_by": "scope-054", "count_guests": "scope-055", "active": "scope-056", "admission_items": "scope-057",
    }
    discount_columns = {
        "name": 1, "code": 2, "method": 4, "amount_or_percentage": 5, "effective_from": 6, "effective_to": 7,
        "capacity": 8, "stackable": 9, "usable_by": 10, "count_guests": 11, "active": 12, "admission_items": 14,
    }
    discount_items = []
    sheet_name = "Discount Code Template"
    ws = wb_values[sheet_name]
    for row in range(7, ws.max_row + 1):
        if str(ws.cell(row, 12).value or "").strip().lower() != "yes":
            continue
        if ws.cell(row, 1).value in (None, "") or ws.cell(row, 2).value in (None, ""):
            continue
        fields = {}
        for key, col in discount_columns.items():
            value = ws.cell(row, col).value
            if key in {"stackable", "active"}:
                value = yes_no(value)
            if value is not None and not (key == "admission_items" and str(value).strip().startswith("[")):
                fields[key] = field(value, discount_scope[key], f"{sheet_name}!{ws.cell(row, col).coordinate}")
        discount_items.append({"matchReference": ws.cell(row, 2).value, "sourceSheet": sheet_name, "sourceRow": row, "fields": fields})

    qws = wb_values["Show Questions"]
    definition_rows = []
    for row in range(5, qws.max_row + 1):
        displayed_text = qws.cell(row, 4).value
        metadata = [qws.cell(row, col).value for col in (1, 2, 3, 7, 8, 9)]
        if displayed_text not in (None, "") and any(value not in (None, "") for value in metadata):
            definition_rows.append(row)
    questions = []
    for index, row in enumerate(definition_rows):
        next_row = definition_rows[index + 1] if index + 1 < len(definition_rows) else qws.max_row + 1
        raw_identifier = qws.cell(row, 2).value
        identifier = str(raw_identifier).strip() if raw_identifier not in (None, "") else None
        fields = {}
        mappings = (("page_displayed_on", 1, "scope-058"), ("company_or_individual", 3, "scope-059"),
                    ("displayed_text", 4, "scope-060"), ("appearance", 7, "scope-061"))
        for key, col, sid in mappings:
            value = qws.cell(row, col).value
            if value not in (None, ""):
                fields[key] = field(value, sid, f"Show Questions!{qws.cell(row, col).coordinate}")
        choices = choice_rows(qws, row, next_row)
        if choices:
            fields["ordered_answer_options"] = field(choices, "scope-062", f"Show Questions!E{row + 1}:F{next_row - 1}")
        continuation = [str(qws.cell(r, 4).value).strip() for r in range(row + 1, next_row) if qws.cell(r, 4).value not in (None, "")]
        if continuation and "displayed_text" in fields:
            fields["displayed_text"]["value"] = "\n\n".join([str(fields["displayed_text"]["value"]).strip(), *continuation])
            fields["displayed_text"]["source"] = f"Show Questions!D{row}:D{next_row - 1}"
        required = qws.cell(row, 8).value
        if required not in (None, ""):
            fields["required"] = field(yes_no(required), "scope-063", f"Show Questions!H{row}")
        visibility = qws.cell(row, 9).value
        if visibility not in (None, ""):
            text = str(visibility)
            conditional = bool(re.search(r"(?:\bif\b|=|only ask|when |\band/or\b)", text, re.I)) or " - " in text or " / " in text
            if not conditional:
                fields["registration_type_visibility"] = field(visibility, "scope-064", f"Show Questions!I{row}")
        questions.append({"rrIdentifier": identifier, "notACventIdentity": True, "sourceRow": row, "fields": fields})

    emp_row = next((row for row in definition_rows if str(qws.cell(row, 2).value or "").strip() == "EMPP"), None)
    terms = {"fields": {}}
    if emp_row:
        terms["fields"]["privacy_policy_acceptance"] = field(qws.cell(emp_row, 4).value, "scope-068", f"Show Questions!D{emp_row}")

    excluded = [
        {"request": "RR event identity (BDNY 2026 / FP code)", "reason": "Mock RR cannot select or rename the protected target."},
        {"request": "Event type and expo/conference dates", "scopeIds": ["scope-011", "scope-012", "scope-013"], "reason": "Exact mapped RR fields are absent; the generic Event Dates field was not repurposed."},
        {"request": "Hotel Info footer links", "scopeId": "scope-071", "scopeStatus": "unconfirmed"},
        {"request": "Registration path creation/privacy/status", "scopeIds": ["scope-075", "scope-076", "scope-077"], "scopeStatus": "unconfirmed"},
        {"request": "Registration type names/path/status/schedule/capacity/guest eligibility", "scopeIds": ["scope-078", "scope-081", "scope-082", "scope-083", "scope-084", "scope-085"], "scopeStatus": "unconfirmed"},
        {"request": "Admission item names/codes/status/schedule/capacity/fee flag", "scopeIds": ["scope-086", "scope-087", "scope-088", "scope-089", "scope-090", "scope-091"], "scopeStatus": "unconfirmed"},
        {"request": "Discount category/type, tracks, sessions and optional items", "scopeIds": ["scope-097", "scope-098"], "scopeStatus": "unconfirmed_or_absent"},
        {"request": "Question internal names, determines-registration-type, triggers and conditional/follow-up logic", "scopeIds": ["scope-103", "scope-104", "scope-105"], "scopeStatus": "unconfirmed"},
        {"request": "Registration pass description", "scopeId": "scope-038", "reason": "The exact mapped RR field is absent; Badge Description was not repurposed."},
        {"request": "Create missing registration questions", "scopeIds": ["scope-058", "scope-059", "scope-060", "scope-061", "scope-062", "scope-063", "scope-064"], "reason": "Creation requires the unconfirmed internal-name field scope-103; only safely matched existing questions may be updated."},
        {"request": "Question online visibility", "scopeId": "scope-065", "reason": "No Visible Online field is present in this RR."},
        {"request": "Show-policy URL and cancellation/refund text", "scopeIds": ["scope-066", "scope-067"], "reason": "The exact mapped RR fields are absent; footer URLs were not repurposed."},
        {"request": "Optional items/add-ons, advanced rules, vouchers, sessions, speakers, communications and other areas", "scopeStatus": "deferred_or_absent"},
    ]
    registry = {}
    for identifier in ("M-09", "M-10", "M-11", "AGES", "NAICS36D", "CSUB4", "SUB4", "DONATE"):
        locations = []
        for ws in wb_values.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None and re.search(rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])", str(cell.value), re.I):
                        locations.append(f"{ws.title}!{cell.coordinate}")
        registry[identifier] = {"exact": identifier, "sourceLocations": locations, "included": identifier in {q["rrIdentifier"] for q in questions}}
        if not locations:
            excluded.append({"request": identifier, "reason": "Exact identifier is absent from this RR; no Cvent work authorized."})

    result = {
        "schemaVersion": 3,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "rr": {"path": str(RR), "sha256": hashlib.sha256(RR.read_bytes()).hexdigest(), "mode": "mock_requirements_only"},
        "scope": {"authority": manifest["authority"], "sourceSha256": manifest["sourceSha256"], "confirmedCount": manifest["counts"]["confirmed"]},
        "target": TARGET,
        "domains": {
            "event_basics": {"fields": event_fields},
            "theme_branding": {"fields": theme_fields},
            "header_footer_body": header_footer_body,
            "registration_paths": registration_paths,
            "registration_types": {"items": reg_types},
            "admission_items": {"items": admissions},
            "pricing_fees": pricing,
            "discounts": {"items": discount_items},
            "registration_questions": {"items": questions, "collisionControls": ["RR identifiers are not Cvent identities.", "Never overwrite reusable/profile/account-global definitions."]},
            "terms_policies": terms,
            "final_qa": {"checks": ["protected identity unchanged", "unpublished", "confirmed fields reread", "no in-scope duplicates"]},
        },
        "identifierRegistry": registry,
        "excludedOrBlocked": excluded,
        "counts": {
            "confirmedApplicableFields": 0,
            "registrationTypeRecords": len(reg_types),
            "admissionRecords": len(admissions),
            "pricingRecords": len(prices),
            "discountRecords": len(discount_items),
            "questionRecords": len(questions),
            "footerLinkRecords": len(footer_links),
            "socialRecords": len(social),
        },
    }

    def count_fields(item):
        if isinstance(item, dict):
            if {"value", "scopeId"} <= set(item):
                return 1
            return sum(count_fields(value) for value in item.values())
        if isinstance(item, list):
            return sum(count_fields(value) for value in item)
        return 0

    def validate(item, path="domains"):
        if isinstance(item, dict):
            if "value" in item or "scopeId" in item:
                assert {"value", "scopeId", "source"} <= set(item), path
                assert item["scopeId"] in confirmed, (path, item["scopeId"])
            else:
                for key, value in item.items():
                    validate(value, f"{path}.{key}")
        elif isinstance(item, list):
            for index, value in enumerate(item):
                validate(value, f"{path}[{index}]")

    result["counts"]["confirmedApplicableFields"] = count_fields(result["domains"])
    validate(result["domains"])
    atomic_json(OUT, result)
    print(json.dumps({"ok": True, "output": str(OUT), "counts": result["counts"], "identifiers": registry}, indent=2))
finally:
    wb_formula.close()
    wb_values.close()
