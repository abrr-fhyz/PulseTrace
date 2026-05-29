"""Stage 10: topic graph (Cytoscape nodes + cosine-similarity edges).

Backs README use-case "Topic Graph — clusters connected by similarity".
Mirrors the same math as `server.py:/graph` so the JSON in `results/` matches
exactly what the webapp would render live.
"""
from __future__ import annotations
import numpy as np

import pytest

from .conftest import write_stage_artifact


def _graph_from_clusters(clusters: list[dict], threshold: float = 0.5) -> dict:
    nodes = [{"data": {"id": str(c["id"]), "label": c["label"],
                       "size": len(c["members"]),
                       "sentiment": c["sentiment"]}} for c in clusters]
    edges = []
    for i, a in enumerate(clusters):
        va = np.array(a["centroid"])
        for b in clusters[i + 1:]:
            vb = np.array(b["centroid"])
            denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
            sim = float(va @ vb) / denom
            if sim > threshold:
                edges.append({"data": {
                    "id": f"{a['id']}-{b['id']}",
                    "source": str(a["id"]),
                    "target": str(b["id"]),
                    "weight": round(sim, 4),
                }})
    return {"nodes": nodes, "edges": edges}


def _stub_cluster(cid: int, centroid: list[float], members: list[str],
                  label: str = "x") -> dict:
    return {
        "id": cid, "label": label,
        "centroid": centroid, "members": members,
        "sentiment": {"pos": 0.3, "neu": 0.4, "neg": 0.3},
    }


def test_graph_no_edges_when_clusters_orthogonal():
    clusters = [
        _stub_cluster(0, [1.0, 0.0, 0.0], ["m1"]),
        _stub_cluster(1, [0.0, 1.0, 0.0], ["m2"]),
        _stub_cluster(2, [0.0, 0.0, 1.0], ["m3"]),
    ]
    g = _graph_from_clusters(clusters)
    assert len(g["nodes"]) == 3
    assert g["edges"] == []


def test_graph_links_similar_clusters_only():
    clusters = [
        _stub_cluster(0, [1.0, 0.0], ["m1", "m2"], "A"),
        _stub_cluster(1, [0.9, 0.1], ["m3", "m4"], "near-A"),
        _stub_cluster(2, [0.0, 1.0], ["m5"], "B"),
    ]
    g = _graph_from_clusters(clusters, threshold=0.5)
    edge_ids = sorted(e["data"]["id"] for e in g["edges"])
    assert edge_ids == ["0-1"], f"unexpected edges: {edge_ids}"
    assert g["edges"][0]["data"]["weight"] > 0.5

    write_stage_artifact("stage10_graph.json", g)


def test_node_payload_has_required_fields():
    clusters = [_stub_cluster(0, [1.0, 0.0], ["a", "b", "c"], "Lbl")]
    g = _graph_from_clusters(clusters)
    n = g["nodes"][0]["data"]
    assert set(n) >= {"id", "label", "size", "sentiment"}
    assert n["size"] == 3
    assert set(n["sentiment"]) >= {"pos", "neu", "neg"}
