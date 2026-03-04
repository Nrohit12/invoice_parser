"""
Enhanced Line Item Extractor with UOM Detection and Normalization
Extracts structured line items from invoice text with:
- Supplier name extraction and normalization
- Item description cleaning
- Manufacturer part number (MPN) detection
- Unit of Measure (UOM) detection and pack quantity parsing
- Price per base unit calculation
- Confidence scoring and escalation flags
"""

import re
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
from functools import lru_cache


class UOMType(str, Enum):
    """Standard Unit of Measure types"""
    EACH = "EA"          # Each (canonical base unit)
    CASE = "CS"          # Case
    PACK = "PK"          # Pack
    BOX = "BX"           # Box
    DOZEN = "DZ"         # Dozen
    PAIR = "PR"          # Pair
    SET = "SET"          # Set
    ROLL = "RL"          # Roll
    SHEET = "SH"         # Sheet
    METER = "M"          # Meter
    KILOGRAM = "KG"      # Kilogram
    LITER = "L"          # Liter
    UNKNOWN = "UNK"      # Unknown/Undetected


class LookupSource(str, Enum):
    """Source of UOM/pack quantity information"""
    EXTRACTED = "extracted"           # Found in original text
    PATTERN_MATCHED = "pattern_matched"  # Detected via regex patterns
    ONLINE_LOOKUP = "online_lookup"   # Retrieved from external source
    LLM_INFERRED = "llm_inferred"    # Inferred by LLM
    MANUAL = "manual"                # Requires manual review


class EscalationReason(str, Enum):
    """Reasons for escalating to human review"""
    MISSING_UOM = "missing_uom"
    AMBIGUOUS_PACK = "ambiguous_pack"
    LOW_CONFIDENCE = "low_confidence"
    CONFLICTING_DATA = "conflicting_data"
    UNKNOWN_SUPPLIER = "unknown_supplier"
    INVALID_PRICE = "invalid_price"


@dataclass
class PackQuantity:
    """Pack quantity information"""
    quantity: int
    unit: UOMType
    confidence: float
    source: LookupSource


@dataclass
class LineItemResult:
    """Complete line item extraction result"""
    # Core fields (as per requirements)
    supplier_name: Optional[str] = None
    item_description: Optional[str] = None
    manufacturer_part_number: Optional[str] = None
    original_uom: Optional[str] = None
    detected_pack_quantity: Optional[int] = None
    canonical_base_uom: str = "EA"  # Always normalize to EA
    price_per_base_unit: Optional[float] = None
    confidence_score: float = 0.0
    escalation_flag: bool = False
    
    # Additional metadata
    escalation_reasons: List[EscalationReason] = None
    raw_line: Optional[str] = None
    hsn_code: Optional[str] = None
    sac_code: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total_amount: Optional[float] = None
    taxable_amount: Optional[float] = None
    pack_info: Optional[PackQuantity] = None
    
    def __post_init__(self):
        if self.escalation_reasons is None:
            self.escalation_reasons = []


class LineItemExtractor:
    """Enhanced line item extractor with UOM detection"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Pre-compiled regex patterns for performance
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns for extraction"""
        
        # UOM patterns - matches various pack expressions
        self.uom_patterns = {
            # Pack expressions: "25/CS", "PK10", "1000 EA", "BX/100"
            'pack_slash': re.compile(r'(\d+)\s*/\s*([A-Z]{2,4})', re.IGNORECASE),
            'pack_prefix': re.compile(r'([A-Z]{2,4})\s*(\d+)', re.IGNORECASE),
            'pack_suffix': re.compile(r'(\d+)\s+([A-Z]{2,4})', re.IGNORECASE),
            'pack_per': re.compile(r'(\d+)\s*(?:per|/)\s*([A-Z]{2,4})', re.IGNORECASE),
            
            # Standard UOM: "EA", "CS", "PK", "BX", "DZ"
            'standard_uom': re.compile(r'\b(EA|CS|PK|BX|DZ|PR|SET|RL|SH|M|KG|L|EACH|CASE|PACK|BOX|DOZEN)\b', re.IGNORECASE),
            
            # Quantity expressions: "Qty: 100", "Quantity 25"
            'quantity': re.compile(r'(?:qty|quantity|quan)[:\s]*(\d+)', re.IGNORECASE),
        }
        
        # MPN patterns - manufacturer part numbers
        self.mpn_patterns = {
            'explicit_mpn': re.compile(r'(?:MPN|Part\s*#?|P/N|Model)[:\s]*([A-Z0-9\-_]+)', re.IGNORECASE),
            'embedded_code': re.compile(r'\b([A-Z]{2,4}\-?[0-9]{3,8}(?:\-[A-Z0-9]{1,4})?)\b'),
            'alphanumeric': re.compile(r'\b([A-Z0-9]{6,15})\b'),
        }
        
        # HSN/SAC codes
        self.hsn_pattern = re.compile(r'\b(\d{4,8})\b')
        
        # Amount patterns
        self.amount_patterns = {
            'currency': re.compile(r'(?:₹|INR|Rs\.?|USD|EUR|GBP)\s?([0-9,\.]+)'),
            'numeric': re.compile(r'\b(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\b'),
        }
        
        # Supplier normalization patterns
        self.supplier_patterns = {
            'ltd_variants': re.compile(r'\b(?:LTD|LIMITED|PVT|PRIVATE|CORP|CORPORATION|INC|INCORPORATED)\b', re.IGNORECASE),
            'common_suffixes': re.compile(r'\b(?:CO|COMPANY|ENTERPRISES|TRADERS|SUPPLIERS)\b', re.IGNORECASE),
        }

    @lru_cache(maxsize=1000)
    def normalize_uom(self, uom_text: str) -> UOMType:
        """Normalize UOM text to standard enum"""
        if not uom_text:
            return UOMType.UNKNOWN
        
        uom_upper = uom_text.upper().strip()
        
        # Direct mappings
        uom_map = {
            'EA': UOMType.EACH, 'EACH': UOMType.EACH,
            'CS': UOMType.CASE, 'CASE': UOMType.CASE,
            'PK': UOMType.PACK, 'PACK': UOMType.PACK, 'PKG': UOMType.PACK,
            'BX': UOMType.BOX, 'BOX': UOMType.BOX,
            'DZ': UOMType.DOZEN, 'DOZEN': UOMType.DOZEN, 'DOZ': UOMType.DOZEN,
            'PR': UOMType.PAIR, 'PAIR': UOMType.PAIR,
            'SET': UOMType.SET,
            'RL': UOMType.ROLL, 'ROLL': UOMType.ROLL,
            'SH': UOMType.SHEET, 'SHEET': UOMType.SHEET,
            'M': UOMType.METER, 'METER': UOMType.METER, 'MTR': UOMType.METER,
            'KG': UOMType.KILOGRAM, 'KILOGRAM': UOMType.KILOGRAM,
            'L': UOMType.LITER, 'LITER': UOMType.LITER, 'LITRE': UOMType.LITER,
        }
        
        return uom_map.get(uom_upper, UOMType.UNKNOWN)

    def get_pack_multiplier(self, uom: UOMType) -> int:
        """Get standard pack multiplier for UOM conversion to EA"""
        multipliers = {
            UOMType.EACH: 1,
            UOMType.PAIR: 2,
            UOMType.DOZEN: 12,
            UOMType.CASE: 1,      # Variable - needs lookup
            UOMType.PACK: 1,      # Variable - needs lookup
            UOMType.BOX: 1,       # Variable - needs lookup
            UOMType.SET: 1,       # Variable - needs lookup
            UOMType.ROLL: 1,      # Variable - needs lookup
            UOMType.SHEET: 1,
            UOMType.METER: 1,
            UOMType.KILOGRAM: 1,
            UOMType.LITER: 1,
        }
        return multipliers.get(uom, 1)

    def extract_pack_quantity(self, text: str) -> Optional[PackQuantity]:
        """Extract pack quantity from text patterns"""
        
        # Try pack/slash pattern: "25/CS"
        match = self.uom_patterns['pack_slash'].search(text)
        if match:
            qty = int(match.group(1))
            uom = self.normalize_uom(match.group(2))
            return PackQuantity(
                quantity=qty,
                unit=uom,
                confidence=0.9,
                source=LookupSource.PATTERN_MATCHED
            )
        
        # Try prefix pattern: "PK10"
        match = self.uom_patterns['pack_prefix'].search(text)
        if match:
            uom = self.normalize_uom(match.group(1))
            qty = int(match.group(2))
            return PackQuantity(
                quantity=qty,
                unit=uom,
                confidence=0.85,
                source=LookupSource.PATTERN_MATCHED
            )
        
        # Try suffix pattern: "1000 EA"
        match = self.uom_patterns['pack_suffix'].search(text)
        if match:
            qty = int(match.group(1))
            uom = self.normalize_uom(match.group(2))
            return PackQuantity(
                quantity=qty,
                unit=uom,
                confidence=0.8,
                source=LookupSource.PATTERN_MATCHED
            )
        
        # Try standard UOM without quantity
        match = self.uom_patterns['standard_uom'].search(text)
        if match:
            uom = self.normalize_uom(match.group(1))
            multiplier = self.get_pack_multiplier(uom)
            return PackQuantity(
                quantity=multiplier,
                unit=uom,
                confidence=0.7,
                source=LookupSource.PATTERN_MATCHED
            )
        
        return None

    def extract_mpn(self, text: str) -> Optional[str]:
        """Extract manufacturer part number"""
        
        # Try explicit MPN patterns first
        for pattern_name, pattern in self.mpn_patterns.items():
            match = pattern.search(text)
            if match:
                mpn = match.group(1).strip()
                # Validate MPN (basic checks)
                if len(mpn) >= 4 and not mpn.isdigit():
                    return mpn
        
        return None

    def extract_amounts(self, text: str) -> List[float]:
        """Extract all monetary amounts from text"""
        amounts = []
        
        # Try currency patterns first
        for match in self.amount_patterns['currency'].finditer(text):
            try:
                amount_str = match.group(1).replace(',', '')
                amounts.append(float(amount_str))
            except ValueError:
                continue
        
        # If no currency amounts, try numeric patterns
        if not amounts:
            for match in self.amount_patterns['numeric'].finditer(text):
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    # Filter reasonable amounts (avoid dates, codes, etc.)
                    if 0.01 <= amount <= 1000000:
                        amounts.append(amount)
                except ValueError:
                    continue
        
        return amounts

    def normalize_supplier_name(self, name: str) -> str:
        """Normalize supplier name for consistency"""
        if not name:
            return ""
        
        # Clean and normalize
        normalized = name.strip().upper()
        
        # Remove common legal suffixes for matching
        normalized = self.supplier_patterns['ltd_variants'].sub('', normalized)
        normalized = self.supplier_patterns['common_suffixes'].sub('', normalized)
        
        # Clean extra whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized

    def extract_supplier_name(self, text: str) -> Optional[str]:
        """
        Extract supplier name from invoice header text
        
        Looks for common patterns in the first 30 lines of the invoice:
        - Explicit labels: "Sold By:", "Vendor:", "Supplier:", "From:", "Bill From:"
        - Company name patterns with legal suffixes (LLC, Inc, Corp, Ltd, etc.)
        - Prominent header text that looks like a company name
        """
        lines = text.split('\n')[:30]  # Check first 30 lines (header area)
        header_text = '\n'.join(lines)
        
        # Pattern 1: Explicit supplier labels
        explicit_patterns = [
            re.compile(r'(?:sold\s*by|vendor|supplier|from|bill\s*from|ship\s*from)[:\s]+([A-Z][A-Za-z0-9\s&,.\-\']+?)(?:\n|$)', re.IGNORECASE),
            re.compile(r'(?:company|business\s*name)[:\s]+([A-Z][A-Za-z0-9\s&,.\-\']+?)(?:\n|$)', re.IGNORECASE),
        ]
        
        for pattern in explicit_patterns:
            match = pattern.search(header_text)
            if match:
                supplier = match.group(1).strip()
                # Clean trailing punctuation
                supplier = re.sub(r'[,.\s]+$', '', supplier)
                if len(supplier) > 3 and not supplier.isdigit():
                    return supplier.upper()
        
        # Pattern 2: Company name with legal suffix on its own line
        company_pattern = re.compile(
            r'^([A-Z][A-Z0-9\s&,.\-\']{3,50}(?:LLC|INC|CORP|LTD|LIMITED|CO\.?|COMPANY|ENTERPRISES|TRADING|DISTRIBUTORS|SUPPLIES|SUPPLY)\.?)\s*$',
            re.MULTILINE | re.IGNORECASE
        )
        match = company_pattern.search(header_text)
        if match:
            supplier = match.group(1).strip()
            return supplier.upper()
        
        # Pattern 3: Look for prominent company-like names in first few lines
        for i, line in enumerate(lines[:10]):
            line = line.strip()
            if not line or len(line) < 5:
                continue
            
            # Skip lines that look like addresses, dates, or invoice numbers
            if re.search(r'(?:invoice|bill|date|address|phone|fax|email|www\.|http|@|\d{5,})', line, re.IGNORECASE):
                continue
            
            # Skip lines that are mostly numbers
            if sum(c.isdigit() for c in line) > len(line) * 0.5:
                continue
            
            # Check if line looks like a company name
            if line[0].isupper() and len(line) > 5:
                # Must have some alphabetic content
                alpha_ratio = sum(c.isalpha() for c in line) / len(line)
                if alpha_ratio > 0.6:
                    # Check for company indicators
                    if any(suffix in line.upper() for suffix in [
                        'LLC', 'INC', 'CORP', 'LTD', 'CO.', 'CO ', 'COMPANY', 
                        'ENTERPRISES', 'TRADING', 'DISTRIBUTORS', 'SUPPLIES', 
                        'SUPPLY', 'INDUSTRIES', 'SOLUTIONS', 'SERVICES', 'GROUP'
                    ]):
                        return line.upper()
        
        # Pattern 4: First substantial capitalized line as fallback
        for line in lines[:5]:
            line = line.strip()
            if len(line) > 8 and line[0].isupper():
                # Must be mostly letters
                alpha_ratio = sum(c.isalpha() or c.isspace() for c in line) / len(line)
                if alpha_ratio > 0.7:
                    # Skip common non-supplier headers
                    skip_words = ['invoice', 'bill', 'receipt', 'order', 'purchase', 'tax', 'gst', 'date']
                    if not any(word in line.lower() for word in skip_words):
                        return line.upper()
        
        return None

    def calculate_confidence_score(self, item: LineItemResult) -> float:
        """Calculate overall confidence score for line item"""
        scores = []
        
        # Supplier name confidence
        if item.supplier_name:
            scores.append(0.8 if len(item.supplier_name) > 5 else 0.5)
        else:
            scores.append(0.0)
        
        # Description confidence
        if item.item_description:
            desc_len = len(item.item_description)
            if desc_len > 20:
                scores.append(0.9)
            elif desc_len > 10:
                scores.append(0.7)
            else:
                scores.append(0.5)
        else:
            scores.append(0.0)
        
        # UOM confidence
        if item.pack_info:
            scores.append(item.pack_info.confidence)
        elif item.original_uom:
            scores.append(0.6)
        else:
            scores.append(0.0)
        
        # Price confidence
        if item.price_per_base_unit and item.price_per_base_unit > 0:
            scores.append(0.8)
        elif item.unit_price and item.unit_price > 0:
            scores.append(0.6)
        else:
            scores.append(0.0)
        
        # MPN confidence (bonus)
        if item.manufacturer_part_number:
            scores.append(0.9)
        
        return sum(scores) / len(scores) if scores else 0.0

    def check_escalation_flags(self, item: LineItemResult) -> List[EscalationReason]:
        """Determine if line item needs escalation"""
        reasons = []
        
        # Missing UOM
        if not item.original_uom and not item.pack_info:
            reasons.append(EscalationReason.MISSING_UOM)
        
        # Low confidence
        if item.confidence_score < 0.5:
            reasons.append(EscalationReason.LOW_CONFIDENCE)
        
        # Missing critical data
        if not item.item_description:
            reasons.append(EscalationReason.LOW_CONFIDENCE)
        
        # Invalid price
        if item.price_per_base_unit and item.price_per_base_unit <= 0:
            reasons.append(EscalationReason.INVALID_PRICE)
        
        # Ambiguous pack quantity
        if item.pack_info and item.pack_info.confidence < 0.6:
            reasons.append(EscalationReason.AMBIGUOUS_PACK)
        
        return reasons

    def extract_line_items(self, text: str, supplier_name: Optional[str] = None) -> List[LineItemResult]:
        """
        Extract line items from invoice text
        
        Args:
            text: OCR extracted text
            supplier_name: Known supplier name (optional, will be auto-extracted if not provided)
            
        Returns:
            List of structured line items
        """
        items = []
        lines = text.split('\n')
        
        # Auto-extract supplier name if not provided
        if not supplier_name:
            supplier_name = self.extract_supplier_name(text)
            if supplier_name:
                self.logger.info(f"Auto-extracted supplier name: {supplier_name}")
        
        # Find table boundaries
        table_start = -1
        table_end = len(lines)
        
        for i, line in enumerate(lines):
            # Table header indicators
            if any(kw in line.lower() for kw in [
                's.no', 's no', 'sr.no', 'sr no', 'item', 'description', 
                'particulars', 'product', 'service'
            ]):
                table_start = i + 1
            
            # Table footer indicators
            if any(kw in line.lower() for kw in [
                'subtotal', 'sub total', 'total before tax', 'taxable amount',
                'cgst', 'sgst', 'igst', 'grand total'
            ]):
                table_end = i
                break
        
        if table_start == -1:
            table_start = 0
        
        # Extract line items
        item_number = 1
        for i in range(table_start, table_end):
            line = lines[i].strip()
            
            # Skip empty lines and headers
            if not line or len(line) < 5:
                continue
            
            if any(kw in line.lower() for kw in [
                's.no', 's no', 'item', 'description', 'qty', 'rate', 
                'amount', 'total', 'uom', 'unit'
            ]):
                continue
            
            # Check if line contains numbers (likely a line item)
            if re.search(r'\d+', line):
                item = self._extract_single_line_item(line, supplier_name)
                if item and item.item_description:
                    # Calculate confidence and escalation
                    item.confidence_score = self.calculate_confidence_score(item)
                    item.escalation_reasons = self.check_escalation_flags(item)
                    item.escalation_flag = len(item.escalation_reasons) > 0
                    
                    items.append(item)
                    item_number += 1
        
        return items

    def _extract_single_line_item(self, line: str, supplier_name: Optional[str] = None) -> Optional[LineItemResult]:
        """Extract data from a single line item"""
        
        item = LineItemResult()
        item.raw_line = line
        item.supplier_name = supplier_name
        
        # Split by multiple spaces or tabs
        parts = re.split(r'\s{2,}|\t', line)
        parts = [p.strip() for p in parts if p.strip()]
        
        # Extract description (longest non-numeric part)
        descriptions = []
        for part in parts:
            if len(part) > 5 and not re.match(r'^[\d,\.₹]+$', part):
                # Skip if it's likely a code or amount
                if not re.match(r'^[A-Z0-9\-/]+$', part) or len(part) > 15:
                    descriptions.append(part)
        
        if descriptions:
            item.item_description = descriptions[0]
        
        # Extract HSN/SAC code
        hsn_matches = self.hsn_pattern.findall(line)
        if hsn_matches:
            code = hsn_matches[0]
            if len(code) >= 6:
                item.sac_code = code
            else:
                item.hsn_code = code
        
        # Extract MPN
        item.manufacturer_part_number = self.extract_mpn(line)
        
        # Extract pack quantity and UOM
        item.pack_info = self.extract_pack_quantity(line)
        if item.pack_info:
            item.original_uom = item.pack_info.unit.value
            item.detected_pack_quantity = item.pack_info.quantity
        
        # Extract amounts
        amounts = self.extract_amounts(line)
        
        # Assign amounts to fields (heuristic based on position and value)
        if len(amounts) >= 3:
            # Likely: quantity, unit_price, total
            item.quantity = amounts[0]
            item.unit_price = amounts[1]
            item.total_amount = amounts[-1]
            if len(amounts) >= 4:
                item.taxable_amount = amounts[2]
        elif len(amounts) == 2:
            # Likely: quantity, total OR unit_price, total
            if amounts[0] < 1000 and amounts[1] > amounts[0]:
                item.quantity = amounts[0]
                item.total_amount = amounts[1]
            else:
                item.unit_price = amounts[0]
                item.total_amount = amounts[1]
        elif len(amounts) == 1:
            item.total_amount = amounts[0]
        
        # Calculate price per base unit
        if item.pack_info and item.unit_price:
            # Convert to per-EA pricing
            base_multiplier = item.pack_info.quantity
            item.price_per_base_unit = item.unit_price / base_multiplier
        elif item.unit_price:
            item.price_per_base_unit = item.unit_price
        elif item.total_amount and item.quantity and item.quantity > 0:
            item.price_per_base_unit = item.total_amount / item.quantity
        
        return item if item.item_description else None
