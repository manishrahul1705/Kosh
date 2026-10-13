"""Tiny, dependency-free PDF writer for Stage 3A test fixtures.

Supports: multiple pages, Helvetica / Helvetica-Bold text (WinAnsi), lines,
ruled tables, a grey image XObject (to simulate scanned pages) and the
Standard security handler (RC4 40-bit, revision 2) with a user password.
Coordinates passed to the helpers are TOP-based (like pdfplumber reports them).
"""

from __future__ import annotations

import hashlib
import os
import zlib
from dataclasses import dataclass, field

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for b in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _pad(pw: str) -> bytes:
    return (pw.encode("latin-1") + _PAD)[:32]


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


@dataclass
class Page:
    width: float = 595.0
    height: float = 842.0
    ops: list[str] = field(default_factory=list)
    links: list[tuple] = field(default_factory=list)

    def text(self, x: float, top: float, s: str, size: float = 10, bold: bool = False) -> "Page":
        font = "F2" if bold else "F1"
        y = self.height - top - size
        self.ops.append(f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_esc(s)}) Tj ET")
        return self

    def link(self, url, x=40, top=100, width=400, height=14):
        self.links.append((url,x,top,width,height))
        return self

    def line(self, x1: float, top1: float, x2: float, top2: float) -> "Page":
        self.ops.append(f"0.8 w {x1:.2f} {self.height - top1:.2f} m {x2:.2f} {self.height - top2:.2f} l S")
        return self

    def image(self, x: float, top: float, w: float, h: float) -> "Page":
        self.ops.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {self.height - top - h:.2f} cm /Im1 Do Q")
        return self

    def table(self, x: float, top: float, col_widths: list[float], rows: list[list[str]],
              row_height: float = 20, size: float = 9, bold_header: bool = False) -> float:
        """Draw a fully ruled table; returns the bottom (top-based) coordinate."""
        total_w = sum(col_widths)
        bottom = top + row_height * len(rows)
        for r in range(len(rows) + 1):
            y = top + r * row_height
            self.line(x, y, x + total_w, y)
        cx = x
        for w in [0] + col_widths:
            cx += w
            self.line(cx, top, cx, bottom)
        for r, row in enumerate(rows):
            cx = x
            for c, cell in enumerate(row):
                if cell:
                    self.text(cx + 3, top + r * row_height + (row_height - size) / 2, cell, size=size,
                              bold=bold_header and r == 0)
                cx += col_widths[c]
        return bottom


class PdfBuilder:
    def __init__(self) -> None:
        self.pages: list[Page] = []

    def page(self, width: float = 595.0, height: float = 842.0) -> Page:
        p = Page(width, height)
        self.pages.append(p)
        return p

    def build(self, user_password: str | None = None, owner_password: str = "owner") -> bytes:
        file_id = hashlib.md5(os.urandom(16)).digest()
        objects: dict[int, bytes] = {}
        n_pages = len(self.pages)
        first_page_obj = 6
        kids = " ".join(f"{first_page_obj + 2 * i} 0 R" for i in range(n_pages))
        objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
        objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        img = zlib.compress(bytes((i * 7) % 256 for i in range(16 * 16)))
        objects[5] = (f"<< /Type /XObject /Subtype /Image /Width 16 /Height 16 /ColorSpace /DeviceGray "
                      f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(img)} >>\nstream\n").encode() + img + b"\nendstream"
        for i, p in enumerate(self.pages):
            pobj, cobj = first_page_obj + 2 * i, first_page_obj + 2 * i + 1
            objects[pobj] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {p.width} {p.height}] "
                             f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << /Im1 5 0 R >> >> "
                             f"/Contents {cobj} 0 R >>").encode()
            if p.links:
                annots=' '.join(f"<< /Type /Annot /Subtype /Link /Rect [{x} {p.height-top-height} {x+w} {p.height-top}] /A << /S /URI /URI ({_esc(url)}) >> >>" for url,x,top,w,height in p.links)
                objects[pobj]=objects[pobj][:-2]+f" /Annots [{annots}] >>".encode()
            content = "\n".join(p.ops).encode("latin-1")
            objects[cobj] = f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"

        encrypt_ref = ""
        if user_password is not None:
            o = _rc4(hashlib.md5(_pad(owner_password)).digest()[:5], _pad(user_password))
            perms = (-4).to_bytes(4, "little", signed=True)
            key = hashlib.md5(_pad(user_password) + o + perms + file_id).digest()[:5]
            u = _rc4(key, _PAD)
            enc_obj = max(objects) + 1
            objects[enc_obj] = (f"<< /Filter /Standard /V 1 /R 2 /O <{o.hex()}> /U <{u.hex()}> /P -4 >>").encode()
            encrypt_ref = f" /Encrypt {enc_obj} 0 R"

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = {}
        for num in sorted(objects):
            offsets[num] = len(out)
            out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
        xref = len(out)
        size = max(objects) + 1
        out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
        for num in range(1, size):
            out += f"{offsets[num]:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {size} /Root 1 0 R /ID [<{file_id.hex()}> <{file_id.hex()}>]{encrypt_ref} >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)


# ---------------------------------------------------------------------------
# Ready-made fixtures
# ---------------------------------------------------------------------------
def gem_like_pdf() -> bytes:
    """3 pages that mimic a GeM bid: title, headings, key/value tables, ATC text."""
    b = PdfBuilder()
    p1 = b.page()
    p1.text(40, 30, "Bid Number: GEM/2026/B/8124821", size=9, bold=True)
    p1.text(40, 45, "Dated: 06-10-2026", size=9)
    p1.text(200, 70, "Bid Document", size=13.5, bold=True)
    p1.text(40, 100, "Bid Details", size=10.5, bold=True)
    p1.table(40, 120, [250, 250], [
        ["Bid End Date/Time", "16-10-2026 21:00:00"],
        ["Bid Opening Date/Time", "17-10-2026 21:00:00"],
        ["Ministry/State Name", "Ministry Of Defence"],
    ])
    p1.text(40, 200, "EMD Detail", size=10.5, bold=True)
    p1.table(40, 220, [250, 250], [
        ["EMD Amount", "Rs. 25,000"],
        ["ePBG Percentage(%)", "5.00"],
    ])
    p1.text(40, 280, "The bidder must submit the EMD before the bid end date.", size=9)
    p2 = b.page()
    p2.text(40, 40, "MSE Purchase Preference", size=10.5, bold=True)
    p2.table(40, 60, [250, 250], [["MSE Purchase Preference", "Yes"]])
    p2.table(40, 100, [150, 150, 150], [["S.No.", "Consignee", "Quantity"], ["1", "Jalpaiguri", "2"]],
             bold_header=True)
    p2.text(40, 170, "Buyer Added Bid Specific Terms and Conditions", size=10.5, bold=True)
    p2.text(40, 190, "1. Generic", size=9, bold=True)
    p2.text(40, 205, "OPTION CLAUSE: The Purchaser reserves the right to increase or decrease the quantity", size=9)
    p2.text(40, 218, "up to 25 percent of bid quantity at the time of placement of contract.", size=9)
    p3 = b.page()
    p3.text(40, 40, "SCOPE OF WORK", size=9)
    p3.text(40, 60, "The seller shall supply, install and commission the equipment within 30 days.", size=9)
    p3.text(40, 75, "Turnover requirement: Rs. 1,00,000 (one lakh) for the last 3 years.", size=9)
    return b.build()


def text_pdf(pages: list[list[str]]) -> bytes:
    b = PdfBuilder()
    for lines in pages:
        p = b.page()
        for i, line in enumerate(lines):
            p.text(40, 40 + 14 * i, line, size=10)
    return b.build()


def scanned_pdf(n_pages: int = 2) -> bytes:
    b = PdfBuilder()
    for _ in range(n_pages):
        b.page().image(30, 30, 535, 780)
    return b.build()


def blank_pdf(n_pages: int = 1) -> bytes:
    b = PdfBuilder()
    for _ in range(n_pages):
        b.page()
    return b.build()


def encrypted_pdf() -> bytes:
    b = PdfBuilder()
    b.page().text(40, 40, "secret tender text", size=10)
    return b.build(user_password="userpw")


CORRUPT_PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\nthis is not a real pdf \x00\x01\x02"
