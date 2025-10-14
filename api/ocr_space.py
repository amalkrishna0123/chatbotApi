# ocr_space.py - Enhanced version with multi-page PDF support
import io
import os
import requests
from PIL import Image, ImageOps, ImageEnhance

# OCR.space credentials
OCR_API_KEY = "K82681714188957"
OCR_ENDPOINT = "https://api.ocr.space/parse/image"

def _pre_process(img: Image.Image, max_dim=2048) -> bytes:
    """
    Light, fast in-memory prep: orient, contrast, shrink.
    Returns JPEG bytes ready for upload.
    """
    img = ImageOps.exif_transpose(img)                 # auto-rotate via EXIF
    img = ImageEnhance.Contrast(img).enhance(1.15)     # bump contrast
    img.thumbnail((max_dim, max_dim), Image.LANCZOS)   # keep under 5 MB limit

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()

def ocr_space_file(file_obj, is_pdf=False, language="eng"):
    """
    Call OCR.space Parse API.

    :param file_obj: Django InMemoryUploadedFile or file-like object
    :param is_pdf: bool
    :param language: OCR.space language string (default "eng")
    :return: (parsed_text: str, exit_code: int, error: str)
    """
    try:
        if is_pdf:
            # Reset file pointer for PDF
            file_obj.seek(0)
            files = {"file": (file_obj.name, file_obj.read(), "application/pdf")}
        else:
            # Reset file pointer for image
            file_obj.seek(0)
            img_bytes = _pre_process(Image.open(file_obj))
            files = {"file": (file_obj.name, img_bytes, "image/jpeg")}

        data = {
            "apikey": OCR_API_KEY,
            "language": language,
            "isTable": "true",
            "OCREngine": "2",
            "scale": "true",
            "isCreateSearchablePdf": "false",
            "isSearchablePdfHideTextLayer": "false",
        }

        resp = requests.post(OCR_ENDPOINT, files=files, data=data, timeout=60)
        
        if resp.status_code != 200:
            return "", 2, f"HTTP {resp.status_code}"

        j = resp.json()
        
        if j.get("IsErroredOnProcessing"):
            return "", 4, j.get("ErrorMessage", "Unknown OCR.space error")

        parsed_results = j.get("ParsedResults", [])
        if not parsed_results:
            return "", 5, "No OCR results returned"
            
        parsed_text = parsed_results[0].get("ParsedText", "")
        return parsed_text.strip(), 0, ""
        
    except requests.RequestException as exc:
        return "", 1, f"Network error: {exc}"
    except Exception as exc:
        return "", 6, f"Processing error: {exc}"

def ocr_space_file_multi_lang(file_obj, is_pdf=False):
    """
    Try OCR with multiple languages by making separate API calls.
    First tries English, then Arabic if English doesn't yield good results.
    Returns the best result.
    
    Enhanced to handle multi-page PDFs by processing all pages.
    """
    # For PDF files, we need to process all pages
    if is_pdf:
        return ocr_space_pdf_all_pages(file_obj)
    
    # For single images, use the existing logic
    # Try English first
    eng_text, eng_code, eng_error = ocr_space_file(file_obj, False, "eng")
    
    # Check if English OCR was successful and returned substantial text
    if eng_code == 0 and len(eng_text.strip()) > 10:  # Reduced threshold
        return eng_text, eng_code, eng_error
    
    # If English didn't work well, try Arabic
    # Reset file pointer
    file_obj.seek(0)
    
    ara_text, ara_code, ara_error = ocr_space_file(file_obj, False, "ara")
    
    if ara_code == 0:
        return ara_text, ara_code, ara_error
    
    # If both failed, return the English result (even if empty)
    return eng_text, eng_code, eng_error

def ocr_space_pdf_all_pages(file_obj):
    """
    Process all pages of a PDF file using OCR.space
    Returns combined text from all pages.
    """
    try:
        # Reset file pointer
        file_obj.seek(0)
        pdf_content = file_obj.read()
        
        combined_text = ""
        
        # OCR.space automatically processes all pages in PDF files
        # We'll use a single API call as OCR.space handles multi-page PDFs
        files = {"file": (file_obj.name, pdf_content, "application/pdf")}
        
        data = {
            "apikey": OCR_API_KEY,
            "language": "eng",  # Start with English
            "isTable": "true",
            "OCREngine": "2",
            "scale": "true",
            "isCreateSearchablePdf": "false",
            "isSearchablePdfHideTextLayer": "false",
        }

        # First try with English
        resp = requests.post(OCR_ENDPOINT, files=files, data=data, timeout=90)
        
        if resp.status_code != 200:
            return "", 2, f"HTTP {resp.status_code}"

        j = resp.json()
        
        if j.get("IsErroredOnProcessing"):
            return "", 4, j.get("ErrorMessage", "Unknown OCR.space error")

        parsed_results = j.get("ParsedResults", [])
        if not parsed_results:
            return "", 5, "No OCR results returned"
        
        # Combine text from all pages
        for result in parsed_results:
            page_text = result.get("ParsedText", "")
            if page_text.strip():
                combined_text += page_text + "\n\n"
        
        # Check if we got substantial text with English
        if len(combined_text.strip()) > 10:
            return combined_text.strip(), 0, ""
        
        # If English didn't yield good results, try Arabic
        # Reset file pointer and try Arabic
        file_obj.seek(0)
        files = {"file": (file_obj.name, pdf_content, "application/pdf")}
        data["language"] = "ara"
        
        resp = requests.post(OCR_ENDPOINT, files=files, data=data, timeout=90)
        
        if resp.status_code != 200:
            # Return English result even if it's minimal
            return combined_text.strip(), 0, f"Arabic failed but returning English text"
        
        j = resp.json()
        
        if j.get("IsErroredOnProcessing"):
            return combined_text.strip(), 0, f"Arabic failed but returning English text"
        
        parsed_results = j.get("ParsedResults", [])
        if not parsed_results:
            return combined_text.strip(), 0, f"No Arabic results but returning English text"
        
        # Combine Arabic results
        arabic_text = ""
        for result in parsed_results:
            page_text = result.get("ParsedText", "")
            if page_text.strip():
                arabic_text += page_text + "\n\n"
        
        return arabic_text.strip(), 0, ""
        
    except requests.RequestException as exc:
        return "", 1, f"Network error: {exc}"
    except Exception as exc:
        return "", 6, f"Processing error: {exc}"

def detect_document_side(text):
    """
    Detect if text represents front or back side of Emirates ID.
    Returns 'front', 'back', or 'unknown'
    """
    text_lower = text.lower()
    
    # Back side indicators
    back_indicators = [
        "الكفالة", "employer", "صاحب العمل", "occupation", "المهنة",
        "occupation", "employer", "issuing place", "مكان الإصدار",
        "family sponsor", "كفالة عائلية"
    ]
    
    # Front side indicators  
    front_indicators = [
        "emirates id", "identity card", "بطاقة الهوية", "name", "الاسم",
        "nationality", "الجنسية", "date of birth", "تاريخ الميلاد"
    ]
    
    back_score = sum(1 for indicator in back_indicators if indicator in text_lower)
    front_score = sum(1 for indicator in front_indicators if indicator in text_lower)
    
    if back_score > front_score:
        return "back"
    elif front_score > back_score:
        return "front"
    else:
        return "unknown"