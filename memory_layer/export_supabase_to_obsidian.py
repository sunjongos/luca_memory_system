import os
import json
import re
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

VAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "Supabase_Memory_Vault")

def sanitize_filename(name):
    # Remove characters that are illegal in Windows filenames
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def export_vault():
    print(f"Starting Supabase -> Obsidian Vault Export at: {os.path.abspath(VAULT_DIR)}")
    
    # Supabase Connection
    load_dotenv()
    _SB_URL = os.environ.get("SUPABASE_URL", "")
    _SB_KEY = os.environ.get("SUPABASE_KEY", "")
    if not _SB_URL or not _SB_KEY:
        print("Supabase API Key not found in .env")
        return
    
    client: Client = create_client(_SB_URL, _SB_KEY)
    
    # Create directories
    for folder in ["Raw", "Wiki", "Index"]:
        os.makedirs(os.path.join(VAULT_DIR, folder), exist_ok=True)
        
    print("Fetching agent_memories from Supabase...")
    # Fetch data
    response = client.table('agent_memories').select('*').order('created_at', desc=True).execute()
    memories = response.data
    
    wiki_nodes = defaultdict(list) # Mapping Entity/Topic -> List of Memory IDs
    memory_links = {} # memory_id -> list of node links
    
    print(f"Downloaded {len(memories)} memories.")
    
    for rm in memories:
        m_id = str(rm["id"])
        source = rm.get("source", "Unknown")
        summary = rm.get("summary") or "No Summary"
        raw_text = rm.get("raw_text", "")
        created_at = rm.get("created_at", str(datetime.now()))
        importance = rm.get("importance", 0.5)
        
        entities = rm.get("entities", [])
        if isinstance(entities, str):
            try: entities = json.loads(entities)
            except: entities = []
            
        topics = rm.get("topics", [])
        if isinstance(topics, str):
            try: topics = json.loads(topics)
            except: topics = []
            
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

    print(f"Exported {len(memories)} raw memories to /Raw")

    # 2. Export Wiki (Entities & Topics)
    sorted_nodes = sorted(wiki_nodes.items(), key=lambda x: len(x[1]), reverse=True)
    
    for node_name, m_ids in sorted_nodes:
        unique_m_ids = sorted(list(set(m_ids)), reverse=True)
        backlinks = "\n".join([f"- [[Memory_{mid}]]" for mid in unique_m_ids])
        
        content = f"""---
title: {node_name}
aliases: []
tags: [wiki, concept]
reference_count: {len(unique_m_ids)}
---

# {node_name}

이 개념은 Luca의 Supabase 클라우드 기억 체계 내에서 주요한 노드로 식별되었습니다.

## 언급된 원본 기억 (Backlinks)
{backlinks}

"""
        with open(os.path.join(VAULT_DIR, "Wiki", f"{node_name}.md"), "w", encoding="utf-8") as f:
            f.write(content)

    print(f"Exported {len(sorted_nodes)} concept pages to /Wiki")

    # 3. Generate Index (MOC)
    top_nodes = sorted_nodes[:30]
    top_links = "\n".join([f"- [[{name}]] ({len(mids)} mentions)" for name, mids in top_nodes])
    
    moc_content = f"""---
tags: [index, moc]
date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
---

# ☁️ Supabase Cloud Memory Map (MOC)

이 페이지는 클라우드 안의 에이전트 장기 메모리(Supabase `agent_memories`)를 조망하는 최고 관리용 지식 그래프 대시보드입니다.

## 📊 현재 데이터베이스 상태
- **원시 메모리(Raw):** {len(memories)} 개
- **위키 개념(Wiki 노드):** {len(sorted_nodes)} 개

## ⭐ 핵심 개념 지식그래프 (Top 30)
클라우드 뇌에서 가장 많이 교차 참조된 상위 엔티티입니다. 옵시디언 그래프 뷰 모드 시 가장 큰 중심 원이 됩니다.

{top_links}

---
*Generated Automatically by Supabase-Obsidian Exporter*
"""
    with open(os.path.join(VAULT_DIR, "Index", "MOC.md"), "w", encoding="utf-8") as f:
        f.write(moc_content)
        
    print(f"Exported Cloud Master MOC to /Index")
    print(f"\nAll data extracted. Please open Obsidian and select this folder as Vault:\n> {os.path.abspath(VAULT_DIR)}")
    
    # Launch Obsidian automatically via CLI / URI
    try:
        import urllib.parse
        import webbrowser
        safe_path = urllib.parse.quote(os.path.abspath(VAULT_DIR))
        obsidian_uri = f"obsidian://open?path={safe_path}"
        print(f"\n🚀 Авто-오픈 시도: CLI로 옵시디언을 호출합니다! ({obsidian_uri})")
        print("💡 [안내] 최초 1회는 보안상 'Vault not found' 에러가 날 수 있습니다. 이 경우 옵시디언에서 'Open folder as vault'로 해당 폴더를 한 번만 열어주시면 이후부터 자동 실행됩니다!")
        webbrowser.open(obsidian_uri)
    except Exception as e:
        print(f"⚠️ 옵시디언 자동 실행 실패: {e}")

if __name__ == "__main__":
    export_vault()
