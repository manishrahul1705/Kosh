"""Compatibility entry points backed by strict content/structure validation."""
from app.documents.formats import inspect_document,DocumentFormatError


def validate_by_extension(file_path,extension):
    try:
        inspect_document(file_path,expected=extension)
        return True,None
    except (DocumentFormatError,OSError) as exc:return False,str(exc)


def validate_pdf(path):return validate_by_extension(path,'pdf')
def validate_docx(path):return validate_by_extension(path,'docx')
def validate_xlsx(path):return validate_by_extension(path,'xlsx')
def validate_doc(path):return validate_by_extension(path,'doc')
def validate_xls(path):return validate_by_extension(path,'xls')
def validate_zip(path):return validate_by_extension(path,'zip')
def validate_csv(path):return validate_by_extension(path,'csv')
def validate_text(path):return validate_by_extension(path,'txt')
