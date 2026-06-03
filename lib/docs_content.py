"""Static pitch deck + tech doc content. Edit here for changes."""
from __future__ import annotations

TEAM = {
    "name": "Boulder Of Ephyra",
    "members": [
        {"name": "Abrar Fahyaz", "role": "Team Lead / Architect", "email": "fahyaz.abrar@gmail.com"},
        {"name": "Nafis Shyan",  "role": "Engineer / AI Systems", "email": "shyannafis@gmail.com"},
    ],
}

PITCH = {
    "tagline": "Agentic sentiment intelligence for the open web.",
    "problem": (
        "Brands, journalists, and analysts need to know how the public actually "
        "feels about a topic right now — across Facebook, Reddit, Hacker News, X, "
        "and Instagram. Existing tools either lock data behind enterprise pricing, "
        "give shallow keyword counts, or break the moment a platform changes its DOM."
    ),
    "solution": (
        "PulseTrace runs an LLM-driven agent loop: it fetches multi-source posts, "
        "embeds and clusters them, labels each cluster, scores stance and influence, "
        "and expands queries until topical coverage converges. Output: a topic graph, "
        "sentiment timeline, and a RAG Q&A surface with cited screenshots."
    ),
    "why_now": [
        "Frontier LLMs now cheap enough for per-post labeling at scale.",
        "Vision OCR (Gemini 2.5 Flash) finally beats DOM scraping on hostile sites like Facebook.",
        "BYOK economics let small teams ship without enterprise contracts.",
    ],
    "demo": (
        "Type a topic, watch the 5-stage pipeline animate (fetch → cluster → label → "
        "stance → brief), then open the Cytoscape graph or download the auto-generated "
        "briefing PDF."
    ),
    "market": (
        "PR / comms, political analysis, brand monitoring, academic discourse research. "
        "Adjacent: $4B+ social-listening market dominated by Brandwatch, Talkwalker, Meltwater — "
        "all closed, all expensive, none agentic."
    ),
    "business_model": (
        "Open-source core. Hosted tier: per-run billing on top of BYOK keys. "
        "Enterprise: private connectors + retention + audit trail."
    ),
    "traction": [
        "5 source connectors live (FB, Reddit, HN, X, IG).",
        "8-provider LLM cascade w/ failover (Gemini, Groq, OpenRouter, LLM7, HF, Pollen, Ollama, OpenAI).",
        "Vision-OCR pipeline beating raw DOM scraping on Facebook.",
        "End-to-end briefing PDF generation, 1.9MB output.",
    ],
    "competition": (
        "Brandwatch / Talkwalker / Meltwater: closed, $50k+/yr, no agent loop. "
        "Sprinklr: enterprise sales cycle. "
        "Hobbyist scrapers: brittle, no AI layer, no graph."
    ),
    "advantage": (
        "Agent loop + vision-OCR + BYOK provider cascade. We do not depend on any "
        "single LLM vendor, any single source's DOM, or any single scraping technique."
    ),
    "gtm": (
        "Launch on HN + r/LocalLLaMA. Hackathon traction → open-source momentum → "
        "hosted tier for non-technical users."
    ),
    "vision": (
        "Every topic on the public web has a live sentiment fingerprint, queryable "
        "in natural language, with cited evidence. PulseTrace is that surface."
    ),
}

ROADMAP = {
    "short": [
        "Hosted demo deployment.",
        "Saved-run library + share links.",
        "Email digest of tracked topics.",
    ],
    "mid": [
        "Time-series sentiment alerts.",
        "Custom connector SDK.",
        "Multi-topic comparison view.",
    ],
    "long": [
        "Real-time streaming ingestion (Kafka-style).",
        "Predictive trend modeling.",
        "Enterprise SSO + audit log.",
    ],
}

FEATURES = [
    {"name": "Multi-source ingestion",   "status": "live",     "detail": "FB / Reddit / HN / X / IG connectors"},
    {"name": "Vision OCR fallback",      "status": "live",     "detail": "Gemini 2.5 Flash screenshot pipeline for FB"},
    {"name": "Agentic loop",             "status": "live",     "detail": "Query expansion until coverage converges"},
    {"name": "Cluster + label + stance", "status": "live",     "detail": "HDBSCAN + KMeans fallback, LLM labels"},
    {"name": "Topic graph (Cytoscape)",  "status": "live",     "detail": "Live SSE-pushed render"},
    {"name": "Briefing PDF",             "status": "live",     "detail": "Auto-generated, downscaled, ≤2MB"},
    {"name": "RAG Q&A w/ citations",     "status": "live",     "detail": "FAISS index + screenshot citation cards"},
    {"name": "BYOK provider cascade",    "status": "live",     "detail": "8-provider dispatch w/ failover"},
    {"name": "Saved runs library",       "status": "planned",  "detail": "Browse + share past runs"},
    {"name": "Time-series alerts",       "status": "planned",  "detail": "Watch topics, email on shift"},
    {"name": "Connector SDK",            "status": "planned",  "detail": "Plug in custom sources"},
]

STACK = {
    "Frontend":  ["Jinja templates", "Chart.js", "Cytoscape.js", "SSE (EventSource)"],
    "Backend":   ["Python 3.12", "Flask + flask-cors", "Playwright", "Pillow", "WeasyPrint"],
    "AI":        ["Gemini 2.5 Flash (chat + vision)", "gemini-embedding-001", "HDBSCAN clustering", "FAISS RAG index"],
    "Data":      ["Per-run JSON store", "Screenshot artifacts", "Cookie-backed session store"],
    "Providers": ["Gemini, Groq, OpenRouter, LLM7, HuggingFace, Pollinations, Ollama, OpenAI (cascade)"],
}

APIS_EXPOSED = [
    ("POST", "/run",                          "Launch agent run for a topic"),
    ("GET",  "/events",                       "SSE stream of pipeline events"),
    ("GET",  "/graph",                        "Cytoscape elements for current run"),
    ("POST", "/ask",                          "RAG Q&A with citations"),
    ("GET",  "/run/<id>/briefing/pdf",        "Download briefing PDF"),
    ("GET",  "/run/<id>/briefing/html",       "View briefing HTML"),
    ("GET",  "/providers",                    "List BYOK providers"),
    ("POST", "/byok/validate",                "Validate provider key"),
    ("GET",  "/fb/cookies/status",            "Facebook cookie staleness check"),
    ("GET",  "/shots/<id>",                   "List screenshot artifacts for run"),
    ("GET",  "/docs",                         "This page"),
]

APIS_CONSUMED = [
    "Google Gemini (chat + vision + embeddings)",
    "Reddit PRAW",
    "Hacker News Firebase API",
    "Facebook (Playwright session, vision OCR)",
    "Twitter/X (twikit)",
    "Instagram (instaloader)",
    "OpenAI-compatible endpoints (cascade fallback)",
]

ARCHITECTURE_MERMAID = """flowchart LR
  U[User Browser] -->|topic| F[Flask Server]
  F -->|spawn| A[Agent Loop]
  A --> C1[FB Connector]
  A --> C2[Reddit Connector]
  A --> C3[HN Connector]
  A --> C4[X Connector]
  A --> C5[IG Connector]
  C1 --> O[Vision OCR<br/>Gemini 2.5 Flash]
  C2 --> P[Post Store<br/>data/runs/]
  C3 --> P
  C4 --> P
  C5 --> P
  O --> P
  P --> E[Embed<br/>gemini-embedding-001]
  E --> CL[Cluster<br/>HDBSCAN]
  CL --> L[Label + Stance<br/>LLM]
  L --> R[RAG Index<br/>FAISS]
  L --> G[Graph + Briefing]
  G -->|SSE| U
  R -->|/ask| U
"""

DATA_FLOW_MERMAID = """flowchart TD
  IN[Topic + RAG questions] --> FETCH[Multi-source fetch]
  FETCH --> RAW[Raw posts JSON]
  RAW --> EMB[Embeddings]
  EMB --> CLU[Clusters]
  CLU --> LBL[Labels + stance + influence]
  LBL --> OUT1[Topic graph]
  LBL --> OUT2[Briefing PDF]
  LBL --> IDX[FAISS index]
  IDX --> QA[Cited Q&A]
  OUT1 --> FB[User feedback / new queries]
  FB --> FETCH
"""

DATA_LAYER = {
    "sources":  "Reddit (PRAW), HN (HTTP), Facebook (Playwright + vision OCR), X (twikit), Instagram (instaloader)",
    "storage":  "Per-run JSON under data/runs/<run_id>/. Screenshots under data/runs/<run_id>/shots/. No DB.",
    "privacy":  "BYOK — provider keys never leave the user's machine. No telemetry. Cookies stored locally in info/.",
}

AI_LAYER = {
    "chat":         "gemini-2.5-flash-lite (default), cascades through 8 providers on failure.",
    "vision":       "gemini-2.5-flash for screenshot → post extraction on hostile DOMs (Facebook).",
    "embeddings":   "gemini-embedding-001, cached per run.",
    "clustering":   "HDBSCAN primary, KMeans fallback with entropy-based k selection.",
    "rag":          "FAISS in-memory index, cosine similarity, top-k citations with screenshot pointers.",
    "explainable":  "Every cluster has LLM-generated label + stance + cited post IDs. Every RAG answer cites post IDs + screenshots.",
}

PERFORMANCE = {
    "Run cap":          "MAX_POSTS=500 per run.",
    "Embedding cache":  "Per-run; identical text skipped.",
    "PDF":              "Pillow downscale ≤720px JPEG q40 → 28MB ➜ 1.9MB.",
    "Cluster fallback": "HDBSCAN failure falls back to KMeans automatically.",
    "Provider failover":"8-provider cascade with retryable error detection.",
}

SECURITY = {
    "Auth":             "None on read endpoints (hackathon scope). /docs/admin gated by env token.",
    "Secrets":          ".env gitignored. BYOK keys injected per request, restored after.",
    "Cookies":          "Facebook session cookies in info/, never logged.",
    "RBAC":             "Single admin token. No multi-user model.",
}

ANALYTICS = {
    "Runs completed":   "Live counter (see header).",
    "Connectors live":  "Live counter.",
    "Pipeline stages":  "5 (fetch → embed → cluster → label → brief).",
    "Provider cascade": "8 providers.",
}

CHANGELOG = [
    ("2026-05-30", "Briefing PDF size optimization (28MB → 1.9MB), pipeline UI animation, /docs module."),
    ("2026-05-30", "FB OCR pipeline production-ready: batch fetch, cookie staleness modal, citations w/ screenshots."),
    ("2026-05-29", "BYOK landing + 8-provider cascade. Gemini paid key path. Cost guardrails."),
    ("2026-05-29", "PulseTrace v2 ship: 5 source connectors, agent loop, RAG, Cytoscape, SSE, briefing PDF."),
    ("2026-05-28", "Architecture lock-in: agent loop + multi-source + clustering + RAG."),
]
