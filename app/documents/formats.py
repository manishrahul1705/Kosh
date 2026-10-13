"""Bounded, content-based document validation. Never extract ZIP entries to disk.

Office parsers consume validated XML only; no macros, OLE, external relationships,
DTD/entities, formulas or executable payloads are evaluated.
"""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import zipfile
import xml.etree.ElementTree as ET
import struct

SUPPORTED_TYPES = frozenset({'pdf','docx','xlsx','csv','txt','png','jpg','jpeg'})
MIMES = {'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'html':'text/html',
         'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','txt':'text/plain',
         'csv':'text/csv','png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg',
         'doc':'application/msword','xls':'application/vnd.ms-excel','zip':'application/zip'}


class DocumentFormatError(ValueError):
    pass


@dataclass(frozen=True)
class OfficeLimits:
    max_file_bytes: int = 25*1024*1024
    max_entries: int = 2000
    max_entry_bytes: int = 10*1024*1024
    max_uncompressed_bytes: int = 50*1024*1024
    max_ratio: float = 100
    max_xml_nodes: int = 200000


def safe_xml(data, limits=OfficeLimits()):
    if len(data)>limits.max_entry_bytes:raise DocumentFormatError('OFFICE_ENTRY_LIMIT')
    try:
        text=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)',text,re.I):raise DocumentFormatError('XML_DTD_FORBIDDEN')
        root=ET.fromstring(text)
        if sum(1 for _ in root.iter())>limits.max_xml_nodes:raise DocumentFormatError('XML_NODE_LIMIT')
        return root
    except (UnicodeError,ET.ParseError) as exc:raise DocumentFormatError('MALFORMED_OFFICE_XML') from exc


def office_parts(path, limits=OfficeLimits()):
    """Return bounded ZIP members as bytes after structural and active-content checks."""
    if Path(path).stat().st_size>limits.max_file_bytes:raise DocumentFormatError('DOCUMENT_SIZE_LIMIT')
    # ZipFile eagerly allocates its central-directory objects. Bound the real
    # directory before constructing it, including when the EOCD count lies.
    size=Path(path).stat().st_size
    with open(path,'rb') as f:
        f.seek(max(0,size-65557));tail=f.read(65557);at=tail.rfind(b'PK\x05\x06')
        if at<0 or len(tail)-at<22:raise DocumentFormatError('MALFORMED_OFFICE_ZIP')
        _,disk,central_disk,on_disk,count,length,offset,comment=struct.unpack_from('<4s4H2LH',tail,at)
        if disk or central_disk or on_disk!=count or count==65535 or offset==0xFFFFFFFF:
            raise DocumentFormatError('ZIP64_OR_MULTIDISK_UNSUPPORTED')
        if count>limits.max_entries:raise DocumentFormatError('OFFICE_ENTRY_COUNT_LIMIT')
        if offset+length>size or at+22+comment!=len(tail):raise DocumentFormatError('MALFORMED_OFFICE_ZIP')
        f.seek(offset);central=f.read(length);cursor=0;actual=0
        while cursor<len(central):
            if len(central)-cursor<46 or central[cursor:cursor+4]!=b'PK\x01\x02':raise DocumentFormatError('MALFORMED_OFFICE_ZIP')
            actual+=1
            if actual>limits.max_entries:raise DocumentFormatError('OFFICE_ENTRY_COUNT_LIMIT')
            namesize,extrasize,commentsize=struct.unpack_from('<3H',central,cursor+28)
            cursor+=46+namesize+extrasize+commentsize
        if cursor!=len(central) or actual!=count:raise DocumentFormatError('MALFORMED_OFFICE_ZIP')
    try:
        with zipfile.ZipFile(path) as z:
            infos=z.infolist()
            if len(infos)>limits.max_entries:raise DocumentFormatError('OFFICE_ENTRY_COUNT_LIMIT')
            names=set();total=0
            for i in infos:
                name=i.filename
                p=PurePosixPath(name)
                if '\\' in name or p.is_absolute() or '..' in p.parts or ':' in name or '\x00' in name:
                    raise DocumentFormatError('ARCHIVE_UNSAFE_PATH')
                if name in names:raise DocumentFormatError('ARCHIVE_DUPLICATE_ENTRY')
                names.add(name);total+=i.file_size
                if i.flag_bits&1 or (i.external_attr>>16)&0o170000==0o120000:raise DocumentFormatError('ARCHIVE_UNSAFE_ENTRY')
                if i.file_size>limits.max_entry_bytes or total>limits.max_uncompressed_bytes or i.file_size/max(1,i.compress_size)>limits.max_ratio:
                    raise DocumentFormatError('OFFICE_DECOMPRESSION_LIMIT')
                low=name.lower()
                if any(x in low for x in ['vbaproject','/embeddings/','activex','externallinks/']) or low.endswith(('.exe','.dll','.js','.vbs','.ps1','.bat','.cmd','.jar','.hta','.zip','.7z')):
                    raise DocumentFormatError('OFFICE_ACTIVE_CONTENT_FORBIDDEN')
            parts={i.filename:z.read(i) for i in infos if not i.is_dir()}
            for name,data in parts.items():
                if name.lower().endswith(('.xml','.rels')):
                    root=safe_xml(data,limits)
                    if name.lower().endswith('.rels'):
                        for rel in root:
                            target=rel.get('Target','')
                            if rel.get('TargetMode','').lower()=='external' or re.match(r'^[a-z]+:',target,re.I):
                                raise DocumentFormatError('OFFICE_EXTERNAL_RELATIONSHIP_FORBIDDEN')
                            # Relative internal relationships may ascend one part directory,
                            # but must resolve within the container at extraction time.
                    if name=='[Content_Types].xml' and any('macroenabled' in e.get('ContentType','').lower() for e in root):
                        raise DocumentFormatError('OFFICE_MACRO_FORMAT_FORBIDDEN')
            return parts
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,OSError) as exc:
        raise DocumentFormatError('MALFORMED_OFFICE_ZIP') from exc


def office_type(parts):
    if '[Content_Types].xml' not in parts or '_rels/.rels' not in parts:raise DocumentFormatError('OOXML_STRUCTURE_MISSING')
    root=safe_xml(parts['[Content_Types].xml'])
    types={x.get('PartName','').lstrip('/'):x.get('ContentType','') for x in root}
    for kind,main,typ in [('docx','word/document.xml','application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'),
                          ('xlsx','xl/workbook.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')]:
        if main in parts and types.get(main)==typ:
            if kind=='xlsx' and ('xl/_rels/workbook.xml.rels' not in parts or not any(n.startswith('xl/worksheets/') and n.endswith('.xml') for n in parts)):
                raise DocumentFormatError('XLSX_STRUCTURE_MISSING')
            return kind
    raise DocumentFormatError('OOXML_STRUCTURE_MISSING')


def decode_text(data):
    if len(data)>5*1024*1024:raise DocumentFormatError('TEXT_SIZE_LIMIT')
    try:
        text=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    except UnicodeDecodeError:
        try:text=data.decode('cp1252')
        except UnicodeDecodeError as exc:raise DocumentFormatError('UNSUPPORTED_TEXT_ENCODING') from exc
    if '\x00' in text or sum(not c.isprintable() and c not in '\r\n\t' for c in text)>max(0,len(text)//100):
        raise DocumentFormatError('BINARY_MASQUERADING_AS_TEXT')
    if re.search(r'<\s*(?:!doctype\s+html|html\b|head\b|body\b|script\b)',text[:10000],re.I):
        raise DocumentFormatError('HTML_MASQUERADING_AS_DOCUMENT')
    return text


def inspect_document(path, expected=None, content_type=None, limits=OfficeLimits()):
    path=Path(path)
    with path.open('rb') as f:head=f.read(1024)
    if not head.startswith(b'%PDF') and path.stat().st_size>limits.max_file_bytes:
        raise DocumentFormatError('DOCUMENT_SIZE_LIMIT')
    expected=(expected or '').lower().lstrip('.')
    if expected=='html':
        from app.documents.catalogue import catalogue_rows
        try:catalogue_rows(path.read_bytes().decode('utf8'))
        except UnicodeError as exc:raise DocumentFormatError('CATALOGUE_ENCODING_INVALID') from exc
        kind='html'
    elif head.startswith(b'%PDF'):kind='pdf'
    elif head.startswith(b'PK\x03\x04'):
        parts=office_parts(path,limits)
        if expected=='zip':kind='zip'
        else:kind=office_type(parts)
    elif head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        if expected not in {'doc','xls'}:raise DocumentFormatError('UNSUPPORTED_OLE_DOCUMENT')
        kind=expected
    elif head.startswith(b'\x89PNG\r\n\x1a\n'):kind='png'
    elif head.startswith(b'\xff\xd8\xff'):kind='jpg'
    elif head.startswith((b'MZ',b'\x7fELF')):raise DocumentFormatError('EXECUTABLE_FORBIDDEN')
    else:
        if expected not in {'','txt','csv'}:raise DocumentFormatError('DOCUMENT_SIGNATURE_MISMATCH')
        decode_text(path.read_bytes());kind='csv' if expected=='csv' else 'txt'
    if expected and expected not in {kind,'jpeg' if kind=='jpg' else kind}:
        raise DocumentFormatError('EXTENSION_SIGNATURE_MISMATCH')
    if kind in {'png','jpg'}:
        from PIL import Image
        try:
            with Image.open(path) as image:
                if image.width*image.height>20_000_000 or getattr(image,'n_frames',1)!=1:raise DocumentFormatError('IMAGE_PIXEL_LIMIT')
                image.verify()
        except (OSError,ValueError,Image.DecompressionBombError) as exc:raise DocumentFormatError('IMAGE_INVALID') from exc
    mime=(content_type or '').split(';')[0].strip().lower()
    allowed={MIMES.get(kind),'application/octet-stream','binary/octet-stream',''}
    if kind in {'docx','xlsx','zip'}:allowed.add('application/zip');allowed.add('application/x-zip-compressed')
    if kind=='csv':allowed.add('text/plain');allowed.add('application/csv')
    if mime not in allowed:raise DocumentFormatError('MIME_SIGNATURE_MISMATCH')
    return kind
