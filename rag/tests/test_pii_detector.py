import pytest

from rag.pii_detector import PIIDetector


@pytest.fixture
def detector():
    return PIIDetector()


def test_ssn_masked(detector):
    text = "Patient SSN: 123-45-6789"
    result, found = detector.mask_phi(text)
    assert "123-45-6789" not in result
    assert found is True
    assert "[SSN REDACTED]" in result


def test_phone_masked(detector):
    text = "Call 555-867-5309 for appointments"
    result, found = detector.mask_phi(text)
    assert "555-867-5309" not in result
    assert found is True


def test_email_masked(detector):
    text = "Contact patient at john.doe@gmail.com"
    result, found = detector.mask_phi(text)
    assert "john.doe@gmail.com" not in result
    assert found is True


def test_no_phi_clean(detector):
    text = "Hypertension is defined as blood pressure above 130/80 mmHg per ACC/AHA guidelines."
    result, found = detector.mask_phi(text)
    assert found is False
    assert result == text


def test_zip_masked(detector):
    text = "Patient lives in ZIP code 12345"
    result, found = detector.mask_phi(text)
    assert "12345" not in result or "[ZIP REDACTED]" in result


def test_contains_phi_true(detector):
    assert detector.contains_phi("SSN: 123-45-6789") is True


def test_contains_phi_false(detector):
    assert (
        detector.contains_phi(
            "Normal clinical text about diabetes management guidelines."
        )
        is False
    )


def test_query_masking(detector):
    query = "What medication for patient John Smith with SSN 123-45-6789?"
    result = detector.mask_query(query)
    assert "123-45-6789" not in result
