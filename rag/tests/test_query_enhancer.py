import pytest
from rag.query_enhancer import MedicalQueryEnhancer


@pytest.fixture
def enhancer():
    return MedicalQueryEnhancer()


def test_abbreviation_expansion(enhancer):
    result = enhancer.expand_abbreviations("Patient has HTN and T2DM")
    assert "hypertension" in result.lower() or "HTN" in result
    assert "diabetes" in result.lower() or "T2DM" in result


def test_synonym_addition(enhancer):
    result = enhancer.add_synonyms("treatment for heart attack patients")
    assert "myocardial infarction" in result.lower() or "MI" in result


def test_complex_query_decomposition(enhancer):
    query = "What is hypertension and what is the treatment for diabetes?"
    sub_queries = enhancer.decompose_complex_query(query)
    assert len(sub_queries) >= 1


def test_enhance_returns_tuple(enhancer):
    enhanced, sub_queries = enhancer.enhance("What is MI and how is it treated?")
    assert isinstance(enhanced, str)
    assert isinstance(sub_queries, list)
    assert len(sub_queries) >= 1


def test_no_abbreviations_unchanged(enhancer):
    query = "What are clinical guidelines for blood pressure management?"
    result = enhancer.expand_abbreviations(query)
    assert "blood pressure" in result
