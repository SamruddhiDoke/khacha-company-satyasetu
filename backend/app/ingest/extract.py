"""Attachment validation (by content, not by extension) and text extraction.

image -> Tesseract OCR (eng+hin+mar), with mean word confidence reported
pdf   -> embedded text layer per page; pages without text are OCR'd
audio -> local faster-whisper transcription with language probability reported
Video is not supported (no end-to-end path has been built and tested)."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class UnsupportedFile(Exception):
    pass


@dataclass
class Extraction:
    text: str
    method: str
    confidence: float | None = None
    pages: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    language: str | None = None
    duration_s: float | None = None

    def as_meta(self) -> dict:
        return {"method": self.method, "confidence": self.confidence, "pages": self.pages, "metadata": self.metadata,
                "warnings": self.warnings, "language": self.language, "duration_s": self.duration_s}


def sniff(data: bytes) -> tuple[str, str]:
    """Return (kind, mime) from magic bytes. Raises UnsupportedFile."""
    h = data[:16]
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image", "image/webp"
    if h.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if h.startswith(b"OggS"):
        return "audio", "audio/ogg"
    if h.startswith(b"ID3") or (h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio", "audio/mpeg"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"M4A ", b"M4B ", b"mp42", b"isom", b"dash"):
            return "audio", "audio/mp4"
        raise UnsupportedFile("Video files are not supported yet.")
    if h.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio", "audio/webm"  # browser voice recordings; video/webm is rejected after decoding
    raise UnsupportedFile("Unsupported file type. Upload a PNG/JPEG/WEBP image, a PDF, or an audio recording.")


def ocr_image(data: bytes) -> Extraction:
    import pytesseract
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")
    if max(img.size) < 1400:  # upscale small screenshots for better OCR
        scale = 1400 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    d = pytesseract.image_to_data(img, lang="eng+hin+mar", output_type=pytesseract.Output.DICT, timeout=60)
    confs = [float(c) for c, w in zip(d["conf"], d["text"]) if w.strip() and float(c) >= 0]
    text = pytesseract.image_to_string(img, lang="eng+hin+mar", timeout=60)
    conf = sum(confs) / len(confs) if confs else 0.0
    warnings = []
    if conf < 70:
        warnings.append(f"Low OCR confidence ({conf:.0f}/100): some words may be misread.")
    if not text.strip():
        warnings.append("No text was recognised in the image.")
    return Extraction(text.strip(), "ocr", round(conf, 1), [text.strip()], {}, warnings)


def extract_pdf(data: bytes) -> Extraction:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise UnsupportedFile("Encrypted PDFs are not supported.")
    meta = {}
    if reader.metadata:
        m = reader.metadata
        meta = {"producer": m.get("/Producer"), "creator": m.get("/Creator"), "title": m.get("/Title"),
                "creation_date": _pdf_date(m.get("/CreationDate")), "mod_date": _pdf_date(m.get("/ModDate"))}
        meta = {k: str(v) for k, v in meta.items() if v}
    pages: list[str] = []
    ocr_pages, confs = 0, []
    for i, page in enumerate(reader.pages[:20]):
        t = (page.extract_text() or "").strip()
        if len(t) < 30:  # scanned page -> OCR
            t, c = _ocr_pdf_page(data, i)
            ocr_pages += 1
            if c is not None:
                confs.append(c)
        pages.append(t)
    warnings = []
    if len(reader.pages) > 20:
        warnings.append(f"Only the first 20 of {len(reader.pages)} pages were processed.")
    method = "pdf_text" if not ocr_pages else ("ocr" if ocr_pages == len(pages) else "pdf_text+ocr")
    conf = round(sum(confs) / len(confs), 1) if confs else None
    if ocr_pages:
        warnings.append(f"{ocr_pages} scanned page(s) were read with OCR" + (f" (confidence {conf}/100)." if conf else "."))
    text = "\n\n".join(f"[Page {i + 1}]\n{p}" for i, p in enumerate(pages) if p)
    return Extraction(text, method, conf, pages, meta, warnings)


def _ocr_pdf_page(data: bytes, index: int) -> tuple[str, float | None]:
    try:
        import pypdfium2 as pdfium
        import pytesseract

        pdf = pdfium.PdfDocument(data)
        img = pdf[index].render(scale=2.5).to_pil().convert("L")
        d = pytesseract.image_to_data(img, lang="eng+hin+mar", output_type=pytesseract.Output.DICT, timeout=60)
        confs = [float(c) for c, w in zip(d["conf"], d["text"]) if w.strip() and float(c) >= 0]
        text = pytesseract.image_to_string(img, lang="eng+hin+mar", timeout=60)
        return text.strip(), (sum(confs) / len(confs) if confs else None)
    except Exception as e:
        log.warning("OCR of PDF page %s failed: %s", index, type(e).__name__)
        return "", None


def _pdf_date(v) -> str | None:
    if not v:
        return None
    s = str(v)
    if s.startswith("D:") and len(s) >= 10:
        return f"{s[2:6]}-{s[6:8]}-{s[8:10]}"
    return s[:10]


_whisper = None


def transcribe(path: str, max_seconds: int, model_name: str) -> Extraction:
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        _whisper = WhisperModel(model_name, device="cpu", compute_type="int8", download_root="/data/models")
    segments, info = _whisper.transcribe(path, beam_size=1, vad_filter=True)
    if info.duration and info.duration > max_seconds:
        raise UnsupportedFile(f"Audio is {info.duration:.0f}s long; the limit is {max_seconds}s.")
    text = " ".join(s.text.strip() for s in segments).strip()
    warnings = ["Speech-to-text can mishear names and numbers; check the transcript before relying on it."]
    if info.language not in ("en", "hi", "mr"):
        warnings.append(f"Detected language '{info.language}' is outside SatyaSetu's tested languages (en/hi/mr).")
    if info.language_probability < 0.6:
        warnings.append(f"Language detection was uncertain ({info.language_probability:.0%}).")
    if not text:
        warnings.append("No speech was recognised.")
    return Extraction(text, "transcription", round(info.language_probability * 100, 1), [text], {}, warnings,
                      language=info.language, duration_s=round(info.duration or 0, 1))
