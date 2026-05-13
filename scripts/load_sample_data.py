"""
Load synthetic/public-domain healthcare sample documents into the system.
Run: python scripts/load_sample_data.py
"""
import asyncio
import httpx
import os

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@healthcare.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@12345!")

SAMPLE_DOCS = [
    ("sample_data/clinical_guidelines.txt", "Clinical Practice Guidelines — Hypertension 2024", "clinical_guideline"),
    ("sample_data/medication_interactions.txt", "Common Drug Interactions Reference", "medication_db"),
    ("sample_data/medical_glossary.txt", "Medical Terminology Glossary", "medical_glossary"),
    ("sample_data/hl7_fhir_reference.txt", "HL7 FHIR R4 Quick Reference", "hl7_standard"),
    ("sample_data/diabetes_management.txt", "Diabetes Management Protocol — ADA 2024", "clinical_guideline"),
]


async def main():
    async with httpx.AsyncClient(base_url=API_BASE, timeout=300) as client:
        print("Logging in...")
        r = await client.post("/auth/login", data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        r.raise_for_status()
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        for file_path, title, category in SAMPLE_DOCS:
            if not os.path.exists(file_path):
                print(f"  Skipping missing file: {file_path}")
                continue
            print(f"  Ingesting: {title}")
            with open(file_path, "rb") as f:
                r = await client.post(
                    "/knowledge/ingest",
                    files={"file": (os.path.basename(file_path), f, "text/plain")},
                    data={"title": title, "category": category},
                    headers=headers,
                )
            if r.status_code in (200, 202):
                print(f"    ✓ Queued: {r.json()['document_id']}")
            else:
                print(f"    ✗ Failed: {r.status_code} {r.text}")

        print("\nAll sample documents submitted for indexing.")
        print("Check status with: GET /api/v1/health")


if __name__ == "__main__":
    asyncio.run(main())
