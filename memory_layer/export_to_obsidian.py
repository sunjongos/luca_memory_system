import sqlite3
import os
import json
import re
from collections import defaultdict
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "luca_memory.db")
VAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "Luca_Memory_Vault")

def sanitize_filename(name):
    # Remove characters that are illegal in Windows filenames
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def get_db():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {os.path.abspath(DB_PATH)}")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def export_vault():
    print(f"🚀 Starting Obsidian Vault Export at: {os.path.abspath(VAULT_DIR)}")
    
    # Create directories
    for folder in ["Raw", "Wiki", "Log", "Index"]:
        os.makedirs(os.path.join(VAULT_DIR, folder), exist_ok=True)
        
    db = get_db()
    
    # 1. Export Raw Memories
    memories = db.execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()
    
    wiki_nodes = defaultdict(list) # Mapping Entity/Topic -> List of Memory IDs
    memory_links = {} # memory_id -> list of node links
    
    for rm in memories:
        m_id = rm["id"]
        source = rm["source"]
        summary = rm["summary"]
        raw_text = rm["raw_text"]
        created_at = rm["created_at"]
        importance = rm["importance"]
        
        try:
            entities = json.loads(rm["entities"])
        except:
            entities = []
            
        try:
            topics = json.loads(rm["topics"])
        except:
            topics = []
            
        # Register to wiki mapping
        linked_pages = []
        for e in entities + topics:
            if not e: continue
            safe_name = sanitize_filename(e)
            if safe_name:
                wiki_nodes[safe_name].append(m_id)
                linked_pages.append(f"[[{safe_name}]]")
                
        memory_links[m_id] = linked_pages
        
        # Write Raw Memory File
        tags_str = " ".join([f"#{sanitize_filename(t).replace(' ', '_')}" for t in topics if t])
        content = f"""---
id: {m_id}
source: {source}
date: {created_at}
importance: {importance}
tags: [raw, memory, {source}]
---

# Memory {m_id}: {summary}

**Date**: {created_at}
**Importance**: {importance}
**Tags**: {tags_str}

## Linked Concepts
{", ".join(linked_pages)}

## Raw Context
{raw_text}
"""
        with open(os.path.join(VAULT_DIR, "Raw", f"Memory_{m_id}.md"), "w", encoding="utf-8") as f:
            f.write(content)

    print(f"✅ Exported {len(memories)} raw memories to /Raw")

    # 2. Export Wiki (Entities & Topics)
    # Sort by frequency
    sorted_nodes = sorted(wiki_nodes.items(), key=lambda x: len(x[1]), reverse=True)
    
    for node_name, m_ids in sorted_nodes:
        # Prevent deduplication issues
        unique_m_ids = sorted(list(set(m_ids)), reverse=True)
        
        backlinks = "\n".join([f"- [[Memory_{mid}]]" for mid in unique_m_ids])
        
        content = f"""---
title: {node_name}
aliases: []
tags: [wiki, concept]
reference_count: {len(unique_m_ids)}
---

# {node_name}

이 개념은 Luca의 장기 기억 체계 내에서 주요한 노드로 식별되었습니다.

## 언급된 원본 기억 (Backlinks)
{backlinks}

"""
        with open(os.path.join(VAULT_DIR, "Wiki", f"{node_name}.md"), "w", encoding="utf-8") as f:
            f.write(content)

    print(f"✅ Exported {len(sorted_nodes)} concept pages to /Wiki")

    # 3. Export Log (Consolidations)
    consolidations = db.execute("SELECT * FROM consolidations ORDER BY created_at DESC").fetchall()
    
    for rc in consolidations:
        c_id = rc["id"]
        summary = rc["summary"]
        insight = rc["insight"]
        created_at = rc["created_at"]
        
        try:
            source_ids = json.loads(rc["source_ids"])
        except:
            source_ids = []
            
        src_links = "\n".join([f"- [[Memory_{mid}]]" for mid in source_ids])
        
        content = f"""---
id: C_{c_id}
date: {created_at}
tags: [log, insight, consolidation]
---

# Insight: {summary}

**Date**: {created_at}

## Deep Insight / Synthesis
{insight}

## Sources (Connected Memories)
{src_links}
"""
        with open(os.path.join(VAULT_DIR, "Log", f"Insight_{c_id}.md"), "w", encoding="utf-8") as f:
            f.write(content)
            
    print(f"✅ Exported {len(consolidations)} consolidation logs to /Log")

    # 4. Generate Index (MOC)
    top_nodes = sorted_nodes[:30]
    top_links = "\n".join([f"- [[{name}]] ({len(mids)} mentions)" for name, mids in top_nodes])
    
    moc_content = f"""---
tags: [index, moc]
date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
---

# 🧠 Luca Master Map of Content (MOC)

이 페이지는 에이전트의 전체 머릿속(장기 메모리)을 조망하는 대시보드입니다.

## 📊 현재 기억 상태
- **원시 메모리(Raw):** {len(memories)} 개
- **위키 개념(Wiki):** {len(sorted_nodes)} 개
- **심층 통찰(Log):** {len(consolidations)} 개

## ⭐ 핵심 개념 (Top 30)
가장 많이 참조된 상위 토픽 및 엔티티입니다.

{top_links}

---
*Generated Automatically by Luca Exporter*
"""
    with open(os.path.join(VAULT_DIR, "Index", "MOC.md"), "w", encoding="utf-8") as f:
        f.write(moc_content)
        
    print(f"✅ Exported Master MOC to /Index")
    print(f"\n🎉 완료되었습니다! Obsidian을 열고 '폴더를 볼트(Vault)로 열기'에서 다음 경로를 지정해주세요:\n{os.path.abspath(VAULT_DIR)}")

if __name__ == "__main__":
    try:
        export_vault()
    except Exception as e:
        print(f"Export failed: {e}")
