import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import pymupdf
from parsing.text_tools import normalize_ocr_text, reconstruct_ocr_rows
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream


TEXT_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "text_cache"
OCR_DPI = 300


def _ocr_language_signature() -> str:
    return ",".join(
        sorted(language.language_tag for language in OcrEngine.available_recognizer_languages)
    )


def _cache_path_for_pdf(pdf_path: str) -> Path:
    digest = hashlib.sha256()
    digest.update(
        f"ocr-dpi:{OCR_DPI}\0ocr-languages:{_ocr_language_signature()}\0".encode("utf-8")
    )
    with open(pdf_path, "rb") as pdf_file:
        for chunk in iter(lambda: pdf_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return TEXT_CACHE_DIR / f"{digest.hexdigest()}.txt"


def _write_text_cache(cache_path: Path, text: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as cache_file:
            temporary_path = Path(cache_file.name)
            cache_file.write(text)
        os.replace(temporary_path, cache_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _extract_text_without_cache(pdf_path: str) -> str:
    """
    Extract text directly from digital PDFs and use Windows OCR for scanned pages.
    """

    async def _extract() -> str:
        ocr_engine = None
        extracted_pages = []
        with pymupdf.open(pdf_path) as doc:
            for page in doc:
                page_text = page.get_text("text").strip()
                if not page_text:
                    if ocr_engine is None:
                        hebrew_language = Language("he-IL")
                        hebrew_supported = OcrEngine.is_language_supported(hebrew_language)
                        ocr_engine = OcrEngine.try_create_from_language(hebrew_language)
                        if not hebrew_supported:
                            print(
                                "[Warning] Hebrew OCR language (he-IL) is not installed. "
                                "Hebrew fields such as location may not be recognized; "
                                "install the Hebrew language pack and process the PDF again."
                            )
                        elif not ocr_engine:
                            print("[Warning] Could not initialize the Hebrew OCR engine.")
                        if not ocr_engine:
                            ocr_engine = OcrEngine.try_create_from_user_profile_languages()
                        if not ocr_engine:
                            raise RuntimeError("Windows OCR could not initialize any available language engine.")

                    pixmap = page.get_pixmap(dpi=OCR_DPI)
                    image_bytes = pixmap.tobytes("png")
                    stream = InMemoryRandomAccessStream()
                    writer = DataWriter(stream)
                    writer.write_bytes(image_bytes)
                    await writer.store_async()
                    await writer.flush_async()
                    stream.seek(0)
                    decoder = await BitmapDecoder.create_async(stream)
                    bitmap = await decoder.get_software_bitmap_async()
                    result = await ocr_engine.recognize_async(bitmap)
                    words = [
                        (
                            word.bounding_rect.x,
                            word.bounding_rect.y + word.bounding_rect.height / 2,
                            word.bounding_rect.height,
                            word.text
                        )
                        for line in result.lines
                        for word in line.words
                    ]
                    page_text = reconstruct_ocr_rows(words)
                extracted_pages.append(page_text)

        return normalize_ocr_text("\n".join(extracted_pages))

    return asyncio.run(_extract())


def extract_text_from_pdf(pdf_path: str, *, force_ocr: bool = False) -> str:
    cache_path = _cache_path_for_pdf(pdf_path)
    if not force_ocr and cache_path.is_file():
        return cache_path.read_text(encoding="utf-8")

    extracted_text = _extract_text_without_cache(pdf_path)
    if extracted_text.strip():
        _write_text_cache(cache_path, extracted_text)
    return extracted_text