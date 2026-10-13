"""Builds Stage 3A rows (extraction/pages/tables/sections) the way Stage 3A stores them,
with bilingual GeM-style labels ("<Hindi with U+FFFD gaps>/<English>"). No PDFs needed:
Stage 3B consumes Stage 3A rows only."""

from __future__ import annotations

import copy
import json

from sqlalchemy import select

from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    Tender,
    TenderDocument,
)
from app.utils.dates import utcnow

H = "�"  # unmapped Hindi glyph as stored by Stage 3A


def bi(english: str) -> str:
    """Bilingual label like the real ones: '<Hindi>/<English>' (with a wrapped line)."""
    return f"{H}बड {H}ववरण/{english}"


# section key -> (page, top, heading, normalized, method)
BASE_SECTIONS = [
    (1, 130.0, f"{H}बड द{H}तावेज़ / Bid Document", "bid document", "known_heading"),
    (1, 170.0, f"{H}बड {H}ववरण/ Bid Details", "bid details", "known_heading"),
    (2, 650.0, f"ईएमड{H} {H}ववरण /EMD Detail", "emd detail", "known_heading"),
    (2, 730.0, f"ईपीबीजी {H}ववरण /ePBG Detail", "epbg detail", "known_heading"),
    (3, 110.0, "एमआईआई खर{H}द वर{H}यता /MII Purchase Preference", "mii purchase preference", "known_heading"),
    (3, 176.0, "एमएसई खर{H}द वर{H}यता /MSE Purchase Preference", "mse purchase preference", "known_heading"),
    (3, 670.0, "Paintball Gun Set ( 2 per seat )", "paintball gun set 2 per seat", "font_size"),
    (3, 700.0, f"तकनीक{H} {H}विश{H}{H}याँ /Technical Specifications", "technical specifications", "known_heading"),
    (4, 90.0, f"परे{H}षती/Consignees/Reporting Officer and Quantity", "consignees reporting officer and quantity",
     "known_heading"),
    (4, 230.0, "/Buyer Added Bid Specific Terms and Conditions", "buyer added bid specific terms and conditions",
     "known_heading"),
    (4, 260.0, "1. Generic", "generic", "numbered"),
    (4, 460.0, "3. Warranty", "warranty", "numbered"),
    (4, 680.0, "5. Certificates", "certificates", "numbered"),
    (4, 750.0, "/Disclaimer", "disclaimer", "known_heading"),
]

BASE_TABLES = [
    # (page, table_index, top, rows)
    (1, 1, 180.0, [
        [bi("Bid Details"), None],
        [bi("Bid End Date/Time"), "16-10-2026 21:00:00"],
        [bi("Bid Opening\nDate/Time"), "17-10-2026 21:00:00"],
        [bi("Bid Offer\nValidity (From End Date)"), "155 (Days)"],
        [f"मं{H}ालय/रा{H}य का नाम/Ministry/State Name", "Ministry Of Defence"],
        [f"{H}वभाग का नाम/Department Name", "Department Of Military Affairs"],
        ["संगठन का नाम/Organisation Name", "Indian Army"],
        [f"कायाल{H} य का नाम/Office Name", "***********"],
        [f"कुल मा{H}ा/Total Quantity", "2"],
        [f"व{H}तु {H}णे ी /Item Category", "Paintball Gun Set"],
        [f"{H} छूट {H}दान /\nक{H} गई है/MSE Relaxation for Years of\nExperience and Turnover", "No"],
        [f"{H}दान /\nक{H} गई है /Startup Relaxation for Years of\nExperience and Turnover", "No"],
    ]),
    (2, 1, -560.0, [
        [bi("Bid Details"), None],
        [f"{H}व{H}ेता से मांगे गए द{H}तावेज़/Document required\nfrom seller",
         "Experience Criteria,Past Performance,Bidder\nTurnover,Certificate (Requested in ATC),OEM Authorization\n"
         "Certificate,OEM Annual Turnover\n*In case any bidder is seeking exemption from Experience /\n"
         "Turnover Criteria, the supporting documents to prove his\neligibility for exemption must be uploaded"],
        [f"{H}वगत {H}दशन{H} /Past Performance", "10 %"],
        [bi("Bid to RA enabled"), "No"],
        [f"{H}बड का {H}कार/Type of Bid", "Two Packet Bid"],
        [f"तकनीक{H} /Time allowed for Technical\nClarifications during technical evaluation", "2 Days"],
        [f"िनर{H}{H}ण आव{H}यक/Inspection Required (By\nEmpanelled Inspection Authority / Agencies\n"
         "pre-registered with GeM)", "No"],
        [f"मू{H}यांकन प{H}ित/Evaluation Method", "Total value wise evaluation"],
        [f"म{H}य{H}थता खंड/Arbitration Clause", "No"],
        ["सुलह खंड/Mediation Clause", "No"],
    ]),
    (2, 2, 677.0, [[f"आव{H}यकता/Required", "No"]]),        # under EMD Detail
    (2, 3, 754.0, [[f"आव{H}यकता/Required", "No"]]),        # under ePBG Detail
    (3, 1, 130.0, [["एमआईआई खर{H}द वर{H}यता/MII Purchase Preference", "No"]]),
    (3, 2, 200.0, [
        ["एमएसई खर{H}द वर{H}यता/MSE Purchase Preference", "Yes"],
        [f"य{H}द L1+X% /\nPurchase Preference to MSE OEMs/ Service\nProvider available upto price within L1+X%", "15"],
        [f"{H}ितशत / Percentage of Bid quantity/amount for\nMSE OEMs/ Service Provider Purchase preference", "25"],
    ]),
    (4, 1, 110.0, [
        [f"{H}.सं./S.N\no.", f"परे{H}षती/{H}रपो{H}ट{H}ग\nअिधकार{H} /Consignee\nReporting/Officer", "पता/Address",
         f"मा{H}ा /Quantity", f"{H}डलीवर{H} के {H}दन/Delivery\nDays"],
        ["1", "***********", "***********Jalpaiguri", "2", "15"],
    ]),
]

BASE_PAGES = {
    1: f"{H}बड सं{H}या/Bid Number: GEM/2026/B/8124821\n{H}दनांक /Dated: 06-10-2026\n"
       f"{H}बड बंद होने क{H} तार{H}ख/समय /Bid End Date/Time 16-10-2026 21:00:00\n"
       f"कुल मा{H}ा/Total Quantity 2\nव{H}तु {H}णे ी /Item Category Paintball Gun Set",
    2: f"{H}वगत {H}दशन{H} /Past Performance 10 %\n{H}बड का {H}कार/Type of Bid Two Packet Bid",
    3: "MII Purchase Preference\nMII Purchase Preference No\n"
       "2. Past Performance: The Bidder or its OEM should have supplied same or similar Category Products "
       "for 10% of bid quantity, in at least one of the last three Financial years.\n"
       "Paintball Gun Set ( 2 per seat )\nTechnical Specifications",
    4: "Consignees/Reporting Officer and Quantity\n1 *********** ***********Jalpaiguri 2 15\n"
       "/Buyer Added Bid Specific Terms and Conditions\n1. Generic\nOPTION CLAUSE: The Purchaser reserves the right.\n"
       "3. Warranty\nWarranty period of the supplied products shall be 5 years from the date of final acceptance.\n"
       "5. Certificates\nISO 9001: The bidder or the OEM of the offered products must have ISO 9001 certification.\n"
       "/Disclaimer\nBuyer added ATC Clauses which are in contravention of clauses defined in bid detail section "
       "including ISO 14001 and OEM Authorization requirements shall be invalid.",
}


def _offset(pages: dict[int, str], page: int, normalized: str, heading: str) -> int | None:
    text = pages.get(page, "")
    needle = heading.split("/")[-1].strip() if "/" in heading else heading
    pos = text.find(needle)
    return pos if pos >= 0 else None


def make_stage3a(db, *, bid: str = "GEM/2026/B/8124821", tables=None, sections=None, pages=None,
                 status: str = "SUCCESS", quality: str = "GOOD", version_number: int = 1,
                 document: TenderDocument | None = None, is_current: bool = True) -> DocumentExtraction:
    tables = copy.deepcopy(BASE_TABLES if tables is None else tables)
    sections = BASE_SECTIONS if sections is None else sections
    pages = BASE_PAGES if pages is None else pages
    # the printed bid number must match the tender the rows belong to
    pages = {k: v.replace("GEM/2026/B/8124821", bid) for k, v in pages.items()}
    if document is None:
        tender = db.scalar(select(Tender).where(Tender.bid_number == bid))
        if tender is None:
            tender = Tender(bid_number=bid, status="ONGOING", source_fingerprint="fp", first_seen_at=utcnow(),
                            last_seen_at=utcnow(), bid_type="BID")
            db.add(tender)
            db.flush()
        document = TenderDocument(tender_id=tender.id, document_key="main_bid", document_type="MAIN_BID",
                                  discovered_at=utcnow(), last_seen_at=utcnow())
        db.add(document)
        db.flush()
    v = DocumentVersion(document_id=document.id, version_number=version_number,
                        sha256=f"{version_number:064d}", storage_path=f"x/v{version_number}.pdf",
                        validation_status="VALID")
    db.add(v)
    db.flush()
    e = DocumentExtraction(document_version_id=v.id, document_id=document.id, tender_id=document.tender_id,
                           extractor_name="pdfplumber", extractor_version="stage3a-v1", status=status,
                           quality_status=quality, text_class="TEXT_NATIVE", is_current=is_current,
                           page_count=len(pages), tables_found=len(tables), sections_found=len(sections))
    db.add(e)
    db.flush()
    for n, text in pages.items():
        db.add(DocumentPage(extraction_id=e.id, document_version_id=v.id, page_number=n, raw_text=text,
                            normalized_text=text, char_count=len(text), word_count=len(text.split()),
                            has_text=True))
    for page, idx, top, rows in tables:
        db.add(DocumentTable(extraction_id=e.id, document_version_id=v.id, page_number=page, table_index=idx,
                             row_count=len(rows), column_count=max(len(r) for r in rows),
                             table_json=json.dumps(rows, ensure_ascii=False), bbox_json=json.dumps([40, top, 550, top + 20]),
                             extraction_method="pdfplumber:lines"))
    for seq, (page, top, heading, normalized, method) in enumerate(sections, start=1):
        db.add(DocumentSection(extraction_id=e.id, document_version_id=v.id, page_number=page, sequence=seq,
                               heading=heading, normalized_heading=normalized, heading_level=2,
                               detection_method=method, char_offset=_offset(pages, page, normalized, heading),
                               top=top))
    db.commit()
    return e


def replace_row(tables, english_label: str, new_value: str):
    """Copy of tables with the value of the row whose label ends with ``english_label`` replaced."""
    out = copy.deepcopy(tables)
    for _, _, _, rows in out:
        for row in rows:
            if row[0] and " ".join(row[0].split()).endswith(english_label):
                row[-1] = new_value
    return out


def drop_rows(tables, *english_labels: str):
    out = copy.deepcopy(tables)
    for t in out:
        t[3][:] = [r for r in t[3] if not (r[0] and any(" ".join(r[0].split()).endswith(lbl) for lbl in english_labels))]
    return [t for t in out if t[3]]
