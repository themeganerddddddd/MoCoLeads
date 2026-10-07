from pipeline.company_matcher import is_possible_moco_address, match_company, normalize_name


def test_company_alias_normalization_ignores_punctuation_and_suffixes():
    assert normalize_name("LOCKHEED-MARTIN Corp.") == normalize_name("Lockheed Martin Corporation")


def test_uei_precedes_name_matching():
    companies = [{"company_id": "x", "canonical_name": "Example", "legal_name": "Example LLC", "aliases_list": [], "uei": "ABC123"}]
    company, method = match_company({"recipient_name": "Wrong Name", "recipient_uei": "abc123"}, companies)
    assert company["company_id"] == "x"
    assert method == "uei"


def test_montgomery_county_address_is_candidate_not_verified():
    assert is_possible_moco_address("123 Main Street, Rockville, MD 20850")
    assert not is_possible_moco_address("123 Main Street, Arlington, VA 22201")
