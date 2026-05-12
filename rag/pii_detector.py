"""
PII detection and masking for HIPAA compliance.
Detects and redacts PHI (Protected Health Information) from responses.
"""
import re
from typing import Tuple


PHI_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REDACTED]"),
    (re.compile(r"\b\d{10}\b"), "[MRN REDACTED]"),
    (re.compile(r"\b[A-Z]{2}\d{6}\b"), "[MRN REDACTED]"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "[DATE REDACTED]"),
    (re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b", re.IGNORECASE), "[DATE REDACTED]"),
    (re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"), None),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL REDACTED]"),
    (re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)\b"), "[ADDRESS REDACTED]"),
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), "[ZIP REDACTED]"),
    (re.compile(r"\b(?:IP|ip)\s*:?\s*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[IP REDACTED]"),
    (re.compile(r"\b(?:DOB|Date of Birth|dob)\s*:?\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", re.IGNORECASE), "[DOB REDACTED]"),
    (re.compile(r"\bNPI\s*:?\s*\d{10}\b", re.IGNORECASE), "[NPI REDACTED]"),
    (re.compile(r"\b(?:DEA|Lic\.?)\s*#?\s*[A-Z]{2}\d{7}\b", re.IGNORECASE), "[LICENSE REDACTED]"),
]

MEDICAL_NAME_CONTEXT = re.compile(
    r"\b(?:Patient|patient|Dr\.?|Doctor|physician|nurse|Mr\.?|Mrs\.?|Ms\.?|Miss)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)


class PIIDetector:
    def mask_phi(self, text: str) -> Tuple[str, bool]:
        """Mask PHI in text. Returns (masked_text, phi_found)."""
        phi_found = False
        result = text

        for pattern, replacement in PHI_PATTERNS:
            if replacement is None:
                continue
            if pattern.search(result):
                phi_found = True
                result = pattern.sub(replacement, result)

        for match in MEDICAL_NAME_CONTEXT.finditer(text):
            phi_found = True
            result = result.replace(match.group(1), "[NAME REDACTED]")

        return result, phi_found

    def contains_phi(self, text: str) -> bool:
        for pattern, _ in PHI_PATTERNS:
            if pattern.search(text):
                return True
        if MEDICAL_NAME_CONTEXT.search(text):
            return True
        return False

    def mask_query(self, query: str) -> str:
        """Light masking on query to prevent PHI leakage to LLM."""
        result, _ = self.mask_phi(query)
        return result


pii_detector = PIIDetector()
