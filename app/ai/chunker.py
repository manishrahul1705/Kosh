"""Deterministic evidence chunking (CHUNKER_VERSION = stage3c-chunks-v1).

Input: one Stage 3A extraction (``app.fields.evidence.Source``: pages, tables,
sections). Output: ordered, de-duplicated chunks with provenance, plus the
selection of chunks that fit the configured budget.

Rules
* Section boundaries come from Stage 3A (heading page + character offset).
  A section's text runs to the next heading (across pages).
* Kinds: BUYER_ATC (between "Buyer Added Bid Specific Terms" and "Disclaimer"),
  BOILERPLATE (Disclaimer and everything after it: GeM standard text),
  TECHNICAL (technical specifications), CLAUSE_TEXT (other prose),
  TABLE (bid-detail tables as "Label: value" lines), OTHER_TEXT (text before
  the first heading).
* Table/page-text duplication: page text interleaves table cells. Lines whose
  words are (almost) all contained in a table of the same section are dropped
  from the text chunk - the table chunk carries them once.
* Meaningful multilingual text is retained; page footers ("3 / 6") are dropped.
* Long text is split at clause boundaries (numbered lines), then sentences,
  never mid-word; each chunk <= AI_MAX_CHUNK_CHARACTERS.
* Identical / contained text is emitted once.
* Selection by priority (BUYER_ATC > CLAUSE_TEXT > TECHNICAL > TABLE > OTHER)
  under AI_MAX_CHUNKS_PER_ANALYSIS and the character budget; BOILERPLATE only
  with AI_INCLUDE_BOILERPLATE. Excluded chunks are kept (sent=False) with a reason.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace

from app.ai.constants import CHUNK_PRIORITY, ChunkKind
from app.extraction.headings import english_part
from app.fields.evidence import SectionRef, Source, TableRef
from app.fields.labels import english_label, label_key
from app.fields.registry import ATC_END_SECTIONS, ATC_START_SECTIONS, TECH_SECTIONS

_DEVANAGARI_OR_FFFD = re.compile("[ऀ-ॿ�]")
_FOOTER = re.compile(r"^\s*(\d+\s*/\s*\d+|-+\s*.*thank you\s*-+|-{3,}.*-{3,})\s*$", re.I)
_CLAUSE_START = re.compile(r"^\s*(\d{1,2}[.)]|[a-z][.)]|\([a-z0-9]{1,3}\)|[ivx]{1,4}[.)])\s+\S", re.I)
_WORD = re.compile(r"[a-z]{2,}|\d+(?:\.\d+)?", re.I)
_SENTENCE_END = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\d])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
# Listing / portal metadata rows that carry no requirement (label key prefixes).
SKIP_TABLE_LABELS = ("searched strings used in gemarpts", "searched result generated in gemarpts",
                     "relevant categories selected for notification", "contact details of grievance redressal")


@dataclass
class Chunk:
    key: str
    sequence: int
    kind: str
    source_type: str            # SECTION_TEXT | TABLE
    page_number: int
    page_end: int
    text: str
    section: SectionRef | None = None
    table_id: int | None = None
    sent: bool = False
    exclusion_reason: str | None = None
    source_location: dict | None = None
    review_required: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def section_heading(self) -> str | None:
        if self.source_location:
            loc=self.source_location
            if loc.get('location'):return loc['location'][:255]
            if loc.get('sheet'):return 'Sheet '+loc['sheet']
            if loc.get('table'):return 'Table '+str(loc['table'])
        if self.section is None:
            return None
        return (english_part(self.section.heading) or self.section.heading).strip(" /")[:255] or None

    @property
    def section_id(self) -> int | None:
        return self.section.id if self.section else None


@dataclass
class ChunkSet:
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def sent(self) -> list[Chunk]:
        return [c for c in self.chunks if c.sent]

    @property
    def truncated(self) -> bool:
        """A relevant (non-boilerplate) chunk had to be left out because of a limit."""
        return any(not c.sent and c.exclusion_reason in ("CHUNK_LIMIT", "CHAR_LIMIT") for c in self.chunks)

    @property
    def sent_characters(self) -> int:
        return sum(c.char_count for c in self.sent)

    def by_key(self) -> dict[str, Chunk]:
        return {c.key: c for c in self.chunks}


# ---------------------------------------------------------------------------
def clean_line(line: str) -> str:
    """Multilingual, whitespace-collapsed line ('' when nothing usable is left)."""
    s = " ".join(line.split())
    if not s or _FOOTER.match(s):
        return ""
    s = s.strip()
    if sum(ch.isalnum() for ch in s) < 2:
        return ""
    # contact details are not needed to interpret requirements: never sent to a provider
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", s))


def _clean_value(value: str) -> str:
    s = " ".join(value.split())
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", s.strip()))


def _raw_table_words(t: TableRef) -> set[str]:
    return _words(" ".join(" ".join(str(c).split()) for row in t.rows for c in row if c))


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def _table_lines(t: TableRef) -> list[str]:
    out = []
    for row in t.rows:
        cells = [" ".join(str(c).split()) if c else "" for c in row]
        nonempty = [c for c in cells if c]
        if not nonempty:
            continue
        if len(row) == 2 and cells[0] and cells[1]:
            label = clean_line(cells[0])
            if label_key(label).startswith(SKIP_TABLE_LABELS):
                continue
            value = _clean_value(cells[1])
            if label and value:
                out.append(f"{label}: {value}")
            continue
        parts = [clean_line(c) for c in nonempty]
        parts = [p for p in parts if p]
        if parts:
            out.append(" | ".join(parts))
    return out


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _split_long(lines: list[str], limit: int) -> list[list[str]]:
    """Group lines into pieces <= limit, breaking preferably before clause starts."""
    # 1. break over-long single lines at sentence boundaries (then hard, at spaces)
    flat: list[str] = []
    for ln in lines:
        if len(ln) <= limit:
            flat.append(ln)
            continue
        buf = ""
        for sent in _SENTENCE_END.split(ln):
            while len(sent) > limit:
                cut = sent.rfind(" ", 0, limit)
                cut = cut if cut > limit // 2 else limit
                if buf:
                    flat.append(buf)
                    buf = ""
                flat.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if buf and len(buf) + 1 + len(sent) > limit:
                flat.append(buf)
                buf = sent
            else:
                buf = f"{buf} {sent}".strip()
        if buf:
            flat.append(buf)
    # 2. pack lines; start a new piece at a clause boundary when the piece is already substantial
    pieces: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for ln in flat:
        add = len(ln) + (1 if cur else 0)
        clause_break = bool(_CLAUSE_START.match(ln)) and size > limit * 0.6
        if cur and (size + add > limit or clause_break):
            pieces.append(cur)
            cur, size = [], 0
            add = len(ln)
        cur.append(ln)
        size += add
    if cur:
        pieces.append(cur)
    return pieces


@dataclass
class _Segment:
    section: SectionRef | None
    kind: str
    page_start: int
    page_end: int
    lines: list[tuple[int, str]]     # (page, cleaned line)
    tables: list[TableRef]


_ATC_START_LINE = re.compile(r"^/?\s*buyer added bid specific (terms and conditions|atc)\b", re.I)
_ATC_END_LINE = re.compile(r"^/?\s*disclaimer\s*$|^the additional terms and conditions \(atc\) have been "
                           r"incorporated by the buyer", re.I)


def _locate(src: Source, s: SectionRef) -> SectionRef:
    """Stage 3A could not place some headings in the page text (char_offset None):
    try the English heading text case-insensitively; otherwise leave it unplaced."""
    if s.char_offset is not None:
        return s
    text = src.page_text(s.page_number)
    eng = (english_part(s.heading) or "").strip(" /")
    for needle in (eng, s.normalized):
        if needle and len(needle) >= 4:
            i = text.lower().find(needle.lower())
            if i >= 0:
                return replace(s, char_offset=i)
    return s


def _base_kind(section: SectionRef | None) -> str:
    if section is None:
        return ChunkKind.OTHER_TEXT.value
    if section.normalized in TECH_SECTIONS:
        return ChunkKind.TECHNICAL.value
    return ChunkKind.CLAUSE_TEXT.value


def _segments(src: Source) -> list[_Segment]:
    """Text segments between placed headings, then split by zone.

    Zones (PRE -> ATC -> POST) switch on headings (Stage 3A sections) AND on marker lines
    ("Buyer Added Bid Specific Terms...", "Disclaimer", GeM's standard ATC disclaimer
    sentence), so a heading Stage 3A could not place never lets GeM boilerplate slip into
    the ATC zone or buyer ATC fall out of it.
    """
    located = [_locate(src, s) for s in src.sections]
    bounds = [s for s in located if s.char_offset is not None]
    pages = sorted(src.pages, key=lambda p: p.page_number)

    def collect(start: tuple[int, int], end: tuple[int, int] | None) -> list[tuple[int, str]]:
        lines: list[tuple[int, str]] = []
        for p in pages:
            if p.page_number < start[0] or (end and p.page_number > end[0]):
                continue
            lo = start[1] if p.page_number == start[0] else 0
            hi = end[1] if end and p.page_number == end[0] else len(p.text)
            if hi <= lo:
                continue
            for raw in p.text[lo:hi].splitlines():
                c = clean_line(raw)
                if c:
                    lines.append((p.page_number, c))
        return lines

    raw: list[tuple[SectionRef | None, list[tuple[int, str]]]] = []
    first_page = pages[0].page_number if pages else 1
    pre_end = (bounds[0].page_number, bounds[0].char_offset) if bounds else None
    raw.append((None, collect((first_page, 0), pre_end)))
    for i, s in enumerate(bounds):
        end = (bounds[i + 1].page_number, bounds[i + 1].char_offset) if i + 1 < len(bounds) else None
        raw.append((s, collect((s.page_number, s.char_offset or 0), end)))
    # unplaced headings still switch zones at their page
    unplaced = [s for s in located if s.char_offset is None]

    zone = "PRE"
    segs: list[_Segment] = []
    for section, lines in raw:
        for u in [u for u in unplaced if section is not None and u.sequence < section.sequence]:
            unplaced.remove(u)
            zone = _zone_after_heading(zone, u)
        if section is not None:
            zone = _zone_after_heading(zone, section)
        start_kind = _zone_kind(zone, section)
        cur: _Segment | None = None
        for pg, ln in lines:
            if zone == "PRE" and _ATC_START_LINE.match(ln):
                zone = "ATC"
            elif zone != "POST" and _ATC_END_LINE.match(ln):
                zone = "POST"
            kind = _zone_kind(zone, section)
            if cur is None or cur.kind != kind:
                cur = _Segment(section, kind, pg, pg, [], [])
                segs.append(cur)
            cur.lines.append((pg, ln))
            cur.page_end = pg
        if cur is None and section is not None:   # heading without text: keep a slot for its tables
            segs.append(_Segment(section, start_kind, section.page_number, section.page_number, [], []))
    # attach tables to the (first) segment of the section they sit under (Stage 3A geometry)
    by_section: dict[int, _Segment] = {}
    for seg in segs:
        if seg.section is not None:
            by_section.setdefault(seg.section.id, seg)
    fallback: dict[int, _Segment] = {}
    for seg in segs:
        for pg in range(seg.page_start, seg.page_end + 1):
            fallback.setdefault(pg, seg)
    for t in src.tables:
        seg = by_section.get(t.section.id) if t.section is not None else None
        seg = seg or fallback.get(t.page_number) or (segs[0] if segs else None)
        if seg is not None:
            seg.tables.append(t)
    return segs


def _zone_after_heading(zone: str, s: SectionRef) -> str:
    if s.normalized in ATC_START_SECTIONS and zone == "PRE":
        return "ATC"
    if s.normalized in ATC_END_SECTIONS:
        return "POST"
    return zone


def _zone_kind(zone: str, section: SectionRef | None) -> str:
    if zone == "ATC":
        return ChunkKind.BUYER_ATC.value
    if zone == "POST":
        return ChunkKind.BOILERPLATE.value
    return _base_kind(section)


def build_chunks(src: Source, *, max_chunk_chars: int) -> list[Chunk]:
    """All candidate chunks in document order (before budget selection)."""
    out: list[Chunk] = []
    seen: list[str] = []

    def emit(kind, source_type, p0, p1, lines, section, table_id=None):
        for piece in _split_long(lines, max_chunk_chars):
            text = "\n".join(piece).strip()
            if not text:
                continue
            n = _norm(text)
            if any(n == s or n in s for s in seen):
                continue                                   # duplicate / contained text
            seen.append(n)
            out.append(Chunk("", 0, kind, source_type, p0, p1, text, section, table_id))

    page_table_words: dict[int, set[str]] = {}
    for t in src.tables:
        page_table_words.setdefault(t.page_number, set()).update(_raw_table_words(t))
    for seg in _segments(src):
        table_lines: list[str] = []
        for t in seg.tables:
            table_lines.extend(_table_lines(t))
        # Table geometry vs. heading positions is approximate, so coverage uses every
        # table on the pages this segment spans (page text interleaves those cells).
        tw: set[str] = set()
        for pg in range(seg.page_start, seg.page_end + 1):
            tw |= page_table_words.get(pg, set())
        text_lines = []
        for _, ln in seg.lines:
            w = _words(ln)
            if tw and w and len(w & tw) / len(w) >= 0.8:
                continue                                   # same information as a table cell
            text_lines.append(ln)
        heading = _norm(english_part(seg.section.heading) or "").strip(" /") if seg.section else ""
        heading_only = (len(text_lines) == 1 and bool(heading)
                        and _norm(text_lines[0]).strip(" /") in (heading, _norm(seg.section.heading).strip(" /")))
        if text_lines and not heading_only:
            emit(seg.kind, "SECTION_TEXT", seg.page_start, seg.page_end, text_lines, seg.section)
        if table_lines:
            kind = seg.kind if seg.kind in (ChunkKind.BUYER_ATC.value, ChunkKind.BOILERPLATE.value) \
                else ChunkKind.TABLE.value
            head = seg.tables[0]
            label = (english_label(seg.section.heading) or "Table") if seg.section else None
            emit(kind, "TABLE", head.page_number, seg.tables[-1].page_number,
                 ([f"[{label}]"] if label else []) + table_lines, seg.section, head.id)
    for i, c in enumerate(out, start=1):
        c.sequence, c.key = i, f"C{i}"
        c.review_required=any(p in src.review_pages for p in range(c.page_number,c.page_end+1))
        if c.table_id and c.page_number==0:
            table=next((t for t in src.tables if t.id==c.table_id),None)
            if table and table.location:
                c.source_location={k:v for k,v in table.location.items() if k!='cells'}
                cells=table.location.get('cells',[])
                if cells:c.source_location['cell_range']=[cells[0],cells[-1]]
        elif c.page_number==0:
            c.source_location={'kind':src.file_type,'location':c.section.heading if c.section else 'Logical document content'}
        elif any(p in src.ocr_metadata for p in range(c.page_number,c.page_end+1)):
            c.source_location={'kind':src.file_type,'method':'OCR','ocr_pages':{
                str(p):src.ocr_metadata[p] for p in range(c.page_number,c.page_end+1) if p in src.ocr_metadata}}
    return out


def select_chunks(chunks: list[Chunk], *, max_chunks: int, max_chars: int, include_boilerplate: bool) -> ChunkSet:
    """Mark chunks sent / excluded (reason) under the limits, by priority then document order."""
    used_chars = 0
    used = 0
    for c in sorted(chunks, key=lambda c: (CHUNK_PRIORITY.get(c.kind, 9), c.sequence)):
        if c.kind == ChunkKind.BOILERPLATE.value and not include_boilerplate:
            c.sent, c.exclusion_reason = False, "BOILERPLATE"
        elif used >= max_chunks:
            c.sent, c.exclusion_reason = False, "CHUNK_LIMIT"
        elif used_chars + c.char_count > max_chars:
            c.sent, c.exclusion_reason = False, "CHAR_LIMIT"
        else:
            c.sent, c.exclusion_reason = True, None
            used += 1
            used_chars += c.char_count
    return ChunkSet(sorted(chunks, key=lambda c: c.sequence))
