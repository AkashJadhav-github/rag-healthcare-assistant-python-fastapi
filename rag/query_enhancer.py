"""
Healthcare query enhancement: medical synonym expansion, abbreviation resolution,
and query decomposition for multi-hop reasoning.
"""
import re
from typing import List, Tuple

MEDICAL_ABBREVIATIONS = {
    "MI": "myocardial infarction",
    "HTN": "hypertension",
    "DM": "diabetes mellitus",
    "CHF": "congestive heart failure",
    "COPD": "chronic obstructive pulmonary disease",
    "CAD": "coronary artery disease",
    "CKD": "chronic kidney disease",
    "UTI": "urinary tract infection",
    "DVT": "deep vein thrombosis",
    "PE": "pulmonary embolism",
    "CVA": "cerebrovascular accident",
    "TIA": "transient ischemic attack",
    "GERD": "gastroesophageal reflux disease",
    "IBD": "inflammatory bowel disease",
    "RA": "rheumatoid arthritis",
    "SLE": "systemic lupus erythematosus",
    "T2DM": "type 2 diabetes mellitus",
    "T1DM": "type 1 diabetes mellitus",
    "HbA1c": "glycated hemoglobin",
    "BMI": "body mass index",
    "BP": "blood pressure",
    "HR": "heart rate",
    "SOB": "shortness of breath",
    "DOE": "dyspnea on exertion",
    "CP": "chest pain",
    "N/V": "nausea and vomiting",
    "BUN": "blood urea nitrogen",
    "GFR": "glomerular filtration rate",
    "eGFR": "estimated glomerular filtration rate",
    "LFTs": "liver function tests",
    "CBC": "complete blood count",
    "WBC": "white blood cell count",
    "RBC": "red blood cell count",
    "Hgb": "hemoglobin",
    "Hct": "hematocrit",
    "PLT": "platelet count",
    "INR": "international normalized ratio",
    "PT": "prothrombin time",
    "PTT": "partial thromboplastin time",
    "ECG": "electrocardiogram",
    "EKG": "electrocardiogram",
    "EEG": "electroencephalogram",
    "MRI": "magnetic resonance imaging",
    "CT": "computed tomography",
    "US": "ultrasound",
    "CXR": "chest X-ray",
    "NSAID": "non-steroidal anti-inflammatory drug",
    "ACE": "angiotensin-converting enzyme",
    "ARB": "angiotensin receptor blocker",
    "BB": "beta-blocker",
    "CCB": "calcium channel blocker",
    "PPI": "proton pump inhibitor",
    "SSRI": "selective serotonin reuptake inhibitor",
    "HLD": "hyperlipidemia",
    "ACS": "acute coronary syndrome",
    "STEMI": "ST-elevation myocardial infarction",
    "NSTEMI": "non-ST-elevation myocardial infarction",
    "EF": "ejection fraction",
    "LVEF": "left ventricular ejection fraction",
    "AF": "atrial fibrillation",
    "A-fib": "atrial fibrillation",
    "VT": "ventricular tachycardia",
    "VF": "ventricular fibrillation",
    "ICU": "intensive care unit",
    "ED": "emergency department",
    "PO": "by mouth orally",
    "IV": "intravenous",
    "IM": "intramuscular",
    "SC": "subcutaneous",
    "PRN": "as needed",
    "QD": "once daily",
    "BID": "twice daily",
    "TID": "three times daily",
    "QID": "four times daily",
}

MEDICAL_SYNONYMS = {
    "heart attack": ["myocardial infarction", "MI", "cardiac arrest"],
    "stroke": ["cerebrovascular accident", "CVA", "brain attack"],
    "blood pressure": ["hypertension", "BP", "arterial pressure"],
    "sugar": ["glucose", "blood glucose", "glycemia"],
    "kidney": ["renal", "nephro"],
    "liver": ["hepatic", "hepato"],
    "lung": ["pulmonary", "respiratory", "bronchial"],
    "cancer": ["malignancy", "neoplasm", "carcinoma", "tumor"],
    "pain": ["algesia", "discomfort", "ache"],
    "fever": ["pyrexia", "hyperthermia", "elevated temperature"],
    "infection": ["sepsis", "bacteremia", "pathogenic"],
    "allergy": ["hypersensitivity", "allergic reaction", "anaphylaxis"],
}


class MedicalQueryEnhancer:
    def expand_abbreviations(self, query: str) -> str:
        words = query.split()
        expanded = []
        for word in words:
            clean = re.sub(r"[^\w/-]", "", word)
            if clean in MEDICAL_ABBREVIATIONS:
                expanded.append(f"{word} ({MEDICAL_ABBREVIATIONS[clean]})")
            else:
                expanded.append(word)
        return " ".join(expanded)

    def add_synonyms(self, query: str) -> str:
        q_lower = query.lower()
        additions = []
        for term, synonyms in MEDICAL_SYNONYMS.items():
            if term in q_lower:
                additions.extend(synonyms[:2])
        if additions:
            return f"{query} OR {' OR '.join(additions)}"
        return query

    def decompose_complex_query(self, query: str) -> List[str]:
        """Split compound questions for multi-hop retrieval."""
        sub_queries = [query]
        connectors = re.split(r"\s+(and|also|additionally|furthermore|what about)\s+", query, flags=re.IGNORECASE)
        if len(connectors) > 1:
            sub_queries = [q.strip() for q in connectors if len(q.strip()) > 10 and q.lower() not in ("and", "also", "additionally", "furthermore", "what about")]
        return sub_queries or [query]

    def enhance(self, query: str) -> Tuple[str, List[str]]:
        """Return (enhanced_query, sub_queries) for multi-hop retrieval."""
        expanded = self.expand_abbreviations(query)
        sub_queries = self.decompose_complex_query(expanded)
        return expanded, sub_queries


query_enhancer = MedicalQueryEnhancer()
