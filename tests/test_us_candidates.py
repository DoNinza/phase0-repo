from phase0.data.us_candidates import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES


def test_expanded_candidates_are_unique_tickers_and_include_default():
    assert len(EXPANDED_CANDIDATES) == len(set(EXPANDED_CANDIDATES))
    assert all(t.isalpha() and t.isupper() for t in EXPANDED_CANDIDATES)
    assert set(DEFAULT_CANDIDATES).issubset(set(EXPANDED_CANDIDATES))
