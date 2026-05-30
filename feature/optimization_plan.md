                                                                                                                 
  1. Speculative seed fetch — kick off _fetch_all(seeds) before LLM returns next-query decision. Pipeline iter N+1 fetch w/ iter N labeling. ~30% wall time gone.                                                                             
  2. Embed-as-you-fetch — stream posts into embedder in batches of 32 while connector still scrolling. Don't wait forfull corpus. asyncio.Queue between fetch+embed.                                                                     
  3. Cache embeddings on disk by text-hash — sha1(text) -> vec in sqlite/parquet. Repeat topics = zero embed cost.Already partial in embed.py cache; persist across runs.                                                               
  4. Incremental clustering — don't re-cluster full corpus every iter. Use HDBSCAN on new posts only, assign to nearest existing centroid w/ cosine threshold; re-cluster from scratch only every 3 iters or on entropy jump.
  5. Cluster→label in parallel — currently sequential for cid in cents. ThreadPoolExecutor(8) over clusters. Label + stance per cluster independent. 4-8x label stage.         
  6. Stance batching across clusters — one mega-prompt: "score these 64 posts, here is theme per post." One LLM call vs 8. Token-cheap w/ flash-lite.                          
  7. Smaller embedding for clustering, big for RAG — gemini-embedding-001 @ 768-dim for clustering (faster faiss, less RAM), full 3072 only for RAG index. Matryoshka truncation = free.
  8. Skip embed for near-dupes — minhash/simhash on raw text first. FB OCR floods near-dupes. Dedupe before embed = 30-50% fewer vectors.                                     
  9. Warm Playwright — keep one Chromium alive across iters as singleton, not new ctx per fetch_many. Already single-session per iter; extend to run-lifetime. Save 2-3s/iter cold start.
  10. Prefetch screenshots in parallel w/ OCR — current: scroll→shot→OCR→scroll→shot→OCR. Better: scroll loop captures all PNGs first, then asyncio.gather Gemini Vision calls. Network-bound OCR parallelizes well.
  11. Early-stop on entropy plateau — already have EPS=0.05 check. Add: stop also when new posts in iter have >0.9 mean cosine to existing centroids (corpus saturating). Skip a whole iter.
  12. LLM call coalescing — seed + next-query LLM share context. Pass cluster summary once, ask "decide stop AND propose queries AND name underrepresented angle" in one call.    
  13. Streaming JSON parse — Gemini supports stream. For long stance batches, parse {"items":[...]} array as it arrives,score in flight. Hides latency behind first-byte.        
  14. GPU embed if avail — fallback to local bge-small on CUDA if nvidia-smi works. Free + faster than Gemini network round-trip for 500 posts. You have 3080 plan doc.         
  15. HTTP/2 + connection pool — single httpx.AsyncClient for all Gemini calls. Reuse TLS. Current openai-sdk opensfresh conn per call.                                      
                                                                                                                        
  My pick: cheap, big wins                                  
                                                                                                                        
  #5 (parallel label) + #6 (stance batch) + #8 (dedupe) + #11 (early stop). Likely 3-4x speedup, <100 LoC total. Want me
   to implement