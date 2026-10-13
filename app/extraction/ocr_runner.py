"""Private local render/OCR child; no networking or document-controlled commands."""
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import re


def run(o):
    from app.extraction.ocr import OCRResult,bounded_pixels
    from dataclasses import asdict
    started=time.monotonic()
    if os.name!='nt':
        import resource
        limit=o['memory_mb']*1024*1024
        resource.setrlimit(resource.RLIMIT_AS,(limit,limit))
        resource.setrlimit(resource.RLIMIT_FSIZE,(o['max_output']*4,o['max_output']*4))
    from PIL import Image
    import pypdfium2 as pdfium
    directory=Path(o['directory']);image_path=directory/'page.png';base=directory/'ocr'
    source=Path(o['source'])
    try:
        with source.open('rb') as f:signature=f.read(5)
        if signature==b'%PDF-':
            with pdfium.PdfDocument(source) as pdf:
                if not 1<=o['page']<=len(pdf):return asdict(OCRResult(error_code='OCR_PAGE_LIMIT'))
                page=pdf[o['page']-1];w,h=page.get_size();scale=o['dpi']/72
                if not bounded_pixels(w,h,o['dpi'],o['max_pixels']):
                    return asdict(OCRResult(error_code='OCR_PIXEL_LIMIT'))
                bitmap=page.render(scale=scale);image=bitmap.to_pil()
                image.save(image_path);image.close();bitmap.close();page.close()
        else:
            with Image.open(source) as image:
                if image.width*image.height>o['max_pixels'] or getattr(image,'n_frames',1)!=1:
                    return asdict(OCRResult(error_code='OCR_PIXEL_LIMIT'))
                rgb=image.convert('RGB');rgb.save(image_path);rgb.close()
        if image_path.stat().st_size>o['max_pixels']*4:return asdict(OCRResult(error_code='OCR_DISK_LIMIT'))
        remaining=o['timeout']-(time.monotonic()-started)
        if remaining<=0:return asdict(OCRResult(error_code='OCR_TIMEOUT'))
        script=None;script_verified=False
        if o.get('detect_script'):
            script_path=directory/'script.txt'
            with script_path.open('wb') as output:
                detected=subprocess.run([o['executable'],str(image_path),'stdout','-l','osd','--psm','0'],
                    timeout=remaining,stdout=output,stderr=subprocess.DEVNULL)
            if script_path.stat().st_size>10000:return asdict(OCRResult(error_code='OCR_OUTPUT_LIMIT'))
            match=re.search(r'^Script: (.+)$',script_path.read_text(encoding='utf-8',errors='replace'),re.M)
            if detected.returncode==0 and match:
                script=match[1].strip();script_verified=True
                if script!='Latin' and not (script=='Devanagari' and 'hin' in o['language'].split('+')):
                    return asdict(OCRResult(language=o['language'],script=script,error_code='OCR_LANGUAGE_UNSUPPORTED'))
        remaining=o['timeout']-(time.monotonic()-started)
        if remaining<=0:return asdict(OCRResult(error_code='OCR_TIMEOUT'))
        subprocess.run([o['executable'],str(image_path),str(base),'-l',o['language'],'--psm','3','tsv'],
                       timeout=remaining,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tsv=base.with_suffix('.tsv')
        if tsv.stat().st_size>o['max_output']:return asdict(OCRResult(error_code='OCR_OUTPUT_LIMIT'))
        lines={};conf=[];low=0
        with tsv.open(encoding='utf-8') as f:
            for row in csv.DictReader(f,delimiter='\t'):
                if row.get('level')!='5' or not row.get('text','').strip():continue
                score=float(row['conf'])
                if not math.isfinite(score) or not 0<=score<=100:continue
                conf.append(score);low+=score<o['confidence_threshold']
                key=tuple(row[k] for k in ['block_num','par_num','line_num'])
                lines.setdefault(key,[]).append(row['text'])
        result=OCRResult('\n'.join(' '.join(words) for words in lines.values()),
                         sum(conf)/len(conf) if conf else None,o['language'],None,low,len(conf))
        result.script=script;result.script_verified=script_verified
        return asdict(result)
    except subprocess.TimeoutExpired:return asdict(OCRResult(error_code='OCR_TIMEOUT'))
    except Exception:return asdict(OCRResult(error_code='OCR_FAILED'))


if __name__=='__main__':print(json.dumps(run(json.loads(sys.argv[1])),ensure_ascii=True))
