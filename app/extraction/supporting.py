"""Normalize validated attachments into existing text/table/section records.

Internal page zero means a logical, non-paginated source. It is never presented
as a physical page. Identifiers and cell coordinates carry the provenance.
"""
import csv
import io
import posixpath
import re
from app.documents.formats import office_parts, safe_xml, decode_text, DocumentFormatError
from app.extraction.pdf_parser import ParsedTable
from app.extraction.headings import Heading, normalize_heading
from app.extraction.normalize import normalize_text, meaningful_char_count, word_count

W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
X='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def extract_supporting(path, kind, settings):
    from app.extraction.service import ExtractionRecord, PageRecord, table_to_text
    texts=[];tables=[];sections=[];offset=0;review=[];units=0;total_table_cells=0
    def add(text, location, normalized=None):
        nonlocal offset,units
        units+=1
        if units>settings.supporting_max_units:raise DocumentFormatError('DOCUMENT_UNIT_LIMIT')
        text=normalize_text(text)
        if offset+len(text)>settings.supporting_max_characters:
            raise DocumentFormatError('DOCUMENT_TEXT_LIMIT')
        label=location+': '+text[:100]
        sections.append(Heading(0,len(sections)+1,label,normalized or normalize_heading(text),None,
                                kind.upper()+'_LOCATION',float(offset),offset))
        texts.append(text);offset+=len(text)+1
    def table(rows, location):
        nonlocal total_table_cells
        total_table_cells+=sum(len(r) for r in rows)
        if total_table_cells>settings.supporting_max_cells:raise DocumentFormatError('DOCUMENT_CELL_LIMIT')
        top=offset
        add(table_to_text(rows),location.get('sheet') or f"Table {len(tables)+1}")
        tables.append(ParsedTable(0,len(tables)+1,rows,(0,float(top),0,float(offset)),location,kind+':cells'))
    if kind=='html':
        from app.documents.catalogue import catalogue_rows
        rows=catalogue_rows(path.read_bytes().decode('utf8'))
        table(rows,{'kind':'catalogue','table':1,'row_base':1,'section':'Bid Requirement (Allowed Values)'})
    elif kind in {'docx','xlsx'}:
        parts=office_parts(path)
        if kind=='docx':
            root=safe_xml(parts['word/document.xml']);body=root.find(W+'body')
            if body is None:raise DocumentFormatError('DOCX_BODY_MISSING')
            def paragraph(p):
                if any(n.tag in {W+'instrText',W+'fldSimple',W+'fldChar'} for n in p.iter()):
                    review.append('DOCX_FIELD_REVIEW');return '[DOCX field not evaluated]'
                return ''.join(e.text or '' for e in p.iter(W+'t'))
            for i,node in enumerate(body,1):
                if node.tag==W+'p':add(paragraph(node),f'Paragraph {i}')
                elif node.tag==W+'tbl':
                    rows=[[ '\n'.join(paragraph(p) for p in c.findall(W+'p')) for c in row.findall(W+'tc')] for row in node.findall(W+'tr')]
                    table(rows,{'kind':'docx','body_index':i,'table':len(tables)+1})
                    if any(n.tag==W+'gridSpan' or n.tag==W+'vMerge' for n in node.iter()):review.append('MERGED_TABLE_REVIEW')
                elif node.tag!=W+'sectPr':review.append('DOCX_UNSUPPORTED_BODY_CONTENT')
            for name in sorted(parts):
                if re.fullmatch(r'word/(?:(?:header|footer)\d+|footnotes|endnotes)\.xml',name):
                    for i,p in enumerate(safe_xml(parts[name]).iter(W+'p'),1):add(paragraph(p),f'{name.rsplit("/",1)[-1]} paragraph {i}')
            # Text embedded in drawing/text boxes is not silently ignored.
            if any(n.tag in {W+'altChunk',W+'object',W+'drawing'} for n in root.iter()):review.append('DOCX_EMBEDDED_CONTENT_REVIEW')
        else:
            root=safe_xml(parts['xl/workbook.xml']);sheets=root.findall('.//'+X+'sheet')
            if len(sheets)>settings.supporting_max_sheets:raise DocumentFormatError('WORKBOOK_SHEET_LIMIT')
            rels={r.get('Id'):r.get('Target','') for r in safe_xml(parts['xl/_rels/workbook.xml.rels'])}
            strings=[]
            if 'xl/sharedStrings.xml' in parts:
                strings=[''.join(t.text or '' for t in si.iter(X+'t')) for si in safe_xml(parts['xl/sharedStrings.xml'])]
            totalcells=0
            for sheet in sheets:
                target=rels.get(sheet.get(R+'id'),'')
                name=posixpath.normpath('xl/'+target) if not target.startswith('/') else target.lstrip('/')
                if not name.startswith('xl/worksheets/') or name not in parts:raise DocumentFormatError('WORKSHEET_RELATIONSHIP_INVALID')
                sr=safe_xml(parts[name]);rows=[];locations=[]
                for row in sr.findall('.//'+X+'sheetData/'+X+'row'):
                    if len(rows)>=settings.supporting_max_rows:raise DocumentFormatError('WORKBOOK_ROW_LIMIT')
                    vals={};cells={}
                    for c in row.findall(X+'c'):
                        totalcells+=1
                        if totalcells>settings.supporting_max_cells:raise DocumentFormatError('WORKBOOK_CELL_LIMIT')
                        ref=c.get('r','')
                        if not re.fullmatch(r'[A-Z]{1,3}[1-9]\d{0,6}',ref):raise DocumentFormatError('WORKBOOK_CELL_REFERENCE_INVALID')
                        col=0
                        for char in re.match(r'[A-Z]+',ref).group():col=col*26+ord(char)-64
                        if col>settings.supporting_max_columns:raise DocumentFormatError('WORKBOOK_COLUMN_LIMIT')
                        if col-1 in vals:raise DocumentFormatError('WORKBOOK_DUPLICATE_CELL')
                        if c.find(X+'f') is not None:
                            value=None;review.append('FORMULA_REVIEW_REQUIRED')
                        elif c.get('t')=='inlineStr':value=''.join(t.text or '' for t in c.iter(X+'t'))
                        else:
                            value=c.findtext(X+'v')
                            if c.get('t')=='s':
                                try:
                                    index=int(value)
                                    if index<0:raise ValueError('negative string index')
                                    value=strings[index]
                                except (ValueError,TypeError,IndexError):raise DocumentFormatError('SHARED_STRING_INVALID')
                        vals[col-1]=value;cells[col-1]=ref
                    length=max(vals,default=-1)+1
                    rows.append([vals.get(i) for i in range(length)]);locations.append([cells.get(i) for i in range(length)])
                merged=[m.get('ref') for m in sr.findall('.//'+X+'mergeCell')]
                if merged:review.append('MERGED_TABLE_REVIEW')
                table(rows,{'kind':'xlsx','sheet':sheet.get('name',''),'cells':locations,'merged_ranges':merged})
    elif kind=='txt':
        for i,line in enumerate(decode_text(path.read_bytes()).splitlines(),1):add(line,f'Line {i}')
    elif kind=='csv':
        text=decode_text(path.read_bytes());rows=[]
        for i,row in enumerate(csv.reader(io.StringIO(text)),1):
            if i>settings.supporting_max_rows:raise DocumentFormatError('CSV_ROW_LIMIT')
            if len(row)>settings.supporting_max_columns:raise DocumentFormatError('CSV_COLUMN_LIMIT')
            clean=[]
            for value in row:
                if value.lstrip().startswith(('=','@')):review.append('FORMULA_REVIEW_REQUIRED');clean.append(None)
                else:clean.append(value)
            rows.append(clean)
        table(rows,{'kind':'csv','row_base':1})
    else:raise DocumentFormatError('UNSUPPORTED_DOCUMENT_TYPE')
    text='\n'.join(texts);meaningful=meaningful_char_count(text)
    page=PageRecord(0,text,text,len(text),word_count(text),meaningful,meaningful>=settings.extraction_min_page_chars,0,0,'NATIVE',None,None,None)
    if not meaningful:review.append('EMPTY_DOCUMENT')
    status='PARTIAL_SUCCESS' if review else 'SUCCESS'
    record=ExtractionRecord(status,'PARTIAL' if review else 'GOOD','TEXT_NATIVE',review[0] if review else None,
                            '; '.join(sorted(set(review))) if review else None,pages=[page],tables=tables,
                            sections=sections,page_count=0,pages_with_text=0,total_characters=len(text),
                            total_words=word_count(text),coverage=1.0 if meaningful else 0.0)
    record.parser_version='bounded-supporting-xml-v1: '+kind
    return record
