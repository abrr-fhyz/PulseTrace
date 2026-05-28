import json
from unittest.mock import patch
import numpy as np
from lib import rag, store


def test_build_and_ask(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    rid = "test-run"
    d = store.run_dir(rid)
    posts = [
        {"id": "a", "text": "cats are great"},
        {"id": "b", "text": "dogs love walks"},
    ]
    (d / "posts.json").write_text(json.dumps(posts))

    fake_emb = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    with patch("lib.rag.embed_texts", return_value=fake_emb):
        rag.build_index(rid)

    qvec = np.array([[1.0, 0.0]], dtype=np.float32)
    with patch("lib.rag.embed_texts", return_value=qvec), \
         patch("lib.rag.chat_json", return_value={"answer": "cats", "citations": ["a"]}):
        res = rag.ask(rid, "tell me about cats", k=1)
    assert res["answer"] == "cats"
    assert "a" in res["retrieved"]


def test_ask_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    res = rag.ask("missing", "?")
    assert res["answer"].startswith("No data")
