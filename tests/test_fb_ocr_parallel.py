from pathlib import Path
from unittest.mock import patch

from lib.connectors import facebook as fb


def test_ocr_many_maps_each_shot_once():
    shots = [Path(f"s{i}.png") for i in range(5)]
    calls = []

    def fake_ocr(shot, key):
        calls.append(shot)
        return [{"post_content": f"text for {shot.name} " + "x" * 40}]

    with patch.object(fb, "_ocr", side_effect=fake_ocr):
        out = fb._ocr_many(shots, key="k", workers=4)

    assert set(out) == set(shots)
    assert sorted(calls) == sorted(shots)
    assert out[shots[0]][0]["post_content"].startswith("text for s0.png")


def test_ocr_many_empty():
    assert fb._ocr_many([], key="k") == {}


def test_shots_to_posts_uses_precomputed_and_dedupes():
    shots = [Path("a.png"), Path("b.png")]
    body = "a genuinely unique facebook post body that is well over thirty chars"
    ocr = {
        shots[0]: [{"post_content": body}],
        shots[1]: [{"post_content": body}],  # duplicate sig -> dropped
    }
    seen: set[str] = set()
    posts = fb._shots_to_posts("q", shots, ocr, seen, limit=30)
    assert len(posts) == 1
    assert posts[0].text == body


def test_shots_to_posts_respects_limit():
    shots = [Path("a.png")]
    ocr = {shots[0]: [{"post_content": f"distinct post number {i} " + "y" * 40}
                      for i in range(5)]}
    posts = fb._shots_to_posts("q", shots, ocr, set(), limit=3)
    assert len(posts) == 3


def test_shots_to_posts_skips_short_bodies():
    shots = [Path("a.png")]
    ocr = {shots[0]: [{"post_content": "too short"}]}
    assert fb._shots_to_posts("q", shots, ocr, set(), limit=30) == []
