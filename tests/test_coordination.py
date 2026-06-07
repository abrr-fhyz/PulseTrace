from lib.coordination import group_near_dupes, detect_campaigns, Campaign


def _post(text, author, ts):
    return {"text": text, "author": author, "ts": ts}


def test_group_singletons_when_all_distinct():
    texts = [
        "apples grow on trees in the orchard",
        "quantum computers use superposition states",
        "the river flooded the valley last spring",
    ]
    groups = group_near_dupes(texts)
    assert sorted(len(g) for g in groups) == [1, 1, 1]


def test_group_collapses_near_identical():
    base = "vote no on prop 12 it will raise your taxes immediately for everyone"
    a = base
    b = base + " now"
    c = base + "!!"
    d = "unrelated cat video going viral; gardeners share spring planting hacks"
    groups = group_near_dupes([a, b, c, d])
    big = max(groups, key=len)
    assert sorted(big) == [0, 1, 2]
    assert [3] in groups


def test_empty_returns_empty():
    assert group_near_dupes([]) == []
    assert detect_campaigns([]) == []


def test_flags_campaign_across_distinct_authors():
    text = "the new policy is a disaster and everyone should be outraged about it"
    posts = [
        _post(text, "Alice", 1000),
        _post(text + " now", "Bob", 1100),
        _post(text + " today", "Carol", 1200),
        _post("a totally different unrelated message about gardening tips", "Dave", 5000),
    ]
    camps = detect_campaigns(posts, min_authors=3)
    assert len(camps) == 1
    c = camps[0]
    assert isinstance(c, Campaign)
    assert c.n_authors == 3
    assert c.n_copies == 3
    assert sorted(c.authors) == ["Alice", "Bob", "Carol"]


def test_single_author_spam_not_flagged():
    text = "buy my product it is the best product on the whole entire market today"
    posts = [_post(text, "Spammer", 1000 + i) for i in range(5)]
    assert detect_campaigns(posts, min_authors=3) == []


def test_tighter_time_window_scores_higher():
    text = "coordinated talking point about the upcoming local election results here"
    tight = [
        _post(text, "A", 1000),
        _post(text + " a", "B", 1010),
        _post(text + " b", "C", 1020),
    ]
    loose = [
        _post(text, "A", 1000),
        _post(text + " a", "B", 1000 + 86400),
        _post(text + " b", "C", 1000 + 2 * 86400),
    ]
    s_tight = detect_campaigns(tight, min_authors=3)[0].score
    s_loose = detect_campaigns(loose, min_authors=3)[0].score
    assert s_tight > s_loose


def test_campaigns_sorted_by_score_desc():
    t1 = "the mayor secretly approved the downtown stadium deal behind closed doors"
    t2 = "imported vaccines are causing a wave of mystery illnesses nationwide now"
    posts = [
        _post(t1, "A", 1000), _post(t1 + " x", "B", 1005), _post(t1 + " y", "C", 1010),
        _post(t2, "D", 1000), _post(t2 + " x", "E", 50000), _post(t2 + " y", "F", 90000),
    ]
    camps = detect_campaigns(posts, min_authors=3)
    assert len(camps) == 2
    assert camps[0].score >= camps[1].score
