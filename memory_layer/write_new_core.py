"""Helper script to write the new world-best core.py"""
import os

CORE_CODE = r'''"""
Luca Brain - World-Best Memory Core (Phase 1+2+3)
"""
import json, logging, math, os, re, requests, sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from google.adk.agents import Agent

MODEL            = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBED_MODEL      = "models/text-embedding-004"
DB_PATH          = os.getenv("MEMORY_DB_PATH", "luca_memory.db")
DECAY_RATE       = float(os.getenv("MEMORY_DECAY_RATE", "0.03"))
IMPORTANCE_FLOOR = 0.05
REINFORCE_BOOST  = 0.02

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("luca-brain")

# ── Embedding ──────────────────────────────────────────────────────────────
def get_embedding(text: str) -> list:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/{EMBED_MODEL}:embedContent?key={api_key}"
    try:
        r = requests.post(url, json={"model": EMBED_MODEL, "content": {"parts": [{"text": text[:8000]}]}}, timeout=15)
        r.raise_for_status()
        return r.json()["embedding"]["values"]
    except Exception as e:
        log.error(f"Embedding error: {e}")
        return []

def cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    na  = math.sqrt(sum(x*x for x in a))
    nb  = math.sqrt(sum(x*x for x in b))
    return 0.0 if na==0 or nb==0 else dot/(na*nb)

# ── Database ───────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source       TEXT NOT NULL DEFAULT 'user_chat',
            agent_id     TEXT NOT NULL DEFAULT 'system',
            raw_text     TEXT NOT NULL,
            summary      TEXT NOT NULL,
            entities     TEXT NOT NULL DEFAULT '[]',
            topics       TEXT NOT NULL DEFAULT '[]',
            connections  TEXT NOT NULL DEFAULT '[]',
            importance   REAL NOT NULL DEFAULT 0.5,
            confidence   REAL NOT NULL DEFAULT 0.8,
            embedding    TEXT DEFAULT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT DEFAULT NULL,
            created_at   TEXT NOT NULL,
            consolidated INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS consolidations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            source_ids TEXT NOT NULL,
            summary    TEXT NOT NULL,
            insight    TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS causal_chains (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            from_memory_id    INTEGER NOT NULL,
            to_memory_id      INTEGER NOT NULL,
            cause_description TEXT NOT NULL,
            effect_description TEXT NOT NULL,
            confidence        REAL NOT NULL DEFAULT 0.7,
            agent_id          TEXT DEFAULT 'system',
            created_at        TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_predictions (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_topic        TEXT NOT NULL,
            trigger_embedding    TEXT DEFAULT NULL,
            predicted_memory_ids TEXT NOT NULL,
            prediction_score     REAL DEFAULT 0.5,
            was_accessed         INTEGER DEFAULT 0,
            created_at           TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ontology_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id  INTEGER NOT NULL,
            entities   TEXT NOT NULL,
            ttl_patch  TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance DESC);
        CREATE INDEX IF NOT EXISTS idx_mem_agent      ON memories(agent_id);
        CREATE INDEX IF NOT EXISTS idx_mem_created    ON memories(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_causal_from    ON causal_chains(from_memory_id);
    """)
    db.commit()
    return db

# ── Temporal Decay ─────────────────────────────────────────────────────────
def apply_temporal_decay(memory_id=None) -> dict:
    db = get_db()
    now = datetime.now(timezone.utc)
    where = "WHERE id = ?" if memory_id else "WHERE consolidated = 0"
    params = (memory_id,) if memory_id else ()
    rows = db.execute(f"SELECT id, importance, created_at FROM memories {where}", params).fetchall()
    updated = 0
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days = (now - created).total_seconds() / 86400
            decayed = max(row["importance"] * math.exp(-DECAY_RATE * days), IMPORTANCE_FLOOR)
            if abs(decayed - row["importance"]) > 0.001:
                db.execute("UPDATE memories SET importance=? WHERE id=?", (round(decayed,4), row["id"]))
                updated += 1
        except Exception:
            pass
    db.commit(); db.close()
    return {"updated": updated}

def reinforce_memory(memory_id: int) -> None:
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE memories SET importance=MIN(1.0,importance+?), access_count=access_count+1, last_accessed=? WHERE id=?",
               (REINFORCE_BOOST, now, memory_id))
    db.commit(); db.close()

# ── Core Tools ─────────────────────────────────────────────────────────────
def store_memory(raw_text: str, summary: str, entities: list, topics: list,
                 importance: float, source: str = "luca_chat",
                 agent_id: str = "system", confidence: float = 0.8) -> dict:
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    emb_text = f"{summary} {' '.join(entities or [])} {' '.join(topics or [])}"
    embedding = get_embedding(emb_text)
    cursor = db.execute(
        "INSERT INTO memories (source,agent_id,raw_text,summary,entities,topics,importance,confidence,embedding,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (source, agent_id, raw_text, summary, json.dumps(entities or []), json.dumps(topics or []),
         importance, confidence, json.dumps(embedding) if embedding else None, now)
    )
    mid = cursor.lastrowid
    db.commit()
    _auto_update_ontology(db, mid, entities or [], topics or [])
    db.close()
    log.info(f"Memory #{mid} [{agent_id}]: {summary[:60]}")
    return {"memory_id": mid, "status": "stored", "summary": summary, "has_embedding": bool(embedding)}

def semantic_search(query: str, top_k: int = 5, agent_id: str = None) -> dict:
    q_emb = get_embedding(query)
    if not q_emb:
        return {"error": "embedding_failed", "results": []}
    db = get_db()
    sql = "SELECT id,summary,entities,topics,importance,confidence,agent_id,created_at,embedding FROM memories WHERE embedding IS NOT NULL"
    params = []
    if agent_id:
        sql += " AND agent_id=?"; params.append(agent_id)
    rows = db.execute(sql, params).fetchall()
    db.close()
    scored = []
    for row in rows:
        try:
            sim = cosine_similarity(q_emb, json.loads(row["embedding"]))
            score = sim*0.7 + row["importance"]*0.3
            scored.append({"id": row["id"], "summary": row["summary"],
                           "entities": json.loads(row["entities"]), "topics": json.loads(row["topics"]),
                           "importance": row["importance"], "confidence": row["confidence"],
                           "agent_id": row["agent_id"], "created_at": row["created_at"],
                           "similarity": round(sim,4), "score": round(score,4)})
        except Exception:
            pass
    scored.sort(key=lambda x: x["score"], reverse=True)
    results = scored[:top_k]
    for r in results:
        reinforce_memory(r["id"])
    return {"query": query, "results": results, "total_searched": len(scored)}

def read_all_memories(limit: int = 50) -> dict:
    apply_temporal_decay()
    db = get_db()
    rows = db.execute("SELECT * FROM memories ORDER BY importance DESC, created_at DESC LIMIT ?", (limit,)).fetchall()
    memories = []
    for r in rows:
        m = dict(r); m["entities"]=json.loads(m["entities"]); m["topics"]=json.loads(m["topics"])
        m["connections"]=json.loads(m["connections"]); m["consolidated"]=bool(m["consolidated"])
        m.pop("embedding", None); memories.append(m)
    db.close()
    return {"memories": memories, "count": len(memories)}

def read_unconsolidated_memories(limit: int = 15) -> dict:
    db = get_db()
    rows = db.execute("SELECT id,summary,entities,topics,importance,confidence,agent_id,created_at FROM memories WHERE consolidated=0 ORDER BY importance DESC, created_at DESC LIMIT ?", (limit,)).fetchall()
    memories = [{"id":r["id"],"summary":r["summary"],"entities":json.loads(r["entities"]),"topics":json.loads(r["topics"]),"importance":r["importance"],"confidence":r["confidence"],"agent_id":r["agent_id"],"created_at":r["created_at"]} for r in rows]
    db.close()
    return {"memories": memories, "count": len(memories)}

def store_consolidation(source_ids: list, summary: str, insight: str, connections: list) -> dict:
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO consolidations (source_ids,summary,insight,created_at) VALUES (?,?,?,?)",
               (json.dumps(source_ids), summary, insight, now))
    for conn in connections:
        from_id, to_id, rel = conn.get("from_id"), conn.get("to_id"), conn.get("relationship","")
        if from_id and to_id:
            for mid in [from_id, to_id]:
                row = db.execute("SELECT connections FROM memories WHERE id=?", (mid,)).fetchone()
                if row:
                    ex = json.loads(row["connections"])
                    ex.append({"linked_to": to_id if mid==from_id else from_id, "relationship": rel})
                    db.execute("UPDATE memories SET connections=? WHERE id=?", (json.dumps(ex), mid))
            if any(kw in rel.lower() for kw in ["cause","lead","result","trigger","because","따라서","원인","결과"]):
                db.execute("INSERT INTO causal_chains (from_memory_id,to_memory_id,cause_description,effect_description,confidence,created_at) VALUES (?,?,?,?,?,?)",
                           (from_id, to_id, f"[Auto] {rel}", insight[:200], 0.7, now))
    ph = ",".join("?"*len(source_ids))
    db.execute(f"UPDATE memories SET consolidated=1 WHERE id IN ({ph})", source_ids)
    db.commit()
    _sync_to_obsidian(summary, insight, connections)
    db.close()
    log.info(f"Consolidated {len(source_ids)} memories")
    return {"status": "consolidated", "memories_processed": len(source_ids), "insight": insight}

def read_consolidation_history(limit: int = 10) -> dict:
    db = get_db()
    rows = db.execute("SELECT * FROM consolidations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    result = [{"summary":r["summary"],"insight":r["insight"],"source_ids":json.loads(r["source_ids"])} for r in rows]
    db.close()
    return {"consolidations": result, "count": len(result)}

def search_obsidian_vault(keyword: str) -> dict:
    base_dir = Path(__file__).resolve().parent.parent
    wiki_dir = base_dir / "Luca_Memory_Vault" / "Wiki"
    results = []
    if wiki_dir.exists():
        for f in wiki_dir.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if keyword.lower() in content.lower() or keyword.lower() in f.name.lower():
                    results.append({"title": f.stem, "snippet": content[:500]})
            except Exception:
                pass
    return {"keyword": keyword, "obsidian_matches": results[:5]}

# ── Phase 2: Causal + Proactive Context ────────────────────────────────────
def store_causal_chain(from_memory_id: int, to_memory_id: int, cause_description: str,
                       effect_description: str, confidence: float = 0.7, agent_id: str = "system") -> dict:
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute("INSERT INTO causal_chains (from_memory_id,to_memory_id,cause_description,effect_description,confidence,agent_id,created_at) VALUES (?,?,?,?,?,?,?)",
                     (from_memory_id, to_memory_id, cause_description, effect_description, confidence, agent_id, now))
    db.commit(); db.close()
    return {"chain_id": cur.lastrowid, "status": "stored"}

def query_causal_chains(memory_id: int = None, keyword: str = None) -> dict:
    db = get_db()
    base = "SELECT c.*, m1.summary as from_summary, m2.summary as to_summary FROM causal_chains c JOIN memories m1 ON c.from_memory_id=m1.id JOIN memories m2 ON c.to_memory_id=m2.id"
    if memory_id:
        rows = db.execute(f"{base} WHERE c.from_memory_id=? OR c.to_memory_id=? ORDER BY c.confidence DESC", (memory_id, memory_id)).fetchall()
    elif keyword:
        rows = db.execute(f"{base} WHERE c.cause_description LIKE ? OR c.effect_description LIKE ? ORDER BY c.confidence DESC LIMIT 10", (f"%{keyword}%", f"%{keyword}%")).fetchall()
    else:
        rows = db.execute(f"{base} ORDER BY c.created_at DESC LIMIT 20").fetchall()
    chains = [dict(r) for r in rows]
    db.close()
    return {"chains": chains, "count": len(chains)}

def get_proactive_context(topic: str, top_k: int = 7) -> dict:
    semantic = semantic_search(topic, top_k=top_k)
    semantic_ids = {r["id"] for r in semantic.get("results", [])}
    db = get_db()
    causal_results = []
    for mid in list(semantic_ids)[:3]:
        chains = db.execute("SELECT c.*, m1.summary as cs, m2.summary as es FROM causal_chains c JOIN memories m1 ON c.from_memory_id=m1.id JOIN memories m2 ON c.to_memory_id=m2.id WHERE c.from_memory_id=? OR c.to_memory_id=? ORDER BY c.confidence DESC LIMIT 3", (mid, mid)).fetchall()
        for c in chains:
            causal_results.append({"cause": c["cs"], "effect": c["es"], "description": c["cause_description"], "confidence": c["confidence"]})
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = db.execute("SELECT id,summary,importance,agent_id FROM memories WHERE created_at>? AND importance>0.6 ORDER BY importance DESC LIMIT 3", (since,)).fetchall()
    recent_results = [{"id":r["id"],"summary":r["summary"],"importance":r["importance"],"agent_id":r["agent_id"]} for r in recent]
    db.close()
    _store_prediction(topic, [r["id"] for r in semantic.get("results", [])])
    return {"topic": topic, "semantic_memories": semantic.get("results",[]), "causal_chains": causal_results, "recent_important": recent_results}

# ── Phase 3: Cross-Time + Prediction + Stats ───────────────────────────────
def cross_time_reasoning(topic: str) -> dict:
    all_mems = semantic_search(topic, top_k=20)
    now = datetime.now(timezone.utc)
    timeline = sorted(all_mems.get("results",[]), key=lambda x: x["created_at"])
    windows = {}
    for days in [7, 30, 90, 365]:
        cutoff = (now - timedelta(days=days)).isoformat()
        windows[f"last_{days}d"] = len([m for m in timeline if m["created_at"] >= cutoff])
    trend = "emerging" if windows.get("last_7d",0) > windows.get("last_30d",0)*0.3 else ("stable" if windows.get("last_30d",0) else "new")
    return {"topic": topic, "trend": trend, "total": len(timeline),
            "by_time_window": windows,
            "timeline": [{"date":m["created_at"][:10],"summary":m["summary"],"importance":m["importance"],"agent_id":m["agent_id"]} for m in timeline],
            "oldest": timeline[0]["created_at"][:10] if timeline else None,
            "latest": timeline[-1]["created_at"][:10] if timeline else None}

def predict_next_memories(current_context: str, top_k: int = 5) -> dict:
    db = get_db()
    past = db.execute("SELECT trigger_topic,predicted_memory_ids,trigger_embedding FROM memory_predictions WHERE trigger_embedding IS NOT NULL ORDER BY created_at DESC LIMIT 50").fetchall()
    db.close()
    cur_emb = get_embedding(current_context)
    similar_ids = []
    for pred in past:
        try:
            sim = cosine_similarity(cur_emb, json.loads(pred["trigger_embedding"]))
            if sim > 0.7:
                similar_ids.extend(json.loads(pred["predicted_memory_ids"]))
        except Exception:
            pass
    freq = Counter(similar_ids)
    top_ids = [mid for mid, _ in freq.most_common(top_k)]
    predicted = []
    if top_ids:
        db = get_db()
        for mid in top_ids:
            row = db.execute("SELECT id,summary,importance,topics FROM memories WHERE id=?", (mid,)).fetchone()
            if row:
                predicted.append({"id":row["id"],"summary":row["summary"],"importance":row["importance"],"topics":json.loads(row["topics"]),"freq":freq[mid]})
        db.close()
    if not predicted:
        predicted = semantic_search(current_context, top_k=top_k).get("results",[])
    return {"context": current_context, "predicted": predicted, "method": "pattern" if top_ids else "semantic"}

def get_memory_stats() -> dict:
    db = get_db()
    s = {
        "total":           db.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        "consolidated":    db.execute("SELECT COUNT(*) FROM memories WHERE consolidated=1").fetchone()[0],
        "with_embedding":  db.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL").fetchone()[0],
        "causal_chains":   db.execute("SELECT COUNT(*) FROM causal_chains").fetchone()[0],
        "consolidations":  db.execute("SELECT COUNT(*) FROM consolidations").fetchone()[0],
        "predictions":     db.execute("SELECT COUNT(*) FROM memory_predictions").fetchone()[0],
        "ontology_events": db.execute("SELECT COUNT(*) FROM ontology_events").fetchone()[0],
    }
    avg = db.execute("SELECT AVG(importance) FROM memories").fetchone()[0]
    s["avg_importance"] = round(avg, 3) if avg else 0
    s["by_agent"] = {r["agent_id"]: r["cnt"] for r in db.execute("SELECT agent_id, COUNT(*) as cnt FROM memories GROUP BY agent_id").fetchall()}
    db.close()
    return s

# ── Internal Helpers ───────────────────────────────────────────────────────
def _store_prediction(trigger_topic: str, predicted_ids: list) -> None:
    try:
        db = get_db()
        emb = get_embedding(trigger_topic)
        db.execute("INSERT INTO memory_predictions (trigger_topic,trigger_embedding,predicted_memory_ids,created_at) VALUES (?,?,?,?)",
                   (trigger_topic, json.dumps(emb) if emb else None, json.dumps(predicted_ids), datetime.now(timezone.utc).isoformat()))
        db.commit(); db.close()
    except Exception:
        pass

def _auto_update_ontology(db, memory_id: int, entities: list, topics: list) -> None:
    try:
        base_dir = Path(__file__).resolve().parent.parent
        ttl_file = base_dir / ".agent" / "skills" / "ontology_ndb" / "ndb_knowledge.ttl"
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        patch = ""
        for e in entities[:5]:
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", e)
            patch += f'\\nndb:{safe}_{memory_id} a owl:NamedIndividual ; rdfs:label "{e}" ; ndb:memory_id "{memory_id}" .\\n'
        db.execute("INSERT INTO ontology_events (memory_id,entities,ttl_patch,created_at) VALUES (?,?,?,?)",
                   (memory_id, json.dumps(entities), patch, datetime.now(timezone.utc).isoformat()))
        db.commit()
        if ttl_file.parent.exists() and patch:
            ttl_file.open("a", encoding="utf-8").write(patch)
    except Exception as e:
        log.warning(f"Ontology update skipped: {e}")

def _sync_to_obsidian(summary: str, insight: str, connections: list) -> None:
    try:
        base_dir = Path(__file__).resolve().parent.parent
        wiki_dir = base_dir / "Luca_Memory_Vault" / "Wiki"
        ttl_file = base_dir / ".agent" / "skills" / "ontology_ndb" / "ndb_knowledge.ttl"
        safe_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        if wiki_dir.exists():
            title = f"Luca_Insight_{safe_time}"
            content = f"# {title}\\n\\n## Summary\\n{summary}\\n\\n## Insight\\n{insight}\\n\\n### Links\\n"
            for c in connections:
                if c.get("relationship"):
                    content += f"- [[Memory_{c.get('from_id')}]] --{c.get('relationship')}--> [[Memory_{c.get('to_id')}]]\\n"
            (wiki_dir / f"{title}.md").write_text(content, encoding="utf-8")
        if ttl_file.parent.exists():
            ttl_file.open("a", encoding="utf-8").write(f'\\nndb:Insight_{safe_time} a owl:Class ; rdfs:label "Consolidation" ; rdfs:comment "{summary[:80].replace(chr(10)," ")}" .\\n')
    except Exception as e:
        log.error(f"Obsidian sync failed: {e}")

# ── ADK Agents ─────────────────────────────────────────────────────────────
def build_memory_agents() -> Agent:
    ingest_agent = Agent(
        name="ingest_agent", model=MODEL,
        description="Processes raw text into structured memory with vector embeddings.",
        instruction="You are Luca's Memory Ingest Agent.\\n1. Extract 1-2 sentence summary\\n2. Extract entities\\n3. Assign 2-4 topic tags\\n4. Rate importance 0.0-1.0\\n5. Set confidence 0.0-1.0\\n6. Call store_memory",
        tools=[store_memory],
    )
    consolidate_agent = Agent(
        name="consolidate_agent", model=MODEL,
        description="Consolidates memories into insights with causal chain detection.",
        instruction="You are Luca\'s Consolidation Agent.\\n1. Call read_unconsolidated_memories\\n2. Find patterns+causal relationships\\n3. Generate ONE powerful insight\\n4. Call store_consolidation with connections (use causal keywords: causes/leads_to/results_in)\\n5. Optionally call store_causal_chain.",
        tools=[read_unconsolidated_memories, store_consolidation, store_causal_chain],
    )
    query_agent = Agent(
        name="query_agent", model=MODEL,
        description="Answers questions using semantic search + causal chains + Obsidian.",
        instruction="You are Luca\'s Memory Query Agent.\\n1. Use semantic_search for vector recall\\n2. Use query_causal_chains for cause-effect\\n3. Use read_consolidation_history\\n4. Use search_obsidian_vault\\nCite: [Memory #id] [Chain] [Obsidian: title]",
        tools=[semantic_search, query_causal_chains, read_all_memories, read_consolidation_history, search_obsidian_vault],
    )
    context_agent = Agent(
        name="context_agent", model=MODEL,
        description="Proactively loads context + predicts future memory needs.",
        instruction="You are Luca\'s Proactive Context Agent.\\n1. Call get_proactive_context\\n2. Call predict_next_memories\\n3. Call cross_time_reasoning\\nReturn curated context bundle.",
        tools=[get_proactive_context, predict_next_memories, cross_time_reasoning],
    )
    orchestrator = Agent(
        name="memory_orchestrator", model=MODEL,
        description="Master Brain Orchestrator.",
        instruction="Route: Remember->ingest_agent | Consolidate->consolidate_agent | Recall->query_agent | Context/Predict->context_agent",
        sub_agents=[ingest_agent, consolidate_agent, query_agent, context_agent],
    )
    return orchestrator
'''

with open("c:/Users/sunjo/Desktop/luca 연구자동화에이전트/memory_layer/core.py", "w", encoding="utf-8") as f:
    f.write(CORE_CODE)
print("core.py written:", len(CORE_CODE), "chars")
