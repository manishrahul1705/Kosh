"""Optional local OCR with isolated rendering and bounded process-tree resources."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import math
import time
from app.core.config import Settings


@dataclass
class OCRResult:
    text: str = ''
    confidence: float | None = None
    language: str = 'eng'
    error_code: str | None = None
    low_confidence_words: int = 0
    words: int = 0
    script: str | None = None
    script_verified: bool = True


class BaseOCRProvider:
    name='base'
    def available(self):return False
    def ocr_page(self,pdf_path,page_number):raise NotImplementedError


def bounded_pixels(width,height,dpi,maximum):
    return (math.isfinite(width) and math.isfinite(height) and width>0 and height>0
            and math.ceil(width*dpi/72)*math.ceil(height*dpi/72)<=maximum)


def _windows_job(process, megabytes):
    """Closing this bounded job kills render/Tesseract descendants, including on timeout."""
    import ctypes
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),
                 ('min_work',ctypes.c_size_t),('max_work',ctypes.c_size_t),('active',w.DWORD),
                 ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(ctypes.Structure):_fields_=[(n,ctypes.c_ulonglong) for n in ['readops','writeops','otherops','readbytes','writebytes','otherbytes']]
    class Limits(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                 ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
    k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.CreateJobObjectW(None,None);lim=Limits();lim.basic.flags=0x2000|0x200;lim.job_memory=megabytes*1024*1024
    if not handle or not k.SetInformationJobObject(handle,9,ctypes.byref(lim),ctypes.sizeof(lim)) or not k.AssignProcessToJobObject(handle,w.HANDLE(int(process._handle))):
        if handle:k.CloseHandle(handle)
        process.kill();process.wait();raise RuntimeError('OCR_RESOURCE_LIMIT_UNAVAILABLE')
    return lambda:k.CloseHandle(handle)


class TesseractOCRProvider(BaseOCRProvider):
    name='tesseract'
    def __init__(self,languages='eng',dpi=200,*,settings=None):
        self.settings=settings or Settings(_env_file=None,ocr_languages=languages,ocr_dpi=dpi)
        self.languages=self.settings.ocr_languages;self.dpi=self.settings.ocr_dpi
        self.executable=self.settings.ocr_executable or shutil.which('tesseract')
        if not self.executable and os.name=='nt':
            path=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Tesseract-OCR/tesseract.exe'
            if path.is_file():self.executable=str(path)
        self.dependency_error=None;self._checked=False
        self.detect_script=False
        self.deadline=None
    def available(self):
        if self._checked:return self.dependency_error is None
        self._checked=True
        if not re.fullmatch(r'[A-Za-z_]+(?:\+[A-Za-z_]+){0,3}',self.languages):
            self.dependency_error='OCR_LANGUAGE_CONFIGURATION_INVALID';return False
        if not self.executable or not Path(self.executable).is_file():
            self.dependency_error='OCR_DEPENDENCY_UNAVAILABLE';return False
        try:
            result=subprocess.run([self.executable,'--list-langs'],capture_output=True,timeout=5,check=True)
            available=result.stdout.decode('utf-8',errors='replace').splitlines()
            self.detect_script='osd' in available
            if not set(self.languages.split('+')).issubset(set(available)):self.dependency_error='OCR_LANGUAGE_UNAVAILABLE'
        except (OSError,subprocess.SubprocessError):self.dependency_error='OCR_DEPENDENCY_UNAVAILABLE'
        return self.dependency_error is None
    def ocr_page(self,pdf_path,page_number):
        if not self.available():return OCRResult(language=self.languages,error_code=self.dependency_error)
        cfg=self.settings
        budget=min(cfg.ocr_timeout_seconds,max(0,self.deadline-time.monotonic())) if self.deadline else cfg.ocr_timeout_seconds
        if budget<=0:return OCRResult(error_code='OCR_DOCUMENT_TIMEOUT')
        if not 1<=page_number<=cfg.extraction_max_pages:return OCRResult(error_code='OCR_PAGE_LIMIT')
        options={'source':str(Path(pdf_path).resolve()),'page':page_number,'executable':self.executable,
                 'language':self.languages,'dpi':self.dpi,'max_pixels':cfg.ocr_max_pixels,
                 'timeout':budget,'max_output':cfg.ocr_max_output_bytes,
                 'memory_mb':cfg.ocr_memory_mb,'confidence_threshold':cfg.ocr_min_confidence}
        options['detect_script']=self.detect_script
        with tempfile.TemporaryDirectory(prefix='gem-ocr-') as temp:
            options['directory']=temp;close_job=lambda:None
            with open(Path(temp)/'result.json','wb') as output:
                proc=subprocess.Popen([sys.executable,'-m','app.extraction.ocr_runner',json.dumps(options)],
                                      stdout=output,stderr=subprocess.DEVNULL,start_new_session=os.name!='nt',
                                      env={**os.environ,'OMP_THREAD_LIMIT':'1'})
                try:
                    if os.name=='nt':close_job=_windows_job(proc,cfg.ocr_memory_mb)
                    proc.wait(timeout=budget+5)
                except subprocess.TimeoutExpired:
                    if os.name!='nt':os.killpg(proc.pid,signal.SIGKILL)
                    else:proc.kill()
                    proc.wait();return OCRResult(error_code='OCR_TIMEOUT')
                except (RuntimeError,OSError):
                    if proc.poll() is None:proc.kill();proc.wait()
                    return OCRResult(error_code='OCR_RESOURCE_LIMIT_UNAVAILABLE')
                finally:close_job()
            result_path=Path(temp)/'result.json'
            if proc.returncode:return OCRResult(error_code='OCR_FAILED')
            if result_path.stat().st_size>cfg.ocr_max_output_bytes:return OCRResult(error_code='OCR_OUTPUT_LIMIT')
            try:return OCRResult(**json.loads(result_path.read_text(encoding='utf-8')))
            except (ValueError,TypeError,OSError):return OCRResult(error_code='OCR_FAILED')


def get_ocr_provider(settings):
    # Keep missing dependency state observable when enabled; disabled remains None.
    return TesseractOCRProvider(settings=settings) if settings.ocr_enabled else None
