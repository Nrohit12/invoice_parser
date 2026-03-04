"""
Agentic Lookup Service for Missing UOM and Pack Quantities
Attempts to resolve missing unit information through:
1. Online product database lookup
2. LLM-based inference with structured output
3. Confidence scoring and safe escalation
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
import json
import re
import httpx
from openai import OpenAI
import os

from .line_item_extractor import (
    UOMType, LookupSource, EscalationReason, PackQuantity, LineItemResult
)


class LookupConfidence(str, Enum):
    """Confidence levels for lookup results"""
    HIGH = "high"           # >0.8 - Very reliable
    MEDIUM = "medium"       # 0.5-0.8 - Moderately reliable  
    LOW = "low"            # 0.2-0.5 - Uncertain
    VERY_LOW = "very_low"  # <0.2 - Unreliable


@dataclass
class LookupResult:
    """Result from agentic lookup"""
    success: bool
    uom: Optional[UOMType] = None
    pack_quantity: Optional[int] = None
    confidence: float = 0.0
    confidence_level: LookupConfidence = LookupConfidence.VERY_LOW
    source: LookupSource = LookupSource.ONLINE_LOOKUP
    reasoning: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AgenticLookupService:
    """Service for resolving missing UOM and pack quantities"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Initialize OpenAI client
        self.openai_client = None
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.openai_client = OpenAI(api_key=api_key)
        else:
            self.logger.warning("OPENAI_API_KEY not found - LLM lookup disabled")
        
        # HTTP client for online lookups
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        # Confidence thresholds
        self.confidence_thresholds = {
            "escalate_below": 0.5,  # Escalate if confidence < 50%
            "accept_above": 0.7,    # Accept if confidence > 70%
        }

    async def lookup_uom_pack_quantity(
        self, 
        item: LineItemResult,
        enable_online_lookup: bool = True,
        enable_llm_lookup: bool = True
    ) -> LookupResult:
        """
        Main lookup method - tries multiple approaches
        
        Args:
            item: Line item needing UOM resolution
            enable_online_lookup: Whether to try online databases
            enable_llm_lookup: Whether to use LLM inference
            
        Returns:
            LookupResult with resolved UOM/pack info
        """
        
        # Skip if already has good UOM info
        if item.pack_info and item.pack_info.confidence > 0.7:
            return LookupResult(
                success=True,
                uom=item.pack_info.unit,
                pack_quantity=item.pack_info.quantity,
                confidence=item.pack_info.confidence,
                confidence_level=self._get_confidence_level(item.pack_info.confidence),
                source=item.pack_info.source,
                reasoning="Already has high-confidence UOM information"
            )
        
        # Try online lookup first (faster, more reliable)
        if enable_online_lookup:
            online_result = await self._online_product_lookup(item)
            if online_result.success and online_result.confidence > 0.6:
                return online_result
        
        # Try LLM inference as fallback
        if enable_llm_lookup and self.openai_client:
            llm_result = await self._llm_uom_inference(item)
            if llm_result.success:
                return llm_result
        
        # No successful lookup
        return LookupResult(
            success=False,
            confidence=0.0,
            error="All lookup methods failed or unavailable",
            reasoning="Could not resolve UOM through available methods"
        )

    async def _online_product_lookup(self, item: LineItemResult) -> LookupResult:
        """
        Attempt online product database lookup
        
        This is a placeholder for actual product database integration.
        In production, you would integrate with:
        - Supplier catalogs
        - Product databases (like Grainger, McMaster-Carr, etc.)
        - Industry-specific databases
        """
        
        try:
            # Extract search terms
            search_terms = self._extract_search_terms(item)
            
            if not search_terms:
                return LookupResult(
                    success=False,
                    error="No suitable search terms found",
                    source=LookupSource.ONLINE_LOOKUP
                )
            
            # Simulate online lookup (replace with actual API calls)
            lookup_result = await self._simulate_online_lookup(search_terms, item)
            
            return lookup_result
            
        except Exception as e:
            self.logger.error(f"Online lookup failed: {e}")
            return LookupResult(
                success=False,
                error=f"Online lookup error: {str(e)}",
                source=LookupSource.ONLINE_LOOKUP
            )

    def _extract_search_terms(self, item: LineItemResult) -> List[str]:
        """Extract searchable terms from line item"""
        terms = []
        
        # MPN is highest priority
        if item.manufacturer_part_number:
            terms.append(item.manufacturer_part_number)
        
        # Clean description for search
        if item.item_description:
            # Remove common noise words
            desc = item.item_description.lower()
            noise_words = ['invoice', 'bill', 'item', 'product', 'service']
            for word in noise_words:
                desc = desc.replace(word, '')
            
            # Extract meaningful terms (>3 chars, alphanumeric)
            words = re.findall(r'\b[a-z0-9]{3,}\b', desc)
            terms.extend(words[:5])  # Limit to top 5 terms
        
        # HSN/SAC codes can be useful
        if item.hsn_code:
            terms.append(item.hsn_code)
        if item.sac_code:
            terms.append(item.sac_code)
        
        return terms

    async def _simulate_online_lookup(self, search_terms: List[str], item: LineItemResult) -> LookupResult:
        """
        Simulate online product lookup
        
        In production, replace with actual API calls to:
        - Product databases
        - Supplier catalogs  
        - Industry databases
        """
        
        # Simulate lookup delay
        await asyncio.sleep(0.1)
        
        # Mock lookup logic based on common patterns
        description = (item.item_description or "").lower()
        
        # Pattern-based UOM inference (simplified simulation)
        if any(term in description for term in ['screw', 'bolt', 'nut', 'washer']):
            return LookupResult(
                success=True,
                uom=UOMType.EACH,
                pack_quantity=1,
                confidence=0.8,
                confidence_level=LookupConfidence.HIGH,
                source=LookupSource.ONLINE_LOOKUP,
                reasoning="Hardware items typically sold by each",
                metadata={"pattern_matched": "hardware"}
            )
        
        elif any(term in description for term in ['paper', 'sheet', 'form']):
            return LookupResult(
                success=True,
                uom=UOMType.PACK,
                pack_quantity=100,
                confidence=0.7,
                confidence_level=LookupConfidence.MEDIUM,
                source=LookupSource.ONLINE_LOOKUP,
                reasoning="Paper products often sold in packs of 100",
                metadata={"pattern_matched": "paper"}
            )
        
        elif any(term in description for term in ['box', 'case', 'carton']):
            return LookupResult(
                success=True,
                uom=UOMType.CASE,
                pack_quantity=24,
                confidence=0.6,
                confidence_level=LookupConfidence.MEDIUM,
                source=LookupSource.ONLINE_LOOKUP,
                reasoning="Box/case items often contain 24 units",
                metadata={"pattern_matched": "packaging"}
            )
        
        # No pattern matched
        return LookupResult(
            success=False,
            confidence=0.0,
            error="No matching patterns in product database",
            source=LookupSource.ONLINE_LOOKUP
        )

    async def _llm_uom_inference(self, item: LineItemResult) -> LookupResult:
        """Use LLM to infer UOM and pack quantity with structured output"""
        
        if not self.openai_client:
            return LookupResult(
                success=False,
                error="OpenAI client not available",
                source=LookupSource.LLM_INFERRED
            )
        
        try:
            # Create structured prompt
            prompt = self._create_llm_prompt(item)
            
            # Call OpenAI with structured output constraints
            response = self.openai_client.chat.completions.create(
                model="gpt-5-nano",
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                functions=[
                    {
                        "name": "resolve_uom",
                        "description": "Resolve unit of measure and pack quantity for a product",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "uom": {
                                    "type": "string",
                                    "enum": ["EA", "CS", "PK", "BX", "DZ", "PR", "SET", "RL", "SH", "M", "KG", "L", "UNK"],
                                    "description": "Standard unit of measure"
                                },
                                "pack_quantity": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 10000,
                                    "description": "Number of base units per pack"
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0.0,
                                    "maximum": 1.0,
                                    "description": "Confidence in the inference (0-1)"
                                },
                                "reasoning": {
                                    "type": "string",
                                    "description": "Brief explanation of the inference"
                                }
                            },
                            "required": ["uom", "pack_quantity", "confidence", "reasoning"]
                        }
                    }
                ],
                function_call={"name": "resolve_uom"}
            )
            
            # Parse structured response
            if response.choices and response.choices[0].message.function_call:
                function_args = json.loads(response.choices[0].message.function_call.arguments)
                
                uom_str = function_args.get("uom", "UNK")
                uom = UOMType(uom_str) if uom_str != "UNK" else UOMType.UNKNOWN
                
                pack_qty = function_args.get("pack_quantity", 1)
                confidence = function_args.get("confidence", 0.0)
                reasoning = function_args.get("reasoning", "")
                
                # Validate confidence bounds
                confidence = max(0.0, min(1.0, confidence))
                
                return LookupResult(
                    success=True,
                    uom=uom,
                    pack_quantity=pack_qty,
                    confidence=confidence,
                    confidence_level=self._get_confidence_level(confidence),
                    source=LookupSource.LLM_INFERRED,
                    reasoning=reasoning,
                    metadata={"model": "gpt-5-nano", "structured_output": True}
                )
            
            return LookupResult(
                success=False,
                error="No structured response from LLM",
                source=LookupSource.LLM_INFERRED
            )
            
        except Exception as e:
            self.logger.error(f"LLM inference failed: {e}")
            return LookupResult(
                success=False,
                error=f"LLM inference error: {str(e)}",
                source=LookupSource.LLM_INFERRED
            )

    def _create_llm_prompt(self, item: LineItemResult) -> str:
        """Create structured prompt for LLM UOM inference"""
        
        prompt_parts = [
            "Analyze this invoice line item and determine the unit of measure (UOM) and pack quantity:",
            "",
            f"Item Description: {item.item_description or 'N/A'}",
        ]
        
        if item.manufacturer_part_number:
            prompt_parts.append(f"Part Number: {item.manufacturer_part_number}")
        
        if item.supplier_name:
            prompt_parts.append(f"Supplier: {item.supplier_name}")
        
        if item.hsn_code or item.sac_code:
            prompt_parts.append(f"HSN/SAC Code: {item.hsn_code or item.sac_code}")
        
        if item.raw_line:
            prompt_parts.append(f"Raw Line: {item.raw_line}")
        
        prompt_parts.extend([
            "",
            "Instructions:",
            "1. Determine the most likely unit of measure (EA, CS, PK, BX, DZ, etc.)",
            "2. Estimate pack quantity (how many base units per pack)",
            "3. Provide confidence score (0.0-1.0) based on available information",
            "4. If uncertain, use lower confidence and explain why",
            "5. Do NOT hallucinate - if information is insufficient, use low confidence",
            "",
            "Common patterns:",
            "- Hardware (screws, bolts): Usually EA (each)",
            "- Paper products: Often PK (pack) of 100-500 sheets",
            "- Office supplies: Varies widely, check description carefully",
            "- Food items: Often CS (case) with various pack sizes",
        ])
        
        return "\n".join(prompt_parts)

    def _get_system_prompt(self) -> str:
        """System prompt for LLM UOM inference"""
        return """You are an expert in product catalog analysis and unit of measure standardization. 
Your task is to analyze invoice line items and determine the correct unit of measure (UOM) and pack quantity.

Key principles:
1. Be conservative - use lower confidence when uncertain
2. Never hallucinate information not present in the input
3. Consider industry standards for similar products
4. Explain your reasoning clearly
5. Use "UNK" for unknown UOM if truly uncertain

Standard UOM codes:
- EA: Each (individual items)
- CS: Case (multiple items in a case)
- PK: Pack (packaged quantities)
- BX: Box (boxed quantities)  
- DZ: Dozen (12 items)
- PR: Pair (2 items)
- SET: Set (grouped items)
- RL: Roll (rolled materials)
- SH: Sheet (flat materials)
- M: Meter (length)
- KG: Kilogram (weight)
- L: Liter (volume)"""

    def _get_confidence_level(self, confidence: float) -> LookupConfidence:
        """Convert numeric confidence to level"""
        if confidence >= 0.8:
            return LookupConfidence.HIGH
        elif confidence >= 0.5:
            return LookupConfidence.MEDIUM
        elif confidence >= 0.2:
            return LookupConfidence.LOW
        else:
            return LookupConfidence.VERY_LOW

    def should_escalate(self, result: LookupResult) -> bool:
        """Determine if lookup result should be escalated"""
        return (
            not result.success or 
            result.confidence < self.confidence_thresholds["escalate_below"]
        )

    async def enhance_line_item(self, item: LineItemResult) -> LineItemResult:
        """
        Enhance line item with agentic lookup if needed
        
        Args:
            item: Original line item
            
        Returns:
            Enhanced line item with resolved UOM info
        """
        
        # Skip if already has high-confidence UOM
        if item.pack_info and item.pack_info.confidence > 0.7:
            return item
        
        # Perform lookup
        lookup_result = await self.lookup_uom_pack_quantity(item)
        
        # Apply results if successful
        if lookup_result.success and lookup_result.confidence > 0.3:
            # Update pack info
            item.pack_info = PackQuantity(
                quantity=lookup_result.pack_quantity,
                unit=lookup_result.uom,
                confidence=lookup_result.confidence,
                source=lookup_result.source
            )
            
            # Update related fields
            item.original_uom = lookup_result.uom.value
            item.detected_pack_quantity = lookup_result.pack_quantity
            
            # Recalculate price per base unit if possible
            if item.unit_price and lookup_result.pack_quantity:
                item.price_per_base_unit = item.unit_price / lookup_result.pack_quantity
        
        # Add escalation flag if needed
        if self.should_escalate(lookup_result):
            if EscalationReason.MISSING_UOM not in item.escalation_reasons:
                item.escalation_reasons.append(EscalationReason.MISSING_UOM)
            item.escalation_flag = True
        
        return item

    async def close(self):
        """Clean up resources"""
        if hasattr(self, 'http_client'):
            await self.http_client.aclose()
