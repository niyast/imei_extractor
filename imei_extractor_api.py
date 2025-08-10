import io
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import pdfplumber
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
import uvicorn


LOG_FILE_NAME = "imei_extractor.log"
APP_NAME = "IMEI Extractor API"
APP_DESCRIPTION = (
    "Upload a PDF or image to extract valid 15-digit IMEI numbers using text extraction and OCR."
)
APP_VERSION = "1.0.0"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("imei_extractor")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers in reload scenarios
    if logger.handlers:
        return logger

    log_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(LOG_FILE_NAME)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()
app = FastAPI(title=APP_NAME, description=APP_DESCRIPTION, version=APP_VERSION)


class ExtractResponse(BaseModel):
    filename: str
    method_used: str
    imeis: List[str]
    num_chars_extracted: int
    num_imeis_found: int


IMEI_REGEX = re.compile(r"\b\d{15}\b")


def is_pdf(filename: str, content_type: Optional[str]) -> bool:
    if filename and filename.lower().endswith(".pdf"):
        return True
    if content_type and content_type.lower() in {"application/pdf", "application/x-pdf"}:
        return True
    return False


def luhn_checksum_is_valid(number_str: str) -> bool:
    if not number_str.isdigit():
        return False
    digits = [int(ch) for ch in number_str]
    checksum = 0
    # Luhn algo: from right, double every second digit, subtract 9 if > 9
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:  # positions to double
            doubled = digit * 2
            if doubled > 9:
                doubled -= 9
            checksum += doubled
        else:
            checksum += digit
    return checksum % 10 == 0


def extract_imeis_from_text(text: str) -> List[str]:
    if not text:
        return []
    candidates = IMEI_REGEX.findall(text)
    valid: List[str] = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        if luhn_checksum_is_valid(candidate):
            valid.append(candidate)
            seen.add(candidate)
    return valid


def extract_text_with_pdfplumber(pdf_path: str) -> str:
    parts: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text(x_tolerance=1.5, y_tolerance=1.5) or ""
            except Exception:
                text = page.extract_text() or ""
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def extract_text_with_pdf_ocr(pdf_path: str, dpi: int = 300) -> str:
    images = convert_from_path(pdf_path, dpi=dpi)
    parts: List[str] = []
    for image in images:
        text = pytesseract.image_to_string(image)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def extract_text_from_image(image_path: str) -> str:
    with Image.open(image_path) as img:
        return pytesseract.image_to_string(img).strip()


def save_upload_to_temp(upload: UploadFile) -> Tuple[str, int]:
    suffix = Path(upload.filename or "").suffix
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix or None)
    os.close(tmp_fd)
    total_bytes = 0
    with open(tmp_path, "wb") as out_file:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            out_file.write(chunk)
    # Reset file read pointer for potential re-reads (not strictly needed)
    try:
        upload.file.seek(0)
    except Exception:
        pass
    return tmp_path, total_bytes


@app.post("/extract-imei/", response_model=ExtractResponse)
async def extract_imei(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    tmp_path = None
    try:
        tmp_path, total_bytes = save_upload_to_temp(file)
        logger.info(
            "Received upload | filename=%s | content_type=%s | size_bytes=%s",
            file.filename,
            file.content_type,
            total_bytes,
        )

        method_used = ""
        extracted_text = ""

        if is_pdf(file.filename or "", file.content_type):
            # First attempt: pdfplumber
            try:
                extracted_text = extract_text_with_pdfplumber(tmp_path)
                method_used = "pdfplumber"
            except Exception as e:
                logger.warning("pdfplumber failed: %s", e)
                extracted_text = ""

            # Fallback to OCR if empty or short
            if not extracted_text or len(extracted_text) < 10:
                try:
                    ocr_text = extract_text_with_pdf_ocr(tmp_path)
                    if ocr_text:
                        extracted_text = ocr_text
                        method_used = "pdf_ocr"
                except Exception as e:
                    logger.warning("PDF OCR failed: %s", e)

            if not method_used:
                method_used = "unknown_pdf"
        else:
            # Treat as image
            try:
                extracted_text = extract_text_from_image(tmp_path)
                method_used = "image_ocr"
            except Exception as e:
                logger.error("Image OCR failed: %s", e)
                raise HTTPException(status_code=400, detail="Failed to process image file for OCR")

        num_chars = len(extracted_text or "")
        imeis = extract_imeis_from_text(extracted_text or "")

        logger.info(
            "Extraction complete | method=%s | chars=%d | imeis_found=%d",
            method_used,
            num_chars,
            len(imeis),
        )

        return JSONResponse(
            status_code=200,
            content={
                "filename": file.filename or Path(tmp_path).name,
                "method_used": method_used,
                "imeis": imeis,
                "num_chars_extracted": num_chars,
                "num_imeis_found": len(imeis),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error during extraction: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error during IMEI extraction")
    finally:
        # Cleanup temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                logger.warning("Failed to remove temp file: %s", tmp_path)


if __name__ == "__main__":
    # Run the app with: python imei_extractor_api.py
    uvicorn.run("imei_extractor_api:app", host="0.0.0.0", port=8010, reload=False)