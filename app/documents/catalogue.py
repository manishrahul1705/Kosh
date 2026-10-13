"""Only the observed public GeM static specification table; no JS/assets/forms."""
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from app.documents.formats import DocumentFormatError

def is_catalogue_url(url):
 try:
  p=urlsplit(url)
  return p.scheme=='https' and p.hostname=='bidplus.gem.gov.in' and p.port in (None,443) and not p.username and not p.password and not p.query and not p.fragment and bool(re.fullmatch(r'/bidding/bid/showCatalogue/[A-Za-z0-9_-]{10,}',p.path))
 except ValueError:return False

def catalogue_rows(html):
 if len(html.encode('utf8'))>1_000_000:raise DocumentFormatError('CATALOGUE_SIZE_LIMIT')
 soup=BeautifulSoup(html,'html.parser')
 if len(soup.find_all(True))>20000:raise DocumentFormatError('CATALOGUE_NODE_LIMIT')
 for n in soup.find_all(['script','style','nav','header','footer','noscript','template','iframe','object']):n.decompose()
 tables=[]
 expected=['category','specification','bid requirement (allowed values)']
 for table in soup.find_all('table'):
  headers=[' '.join(h.get_text(' ',strip=True).lower().split()) for h in table.find_all('th')]
  if headers==expected:tables.append(table)
 if len(tables)!=1:raise DocumentFormatError('CATALOGUE_REQUIREMENT_TABLE_MISSING')
 table=tables[0]
 if table.find(['a','img','input','form','table']):raise DocumentFormatError('CATALOGUE_LINKED_OR_DYNAMIC_CONTENT')
 rows=[['Category','Specification','Bid Requirement (Allowed Values)']];spans={}
 for tr in table.find_all('tr'):
  cells=tr.find_all('td',recursive=False)
  if not cells:continue
  row=[];cursor=0
  for cell in cells:
   while cursor in spans:
    value,left=spans[cursor];row.append(value)
    if left==1:del spans[cursor]
    else:spans[cursor]=(value,left-1)
    cursor+=1
   if cell.get('colspan','1')!='1':raise DocumentFormatError('CATALOGUE_COMPLEX_TABLE_REVIEW')
   # Actual GeM HTML has omitted closing TR tags. Never mix nested row text.
   value=' '.join(str(t).strip() for t in cell.find_all(string=True) if t.find_parent('td')==cell and str(t).strip())
   try:span=int(cell.get('rowspan','1'))
   except ValueError:raise DocumentFormatError('CATALOGUE_INVALID_ROWSPAN')
   if not 1<=span<=100:raise DocumentFormatError('CATALOGUE_INVALID_ROWSPAN')
   row.append(value)
   if span>1:spans[cursor]=(value,span-1)
   cursor+=1
  if len(row)!=3 or not row[1] or not row[2]:raise DocumentFormatError('CATALOGUE_INCOMPLETE_ROW')
  rows.append(row)
  if len(rows)>2000:raise DocumentFormatError('CATALOGUE_ROW_LIMIT')
 if len(rows)<2 or spans:raise DocumentFormatError('CATALOGUE_INCOMPLETE_TABLE')
 return rows
