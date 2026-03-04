"""
OCR Service with Enhanced Fallback Pipeline
Supports: OpenCV+Tesseract → PaddleOCR → OpenAI Vision
Designed for invoice processing with confidence scoring and error handling
"""

import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
import logging
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import base64
import io
import os

# Optional imports with fallbacks
try:
    import paddleocr
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False
    logging.warning("PaddleOCR not available. Install with: pip install paddleocr")

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI not available. Install with: pip install openai")


class OCRMethod(str, Enum):
    """OCR processing methods"""
    TESSERACT_LAYOUT = "tesseract_layout"
    TESSERACT_MULTI_PSM = "tesseract_multi_psm"
    TESSERACT_RAW = "tesseract_raw"
    PADDLE_OCR = "paddle_ocr"
    OPENAI_VISION = "openai_vision"


@dataclass
class OCRResult:
    """OCR processing result with metadata"""
    text: str
    method: OCRMethod
    confidence: float
    processing_time: float
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class OCRService:
    """Enhanced OCR service with multiple fallback methods"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Initialize PaddleOCR if available
        self.paddle_ocr = None
        if PADDLE_AVAILABLE:
            try:
                self.paddle_ocr = paddleocr.PaddleOCR(
                    use_angle_cls=True,
                    lang='en',
                    show_log=False
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize PaddleOCR: {e}")
        
        # OpenAI client
        self.openai_client = None
        if OPENAI_AVAILABLE:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.openai_client = openai.OpenAI(api_key=api_key)
            else:
                self.logger.warning("OPENAI_API_KEY not found in environment")

    def clean_ocr_text(self, text: str) -> str:
        """Clean and normalize OCR output"""
        if not text:
            return ""

        # Remove NULL bytes and control characters
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        # Normalize whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n', text)
        
        # Remove lines with too many special characters
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Keep line if >40% is alphanumeric or it's very short
            alphanum = sum(c.isalnum() or c.isspace() for c in line)
            total = len(line)
            
            if total < 5 or (alphanum / total) > 0.4:
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)

    def preprocess_image(self, pil_img: Image.Image) -> Image.Image:
        """Preprocess image for optimal OCR"""
        # Convert PIL to numpy array
        img = np.array(pil_img)
        
        # Convert to grayscale
        if len(img.shape) == 3:
            if img.shape[2] == 4:
                gray = cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY)
            else:
                gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img
        
        # Get dimensions
        height, width = gray.shape
        
        # Upscale to 2400px height for optimal OCR
        if height < 2400:
            scale = 2400 / height
            new_width = int(width * scale)
            gray = cv2.resize(gray, (new_width, 2400), interpolation=cv2.INTER_CUBIC)
        elif height > 5000:
            scale = 2400 / height
            new_width = int(width * scale)
            gray = cv2.resize(gray, (new_width, 2400), interpolation=cv2.INTER_AREA)
        
        # Light denoising
        denoised = cv2.fastNlMeansDenoising(gray, h=3)
        
        # Otsu's binarization
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        return Image.fromarray(binary)

    def tesseract_layout_ocr(self, image: Image.Image) -> Tuple[str, float]:
        """Layout-aware Tesseract OCR"""
        img = np.array(image)
        config = "--oem 3 --psm 6"
        
        try:
            # Get structured data
            data = pytesseract.image_to_data(
                img, config=config, lang='eng',
                output_type=pytesseract.Output.DICT
            )
            
            # Group by lines with confidence filtering
            lines = {}
            confidences = []
            
            for i in range(len(data['text'])):
                conf = int(data['conf'][i])
                text = str(data['text'][i]).strip()
                
                if conf > 40 and text:
                    confidences.append(conf)
                    line_num = data['line_num'][i]
                    block_num = data['block_num'][i]
                    
                    key = f"{block_num}_{line_num}"
                    if key not in lines:
                        lines[key] = []
                    
                    lines[key].append({
                        'text': text,
                        'left': data['left'][i]
                    })
            
            # Sort and join
            result_lines = []
            for key in sorted(lines.keys()):
                words = sorted(lines[key], key=lambda x: x['left'])
                line_text = ' '.join([w['text'] for w in words])
                result_lines.append(line_text)
            
            full_text = '\n'.join(result_lines)
            avg_confidence = np.mean(confidences) if confidences else 0
            
            return self.clean_ocr_text(full_text), avg_confidence / 100.0
            
        except Exception as e:
            self.logger.error(f"Layout OCR failed: {e}")
            return "", 0.0

    def tesseract_multi_psm(self, image: Image.Image) -> Tuple[str, float]:
        """Try multiple PSM modes and return best result"""
        psm_modes = [6, 4, 3]
        results = []
        
        for psm in psm_modes:
            try:
                img = np.array(image)
                config = f"--oem 3 --psm {psm}"
                text = pytesseract.image_to_string(img, config=config, lang='eng')
                
                if text and len(text) > 50:
                    # Score based on readable content
                    lines = text.split('\n')
                    alphanum_ratio = sum(c.isalnum() for c in text) / max(len(text), 1)
                    
                    score = (
                        len(text) * 0.3 +
                        alphanum_ratio * 2000 +
                        len(lines) * 50
                    )
                    
                    results.append((text, psm, score))
                    
            except Exception as e:
                self.logger.warning(f"PSM {psm} failed: {e}")
                continue
        
        if results:
            best = max(results, key=lambda x: x[2])
            # Estimate confidence based on score
            confidence = min(0.9, best[2] / 3000)
            return self.clean_ocr_text(best[0]), confidence
        
        return "", 0.0

    def tesseract_raw_ocr(self, pil_img: Image.Image) -> Tuple[str, float]:
        """Raw Tesseract OCR with minimal preprocessing"""
        img = np.array(pil_img)
        
        # Convert to grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img
        
        # Only upscale if too small
        height, width = gray.shape
        if height < 1500:
            scale = 2000 / height
            new_width = int(width * scale)
            gray = cv2.resize(gray, (new_width, 2000), interpolation=cv2.INTER_CUBIC)
        
        # Direct OCR
        config = "--oem 3 --psm 6"
        try:
            text = pytesseract.image_to_string(gray, config=config, lang='eng')
            cleaned_text = self.clean_ocr_text(text)
            
            # Estimate confidence based on text quality
            if cleaned_text:
                alphanum_ratio = sum(c.isalnum() for c in cleaned_text) / len(cleaned_text)
                confidence = min(0.8, alphanum_ratio * 1.2)
            else:
                confidence = 0.0
                
            return cleaned_text, confidence
            
        except Exception as e:
            self.logger.error(f"Raw OCR failed: {e}")
            return "", 0.0

    def paddle_ocr_extract(self, pil_img: Image.Image) -> Tuple[str, float]:
        """PaddleOCR extraction"""
        if not self.paddle_ocr:
            return "", 0.0
        
        try:
            # Convert PIL to numpy array
            img = np.array(pil_img)
            
            # Run PaddleOCR
            result = self.paddle_ocr.ocr(img, cls=True)
            
            if not result or not result[0]:
                return "", 0.0
            
            # Extract text and confidence
            lines = []
            confidences = []
            
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0] if line[1] else ""
                    conf = line[1][1] if len(line[1]) > 1 else 0.0
                    
                    if text and conf > 0.5:
                        lines.append(text)
                        confidences.append(conf)
            
            full_text = '\n'.join(lines)
            avg_confidence = np.mean(confidences) if confidences else 0.0
            
            return self.clean_ocr_text(full_text), avg_confidence
            
        except Exception as e:
            self.logger.error(f"PaddleOCR failed: {e}")
            return "", 0.0

    def openai_vision_extract(self, pil_img: Image.Image) -> Tuple[str, float]:
        """OpenAI Vision API extraction"""
        if not self.openai_client:
            return "", 0.0
        
        try:
            # Convert image to base64
            buffer = io.BytesIO()
            pil_img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            
            # Call OpenAI Vision API
            response = self.openai_client.chat.completions.create(
                model="gpt-4-1106-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract all text from this invoice image. Return only the text content, preserving the layout and structure. Do not add any commentary or formatting."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_base64}"
                                }
                            }
                        ]
                    }
                ],
            )
            
            if response.choices and response.choices[0].message.content:
                text = response.choices[0].message.content.strip()
                # OpenAI Vision typically has high confidence
                confidence = 0.95 if text else 0.0
                return self.clean_ocr_text(text), confidence
            
            return "", 0.0
            
        except Exception as e:
            self.logger.error(f"OpenAI Vision failed: {e}")
            return "", 0.0

    def extract_text(self, pil_img: Image.Image) -> OCRResult:
        """
        Main OCR pipeline with fallback chain:
        1. Tesseract Layout-aware
        2. Tesseract Multi-PSM
        3. PaddleOCR (if available)
        4. OpenAI Vision (if available)
        5. Tesseract Raw (last resort)
        """
        import time
        
        start_time = time.time()
        
        # Method 1: Tesseract Layout-aware
        try:
            processed_img = self.preprocess_image(pil_img)
            text, confidence = self.tesseract_layout_ocr(processed_img)
            
            if text and len(text) > 100 and confidence > 0.6:
                processing_time = time.time() - start_time
                return OCRResult(
                    text=text,
                    method=OCRMethod.TESSERACT_LAYOUT,
                    confidence=confidence,
                    processing_time=processing_time,
                    metadata={"preprocessing": "full"}
                )
        except Exception as e:
            self.logger.warning(f"Layout OCR failed: {e}")
        
        # Method 2: Tesseract Multi-PSM
        try:
            processed_img = self.preprocess_image(pil_img)
            text, confidence = self.tesseract_multi_psm(processed_img)
            
            if text and len(text) > 100 and confidence > 0.5:
                processing_time = time.time() - start_time
                return OCRResult(
                    text=text,
                    method=OCRMethod.TESSERACT_MULTI_PSM,
                    confidence=confidence,
                    processing_time=processing_time,
                    metadata={"preprocessing": "full"}
                )
        except Exception as e:
            self.logger.warning(f"Multi-PSM OCR failed: {e}")
        
        # Method 3: PaddleOCR
        if PADDLE_AVAILABLE and self.paddle_ocr:
            try:
                text, confidence = self.paddle_ocr_extract(pil_img)
                
                if text and len(text) > 50 and confidence > 0.7:
                    processing_time = time.time() - start_time
                    return OCRResult(
                        text=text,
                        method=OCRMethod.PADDLE_OCR,
                        confidence=confidence,
                        processing_time=processing_time,
                        metadata={"preprocessing": "none"}
                    )
            except Exception as e:
                self.logger.warning(f"PaddleOCR failed: {e}")
        
        # Method 4: OpenAI Vision
        if OPENAI_AVAILABLE and self.openai_client:
            try:
                text, confidence = self.openai_vision_extract(pil_img)
                
                if text and len(text) > 50:
                    processing_time = time.time() - start_time
                    return OCRResult(
                        text=text,
                        method=OCRMethod.OPENAI_VISION,
                        confidence=confidence,
                        processing_time=processing_time,
                        metadata={"model": "gpt-4-1106-vision-preview"}
                    )
            except Exception as e:
                self.logger.warning(f"OpenAI Vision failed: {e}")
        
        # Method 5: Tesseract Raw (last resort)
        try:
            text, confidence = self.tesseract_raw_ocr(pil_img)
            processing_time = time.time() - start_time
            
            return OCRResult(
                text=text,
                method=OCRMethod.TESSERACT_RAW,
                confidence=confidence,
                processing_time=processing_time,
                error="All advanced methods failed" if not text else None,
                metadata={"preprocessing": "minimal"}
            )
        except Exception as e:
            processing_time = time.time() - start_time
            return OCRResult(
                text="",
                method=OCRMethod.TESSERACT_RAW,
                confidence=0.0,
                processing_time=processing_time,
                error=f"All OCR methods failed: {str(e)}"
            )

    def get_confidence_scores(self, pil_img: Image.Image) -> Dict[str, Any]:
        """Get detailed confidence statistics"""
        try:
            img = np.array(pil_img)
            data = pytesseract.image_to_data(
                img, lang='eng',
                output_type=pytesseract.Output.DICT
            )
            
            confidences = [
                int(conf) for conf in data['conf']
                if str(conf).isdigit() and int(conf) >= 0
            ]
            
            if confidences:
                return {
                    'mean_confidence': round(np.mean(confidences), 2),
                    'median_confidence': round(np.median(confidences), 2),
                    'min_confidence': min(confidences),
                    'max_confidence': max(confidences),
                    'low_confidence_words': sum(1 for c in confidences if c < 60),
                    'high_confidence_words': sum(1 for c in confidences if c > 80),
                    'total_words': len(confidences),
                    'confidence_distribution': {
                        'very_low': sum(1 for c in confidences if c < 40),
                        'low': sum(1 for c in confidences if 40 <= c < 60),
                        'medium': sum(1 for c in confidences if 60 <= c < 80),
                        'high': sum(1 for c in confidences if c >= 80)
                    }
                }
            
            return {'error': 'No confidence data available'}
            
        except Exception as e:
            return {'error': str(e)}
