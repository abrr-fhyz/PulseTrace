from lib.dedup import simhash, hamming, near_dupe_keep


def test_simhash_stable_for_same_text():
    assert simhash("hello world foo bar") == simhash("hello world foo bar")


def test_simhash_ignores_case_and_extra_whitespace():
    assert simhash("Hello   World") == simhash("hello world")


def test_hamming_counts_differing_bits():
    assert hamming(0b1011, 0b1001) == 1
    assert hamming(0, 0) == 0


def test_keep_drops_exact_duplicates():
    texts = ["the quick brown fox", "the quick brown fox", "totally other content here"]
    keep = near_dupe_keep(texts)
    assert keep == [0, 2]


def test_keep_drops_near_duplicates():
    a = "breaking news the mayor resigned today after the scandal broke"
    b = "breaking news the mayor resigned today after the scandal broke out"
    c = "stock markets rallied sharply on strong tech earnings this quarter"
    keep = near_dupe_keep([a, b, c])
    assert 0 in keep
    assert 1 not in keep
    assert 2 in keep


def test_keep_all_when_distinct():
    texts = [
        "apples grow on trees in the orchard",
        "quantum computers use superposition states",
        "the river flooded the valley last spring",
    ]
    assert near_dupe_keep(texts) == [0, 1, 2]


def test_empty_returns_empty():
    assert near_dupe_keep([]) == []


def test_keeps_first_of_each_group_order_preserved():
    texts = ["alpha beta gamma delta", "zeta eta theta iota", "alpha beta gamma delta"]
    assert near_dupe_keep(texts) == [0, 1]
