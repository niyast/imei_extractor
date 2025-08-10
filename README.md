# IMEI Extractor API

Upload a PDF or image to extract valid 15-digit IMEI numbers using text extraction and OCR.

## Features
- Accepts a single file upload via `POST /extract-imei/`
- PDFs: tries `pdfplumber` text extraction, falls back to OCR (`pdf2image` + `pytesseract`)
- Images: OCR via `Pillow` + `pytesseract`
- IMEI validation using the Luhn algorithm
- Structured JSON response with IMEIs found
- Logging to both console and `imei_extractor.log`
- OpenAPI docs available at `/docs`

## Requirements

### System packages
You must install Tesseract OCR and Poppler (for `pdf2image`) on your system.

- Ubuntu/Debian:
  ```bash
  sudo apt-get update
  sudo apt-get install -y tesseract-ocr poppler-utils
  ```
- macOS (Homebrew):
  ```bash
  brew install tesseract poppler
  ```
- Windows:
  - Install Tesseract from: `https://github.com/UB-Mannheim/tesseract/wiki`
  - Install Poppler for Windows: `https://blog.alivate.com.au/poppler-windows/` (or another distribution)
  - After installing Poppler, note the `bin` directory path (contains `pdftoppm.exe`) and pass it as `poppler_path` to `pdf2image.convert_from_path` if needed, or add it to your `PATH`.

### Python packages
Install Python dependencies (Python 3.9+ recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -U pip
pip install -r requirements.txt
```

## Running the server

### Using Python directly
```bash
python imei_extractor_api.py
```
Server will start on `http://0.0.0.0:8080`. OpenAPI docs: `http://localhost:8080/docs`.

### Using uvicorn
```bash
uvicorn imei_extractor_api:app --host 0.0.0.0 --port 8080
```

## API Usage

- Endpoint: `POST /extract-imei/`
- Form field: `file` (single file)
- Response body example:

```json
{
  "filename": "example.pdf",
  "method_used": "pdfplumber",
  "imeis": ["490154203237518"],
  "num_chars_extracted": 12345,
  "num_imeis_found": 1
}
```

### curl example
```bash
curl -X POST \
  -F "file=@/path/to/your/file.pdf" \
  http://localhost:8080/extract-imei/
```

## Notes
- For PDFs, if `pdfplumber` extracts little or no text, the app automatically falls back to OCR using `pdf2image` + `pytesseract`.
- Ensure `tesseract-ocr` is installed and accessible in your `PATH`.
- Ensure `pdftoppm` is available (from Poppler) for `pdf2image`.
- Logs are written to the console and to `imei_extractor.log` in the working directory.