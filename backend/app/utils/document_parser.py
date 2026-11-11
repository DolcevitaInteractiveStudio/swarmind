"""Estrae testo grezzo da PDF, DOCX, TXT, MD, JSON, CSV."""
import codecs
import os
import zipfile

import structlog

log = structlog.get_logger()

# Limiti su cio' che il worker materializza da un brief, indipendenti dal limite del piano sui byte
# caricati: un DOCX compresso o un JSON molto annidato possono espandersi centinaia di volte
# (security audit 2026-11: 9,8 KB di JSON -> 8,8 M caratteri con indent=2; 78 KB di DOCX -> 32 M).
MAX_EXTRACTED_CHARS = int(os.environ.get("MAX_EXTRACTED_CHARS", str(10_000_000)))
MAX_DOCX_UNCOMPRESSED_BYTES = int(os.environ.get("MAX_DOCX_UNCOMPRESSED_BYTES", str(100 * 1024 * 1024)))
MAX_DOCX_RATIO = 100


class DocumentTooLarge(RuntimeError):
    """Il testo estratto supererebbe i limiti: il brief va ridotto o diviso."""


def _bounded(text: str) -> str:
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentTooLarge(f"Extracted text exceeds {MAX_EXTRACTED_CHARS} characters")
    return text

# Ordine di prova. utf-8-sig solo se c'e' il BOM: accetta anche UTF-8 senza BOM e il log mentirebbe.
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")


def read_text_file(file_path) -> str:
    """Legge un file di testo caricato senza perdere byte (Word/Outlook salvano spesso in CP1252).

    Se nessun encoding va bene usa latin-1, che mappa ogni byte e non fallisce mai.
    Gli a capo diventano \\n, come nella lettura in modalita' testo.
    """
    with open(file_path, "rb") as f:
        raw = f.read()
    name = os.path.basename(file_path)
    for encoding in _TEXT_ENCODINGS:
        if encoding == "utf-8-sig" and not raw.startswith(codecs.BOM_UTF8):
            continue
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        encoding = "latin-1"
        text = raw.decode(encoding)
        log.warning("text_decoded_latin1_fallback", file=name)
    log.info("text_decoded", file=name, encoding=encoding)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_document(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _bounded(_parse_pdf(file_path))
    elif ext == ".docx":
        return _bounded(_parse_docx(file_path))
    elif ext in (".txt", ".md", ".csv"):
        return _bounded(read_text_file(file_path))
    elif ext == ".json":
        import json
        raw = read_text_file(file_path)
        json.loads(raw)  # solo validazione: indent=2 moltiplicava il testo per la profondita'
        return _bounded(raw)
    else:
        raise ValueError(f"Formato file non supportato: {ext}")


def _parse_pdf(path: str) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(path)
        pages, total = [], 0
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text = text.strip()
                total += len(text) + 2
                if total > MAX_EXTRACTED_CHARS:
                    raise DocumentTooLarge(f"Extracted text exceeds {MAX_EXTRACTED_CHARS} characters")
                pages.append(text)
        return "\n\n".join(pages)
    except DocumentTooLarge:
        raise
    except Exception as e:
        raise RuntimeError(f"Errore lettura PDF: {e}")


def _check_docx_archive(path: str) -> None:
    """Dimensioni non compresse dal central directory dello ZIP, prima di decomprimere."""
    compressed = os.path.getsize(path) or 1
    try:
        with zipfile.ZipFile(path) as z:
            total = 0
            for info in z.infolist():
                total += info.file_size
                if total > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise DocumentTooLarge("DOCX uncompressed content too large")
    except zipfile.BadZipFile as e:
        raise RuntimeError(f"Errore lettura DOCX: {e}")
    if total / compressed > MAX_DOCX_RATIO and total > 10 * 1024 * 1024:
        raise DocumentTooLarge("DOCX compression ratio too high")


def _parse_docx(path: str) -> str:
    _check_docx_archive(path)
    try:
        from docx import Document
        doc = Document(path)
        out, total = [], 0
        for p in doc.paragraphs:
            if p.text.strip():
                total += len(p.text) + 1
                if total > MAX_EXTRACTED_CHARS:
                    raise DocumentTooLarge(f"Extracted text exceeds {MAX_EXTRACTED_CHARS} characters")
                out.append(p.text)
        return "\n".join(out)
    except DocumentTooLarge:
        raise
    except Exception as e:
        raise RuntimeError(f"Errore lettura DOCX: {e}")
