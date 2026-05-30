              
  1. Live Influence Graph — Cytoscape edges = author→author retweet/quote/comment chains, node size = influence score, color = stance. Click node → posts  
  panel. Already have influence.py + Cytoscape loaded; just wire edges from raw.parent_id.                                                                 
  2. Narrative Drift Timeline — Re-cluster every iter, track cluster→cluster centroid cosine over time. Visualize as Sankey: "cluster A split into B+C at
  iter 3." Shows the agent discovering angles live.                                                                                                        
  3. Contradiction Detector — Per cluster, LLM finds 2 posts with opposing claims, surfaces as "⚠ Disputed: X says A, Y says B." One extra chat_json call
  per cluster. Huge wow factor for misinfo angle.                                                                                                          
  4. Auto-Generated Briefing PDF — End of run → 1-page exec summary (topic, top clusters w/ sentiment bars, top 3 quotes per cluster w/ citations,         
  screenshot thumbnails). weasyprint or print-CSS. Judges love takeaways.
  5. "Ask the Crowd" Live Mode — User types question mid-run → RAG answers from current partial corpus + streams new answer each iter as more posts land.  
  SSE already there.                                        
  6. Stance-over-Time chart — X = iter, Y = pos/neu/neg ratio per cluster, stacked area. Shows narrative shifts. Trivial w/ existing Chart.js +            
  cluster_meta.                                             
                                                                                                                                                           
  Differentiators (FB-specific, harder)                     
                                                                                                                                                           
  7. Account Authenticity Score — Per author: post velocity, account age (if scrapeable), follower/following skew → "likely bot" flag. Even rough heuristic
   = demo gold.                                                                                                                                            
  8. Echo Chamber Map — Cluster authors by which clusters they post in. Authors only in one cluster = echo chamber resident. Force-directed graph.
  9. Cross-Source Convergence — Same claim appearing on FB + Reddit + X = "verified by N sources" badge. Cosine sim across source embeddings, threshold.   
  10. One-Click Counter-Narrative — For any cluster, LLM drafts a fact-check/counter-post using cited evidence from other clusters. Useful for
  journalists/mods angle.                                                                                                                                  
                                                                                                                                                           
  Cheap polish wins                                                                                                                                        
                                                                                                                                                           
  11. Word cloud per cluster (top TF-IDF terms)                                                                                                            
  12. Export run as shareable link (run dir → tarball → upload to /tmp + signed URL)                                                                       
  13. Dark mode toggle (CSS vars)                           
  14. "Replay run" — scrub iter slider, dashboard rewinds                                                                                                  
                                                            