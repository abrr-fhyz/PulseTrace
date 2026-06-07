● Mapped all 15 vs code.

  Implemented ✅

  ┌─────┬────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────┐
  │  #  │                  Opt                   │                                   Where                                   │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 3   │ Disk embed cache (sha1→vec, cross-run) │ embed.py:20 CACHE_PATH jsonl, _key sha1                                   │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 5   │ Parallel cluster→label                 │ agent.py:204 ThreadPoolExecutor(8) over cids                              │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 6   │ Stance batch across clusters           │ stance.py:41 score_mixed + cluster_sentiments chunked                     │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 8   │ Skip embed near-dupes                  │ dedup.py simhash + agent.py:159 near_dupe_keep before embed               │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 9   │ Warm Playwright (partial)              │ facebook.py:246 supports_batch, single session per iter via fetch_many    │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 10  │ Parallel OCR                           │ facebook.py:205 _ocr_many — capture all PNGs, then ThreadPoolExecutor OCR │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ 11  │ Early-stop saturation                  │ cluster.py:36 saturation + agent.py:251 sat>=SAT_EPS                      │
  ├─────┼────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ —   │ Skip-repeat queries                    │ agent.py:130 fetched set, prune already-fetched                           │
  └─────┴────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────┘

  Plus parallel multi-source fetch (agent.py:104).

  NOT implemented ❌

  ┌─────┬────────────────────────────────┬─────────────────────────────────────────────────────────────────────────┬──────────┐
  │  #  │              Opt               │                                   Gap                                   │  Effort  │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 1   │ Speculative seed fetch         │ iter N+1 fetch still blocks on iter N labeling. No prefetch pipeline    │ med      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 2   │ Embed-as-you-fetch stream      │ embed_texts waits full corpus. No asyncio.Queue fetch→embed             │ med      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 4   │ Incremental clustering         │ cluster_embeddings(emb) re-clusters FULL corpus every iter. No          │ med-high │
  │     │                                │ nearest-centroid assign + periodic full recluster                       │          │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 7   │ Matryoshka dims (768 cluster / │ single embed dim everywhere. Free truncation unused                     │ low      │
  │     │  3072 RAG)                     │                                                                         │          │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 12  │ LLM coalesce seed+next-query   │ _llm_seed/_llm_next separate calls. Could merge stop+queries+gap into 1 │ low      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 13  │ Streaming JSON parse           │ chat_json blocking. No stream of {"items":[...]}                        │ med      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 14  │ Local GPU embed (bge on CUDA)  │ network-only providers. You have 3080 plan doc. Free + faster for 500   │ med      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 13  │ Streaming JSON parse           │ chat_json blocking. No stream of {"items":[...]}                        │ med      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 14  │ Local GPU embed (bge on CUDA)  │ network-only providers. You have 3080 plan doc. Free + faster for 500   │ med      │
  │     │                                │ nearest-centroid assign + periodic full recluster                       │          │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 7   │ Matryoshka dims (768 cluster / │ single embed dim everywhere. Free truncation unused                     │ low      │
  │     │  3072 RAG)                     │                                                                         │          │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 12  │ LLM coalesce seed+next-query   │ _llm_seed/_llm_next separate calls. Could merge stop+queries+gap into 1 │ low      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 13  │ Streaming JSON parse           │ chat_json blocking. No stream of {"items":[...]}                        │ med      │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 14  │ Local GPU embed (bge on CUDA)  │ network-only providers. You have 3080 plan doc. Free + faster for 500   │ med      │
  │     │                                │ posts                                                                   │          │
  ├─────┼────────────────────────────────┼─────────────────────────────────────────────────────────────────────────┼──────────┤
  │ 15  │ HTTP/2 conn pool               │ embed.py:61 new OpenAI() client per call, fresh TLS each time           │ low      │
  └─────┴────────────────────────────────┴─────────────────────────────────────────────────────────────────────────┴──────────┘

  Recommend next

  Best ratio leftover:
  - #15 — reuse one client/httpx.AsyncClient, kill TLS handshake per call. ~10 LoC.
  - #12 — merge seed+next LLM, one fewer roundtrip per iter. ~20 LoC.
  - #7 — truncate embed to 768 for cluster, keep full for RAG. faster faiss + less RAM. ~15 LoC.
  - #4 — biggest compute win on long runs (no full recluster each iter) but riskier.

  Original plan picked #5+#6+#8+#11 — all done. The "cheap big wins" batch shipped. Remaining are the harder streaming/pipeline
  ones (#1/#2/#4) plus three low-effort stragglers (#7/#12/#15).

  Want me implement #15+#12+#7 (cheap, ~45 LoC, no risk)?