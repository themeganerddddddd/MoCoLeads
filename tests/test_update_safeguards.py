import pytest

from scripts.update import validate_historical_preservation


def test_historical_preservation_allows_additions():
    validate_historical_preservation([{"id": "old"}], [{"id": "old"}, {"id": "new"}])


def test_historical_preservation_blocks_record_removal():
    with pytest.raises(RuntimeError, match="blocked removal"):
        validate_historical_preservation([{"id": "old"}, {"id": "keep"}], [{"id": "keep"}])
