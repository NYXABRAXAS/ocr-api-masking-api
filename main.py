from fastapi import FastAPI, File, UploadFile, Header, HTTPException, Depends
from fastapi.responses import FileResponse
import pytesseract
from PIL import Image
import re
import os
import cv2
import json
import tempfile
from starlette.background import BackgroundTasks

app = FastAPI(title="Aadhaar OCR & Masking API")

# IMPORTANT FOR RENDER
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# ---------------- API KEY ----------------
API_KEYS = ["mysecretkey123"]

def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

# ---------------- CLEANUP ----------------
def remove_file(path: str):
    if os.path.exists(path):
        os.remove(path)

# ---------------- OCR FUNCTION ----------------
def run_ocr(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img)
    return text

# ---------------- CLEAN NAME ----------------
def clean_name(value):
    if not value:
        return value
    value = re.sub(r'[^A-Za-z\s]', '', value)
    words = [w for w in value.split() if len(w) > 1]
    return " ".join(words)

# ---------------- MAIN API ----------------
@app.post("/v1/ocr/extract-and-mask")
async def extract_and_mask(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_api_key: str = Depends(verify_api_key)
):
    if file.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(400, "Only image files allowed")

    suffix = os.path.splitext(file.filename)[1]

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_input:
        tmp_input.write(await file.read())
        input_path = tmp_input.name

    try:
        # 1️⃣ OCR TEXT
        full_text = run_ocr(input_path)
        lines = full_text.split("\n")

        # 2️⃣ EXTRACT DATA
        extracted = {
            "aadhaar_number": None,
            "dob": None,
            "name": None
        }

        # Aadhaar number
        num_match = re.search(r'\b\d{4}\s?\d{4}\s?\d{4}\b', full_text)
        if num_match:
            extracted["aadhaar_number"] = num_match.group(0)

        # DOB
        dob_match = re.search(r'\d{2}/\d{2}/\d{4}', full_text)
        if dob_match:
            extracted["dob"] = dob_match.group(0)

        # Name detection
        for i, line in enumerate(lines):
            if "GOVERNMENT" in line.upper() or "INDIA" in line.upper():
                for j in range(1, 4):
                    if i + j < len(lines):
                        candidate = lines[i + j]
                        if len(candidate.split()) >= 2 and not any(c.isdigit() for c in candidate):
                            extracted["name"] = clean_name(candidate)
                            break
                if extracted["name"]:
                    break

        # 3️⃣ MASK IMAGE
        img = cv2.imread(input_path)

        if img is None:
            raise HTTPException(400, "Image not readable")

        # Mask Aadhaar area (simple detection)
        for match in re.finditer(r'\d{4}\s?\d{4}\s?\d{4}', full_text):
            h, w, _ = img.shape
            cv2.rectangle(img, (int(w*0.2), int(h*0.5)), (int(w*0.8), int(h*0.6)), (0, 0, 0), -1)

        output_path = input_path.replace(suffix, f"_masked{suffix}")
        cv2.imwrite(output_path, img)

        headers = {
            "X-OCR-Data": json.dumps(extracted),
            "Access-Control-Expose-Headers": "X-OCR-Data"
        }

        background_tasks.add_task(remove_file, input_path)
        background_tasks.add_task(remove_file, output_path)

        return FileResponse(
            path=output_path,
            media_type=file.content_type,
            filename=f"masked_{file.filename}",
            headers=headers
        )

    except Exception as e:
        remove_file(input_path)
        raise HTTPException(500, str(e))

# ---------------- HEALTH ----------------
@app.get("/")
def home():
    return {"status": "OCR & Masking API Running 🚀"}
