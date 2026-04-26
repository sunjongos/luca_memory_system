"""
Claude Code <-> Antigravity ASMR 메모리 브릿지
==============================================
Claude Code가 Bash에서 직접 호출하여 ASMR 3인방 요원의 분석 결과를 받거나,
Port 5050 공유 메모리에 저장/조회하는 경량 CLI.

사용법:
  python shared/claude_memory_bridge.py health
  python shared/claude_memory_bridge.py raw-query "질문"
  python shared/claude_memory_bridge.py query "ASMR 3인방 분석 질문"
  python shared/claude_memory_bridge.py ingest "저장할 내용"
  python shared/claude_memory_bridge.py observe "세션 로그 텍스트"
  python shared/claude_memory_bridge.py ontology "지식그래프 질문"
"""

import asyncio
import json
import os
import sys
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ASMR 모듈 경로 추가
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ASMR_SKILLS_DIR = os.path.join(PROJECT_ROOT, ".agents", "skills")
if ASMR_SKILLS_DIR not in sys.path:
    sys.path.insert(0, ASMR_SKILLS_DIR)

import httpx

# 환경변수에서 GEMINI_API_KEY 로드 (.env 지원)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PORT_5050_URL = os.environ.get("MEMORY_SERVER_URL", "http://127.0.0.1:5050")

# ─── 공유 httpx 클라이언트 ──────────────────────────────────
_gemini_client: httpx.AsyncClient | None = None


async def _get_gemini_client() -> httpx.AsyncClient:
    global _gemini_client
    if _gemini_client is None or _gemini_client.is_closed:
        _gemini_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _gemini_client


async def _cleanup():
    global _gemini_client
    if _gemini_client and not _gemini_client.is_closed:
        await _gemini_client.aclose()


async def gemini_llm_call(system_prompt: str, user_prompt: str, json_schema: dict) -> str:
    """Gemini 2.5 Flash API 호출 (ASMR 에이전트용)"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return json.dumps({"error": "GEMINI_API_KEY 환경변수가 설정되지 않았습니다."})

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )

    schema_str = json.dumps(json_schema, ensure_ascii=False) if json_schema else "{}"
    full_system_prompt = (
        system_prompt
        + "\n\n[CRITICAL INSTRUCTION]\n"
        "You MUST return ONLY a pure JSON string matching the schema below. "
        "No markdown fences, no commentary, no extra text.\n"
        f"Schema: {schema_str}"
    )

    payload = {
        "systemInstruction": {"parts": [{"text": full_system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }

    client = await _get_gemini_client()
    resp = await client.post(url, json=payload)
    if resp.status_code != 200:
        return json.dumps({"error": f"Gemini API Error {resp.status_code}: {resp.text[:300]}"})

    data = resp.json()
    try:
        text_response = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # 마크다운 펜스 제거
        if text_response.startswith("```json"):
            text_response = text_response[7:]
        if text_response.startswith("```"):
            text_response = text_response[3:]
        if text_response.endswith("```"):
            text_response = text_response[:-3]
        return text_response.strip()
    except (KeyError, IndexError):
        return json.dumps({"error": "Gemini API 응답 파싱 실패"})


async def local_gemma_call(system_prompt: str, user_prompt: str, json_schema: dict) -> str:
    """Local Gemma (Ollama) API 호출 (ASMR 에이전트용) - API 키 노출 방지"""
    # 환경 변수에서 로컬 모델 이름 가져오기 (기본값 gemma)
    model_name = os.environ.get("LOCAL_GEMMA_MODEL", "gemma")
    url = "http://127.0.0.1:11434/api/generate"
    
    schema_str = json.dumps(json_schema, ensure_ascii=False) if json_schema else "{}"
    full_prompt = (
        f"System Instruction:\n{system_prompt}\n\n"
        f"User:\n{user_prompt}\n\n"
        "[CRITICAL INSTRUCTION]\n"
        "You MUST return ONLY a pure JSON string matching the schema below. "
        "No markdown fences, no commentary, no extra text.\n"
        f"Schema: {schema_str}"
    )
    
    payload = {
        "model": model_name,
        "prompt": full_prompt,
        "stream": False,
        "options": {"temperature": 0.2}
    }
    
    client = await _get_gemini_client()
    try:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            return json.dumps({"error": f"Ollama API Error {resp.status_code}: {resp.text[:300]}"})
        
        data = resp.json()
        text_response = data.get("response", "").strip()
        # 마크다운 펜스 제거
        if text_response.startswith("```json"):
            text_response = text_response[7:]
        if text_response.startswith("```"):
            text_response = text_response[3:]
        if text_response.endswith("```"):
            text_response = text_response[:-3]
        return text_response.strip()
    except Exception as e:
        return json.dumps({"error": f"Local Gemma Error: {str(e)}"})


# ─── 명령어 구현 ──────────────────────────────────────────

async def cmd_health():
    """Port 5050 서버 + GEMINI_API_KEY 상태 확인"""
    status = {"port_5050": "UNREACHABLE", "gemini_api_key": "MISSING", "ready": False}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            resp = await client.post(
                f"{PORT_5050_URL}/query",
                json={"question": "ping"},
            )
            if resp.status_code == 200:
                status["port_5050"] = "OK"
    except Exception as e:
        status["port_5050_error"] = str(e)

    if os.environ.get("GEMINI_API_KEY"):
        status["gemini_api_key"] = "SET"

    status["ready"] = status["port_5050"] == "OK" and status["gemini_api_key"] == "SET"
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status["ready"] else 1


async def cmd_raw_query(question: str):
    """Port 5050 직접 쿼리 (ASMR 없이, 빠름)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{PORT_5050_URL}/query",
                json={"question": question},
            )
            if resp.status_code == 200:
                data = resp.json()
                print(data.get("result", "(빈 결과)"))
                return 0
            else:
                print(f"ERROR: HTTP {resp.status_code}", file=sys.stderr)
                return 1
    except httpx.ConnectError:
        print("ERROR: Port 5050 서버에 연결할 수 없습니다. pm2 start luca-memory-layer 실행 필요", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


async def cmd_ingest(text: str):
    """Port 5050에 메모리 저장"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{PORT_5050_URL}/ingest",
                json={"text": text},
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            if resp.status_code == 200:
                data = resp.json()
                print(json.dumps({"status": "ingested", "detail": data.get("result", "OK")}, ensure_ascii=False))
                return 0
            else:
                print(f"ERROR: HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                return 1
    except httpx.ConnectError:
        print("ERROR: Port 5050 서버 연결 불가", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


async def cmd_query(question: str):
    """ASMR 3인방 에이전트 분석 (Dr.Claw: Fact + Context + Causal + Arbiter)"""
    from asmr_memory_system.core import ASMRParallelOrchestrator
    from asmr_memory_system.port_5050_bridge import Port5050Bridge, Port5050Error
    from asmr_memory_system.dr_claw_search import DrClawSearchOrchestrator

    bridge = Port5050Bridge(api_url=PORT_5050_URL)
    try:
        core_engine = ASMRParallelOrchestrator(llm_async_callable=local_gemma_call)
        dr_claw = DrClawSearchOrchestrator(orchestrator=core_engine, bridge=bridge)
        result = await dr_claw.analyze_from_5050_memory(question)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Port5050Error as e:
        print(f"ASMR ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        await bridge.close()
        await _cleanup()

async def cmd_core_memory(action: str, content: str = None):
    """Core Memory 조회 및 업데이트"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if action == "get":
                resp = await client.get(f"{PORT_5050_URL}/core-memory")
                if resp.status_code == 200:
                    data = resp.json()
                    print(data.get("content", ""))
                    return 0
                else:
                    print(f"ERROR: HTTP {resp.status_code}", file=sys.stderr)
                    return 1
            elif action == "update" and content is not None:
                resp = await client.post(f"{PORT_5050_URL}/core-memory", json={"content": content})
                if resp.status_code == 200:
                    data = resp.json()
                    print(json.dumps({"status": "updated", "length": data.get("length")}, ensure_ascii=False))
                    return 0
                else:
                    print(f"ERROR: HTTP {resp.status_code}", file=sys.stderr)
                    return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

async def cmd_observe(log_text: str):
    """세션 로그를 ASMR Observer 3인방으로 분석 + 자동 ingest"""
    from asmr_memory_system.core import ASMRParallelOrchestrator
    from asmr_memory_system.port_5050_bridge import Port5050Bridge, Port5050Error
    from asmr_memory_system.luca_observer import LucaMemoryObserver

    bridge = Port5050Bridge(api_url=PORT_5050_URL)
    try:
        core_engine = ASMRParallelOrchestrator(llm_async_callable=local_gemma_call)
        observer = LucaMemoryObserver(orchestrator=core_engine, bridge=bridge)
        result = await observer.process_session_log(log_text)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Port5050Error as e:
        print(f"ASMR ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        await bridge.close()
        await _cleanup()


async def cmd_ontology(question: str):
    """온톨로지 지식그래프 탐색 (Edge Interpreter + Pathfinder + Arbiter)"""
    from asmr_memory_system.core import ASMRParallelOrchestrator
    from asmr_memory_system.port_5050_bridge import Port5050Bridge, Port5050Error
    from asmr_memory_system.ontology_asmr import OntologyASMRSearcher

    bridge = Port5050Bridge(api_url=PORT_5050_URL)
    try:
        core_engine = ASMRParallelOrchestrator(llm_async_callable=local_gemma_call)
        searcher = OntologyASMRSearcher(orchestrator=core_engine, bridge=bridge)
        result = await searcher.traverse_from_5050_memory(question)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Port5050Error as e:
        print(f"ASMR ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        await bridge.close()
        await _cleanup()


# ─── Phase 1-3 직접 API 커맨드 ───────────────────────────────────

async def cmd_search(query: str, top_k: int = 5):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{PORT_5050_URL}/search", json={"query": query, "top_k": top_k})
        data = resp.json().get("result", {})
        print(f"\n🔍 Semantic Search: '{query}' (searched {data.get('total_searched',0)} memories)")
        for i, r in enumerate(data.get("results", []), 1):
            print(f"  [{i}] #{r['id']} sim={r['similarity']:.3f} imp={r['importance']:.2f} [{r['agent_id']}]")
            print(f"      {r['summary']}")
    return 0

async def cmd_context(topic: str):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{PORT_5050_URL}/context", json={"topic": topic})
        data = resp.json().get("result", {})
        print(f"\n🧠 Proactive Context: '{topic}'")
        print(f"  Semantic ({len(data.get('semantic_memories',[]))}): " +
              " | ".join(f"#{m['id']}" for m in data.get("semantic_memories", [])))
        for c in data.get("causal_chains", []):
            print(f"  🔗 {c.get('cause','')[:50]} → {c.get('effect','')[:50]}")
        for r in data.get("recent_important", []):
            print(f"  ⚡ #{r['id']} imp={r['importance']:.2f} {r['summary'][:70]}")
    return 0

async def cmd_reason(topic: str):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{PORT_5050_URL}/reason", json={"topic": topic})
        data = resp.json().get("result", {})
        print(f"\n⏳ Cross-Time Reasoning: '{topic}'")
        print(f"  Trend: {data.get('trend','?')} | Total: {data.get('total',0)} | {data.get('oldest','?')} → {data.get('latest','?')}")
        print(f"  Windows: {data.get('by_time_window',{})}")
        for t in data.get("timeline", [])[-5:]:
            print(f"  [{t['date']}] {t['summary'][:70]}")
    return 0

async def cmd_predict(context_text: str):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{PORT_5050_URL}/predict", json={"context": context_text})
        data = resp.json().get("result", {})
        print(f"\n🔮 Predicted Memories (method: {data.get('method','?')})")
        for m in data.get("predicted", []):
            print(f"  - #{m['id']} {m['summary'][:80]}")
    return 0

async def cmd_causal(keyword: str = None):
    async with httpx.AsyncClient(timeout=30) as client:
        body = {"keyword": keyword} if keyword else {}
        resp = await client.post(f"{PORT_5050_URL}/causal", json=body)
        data = resp.json().get("result", {})
        print(f"\n🔗 Causal Chains ({data.get('count',0)}):")
        for c in data.get("chains", []):
            print(f"  #{c.get('from_memory_id','?')} → #{c.get('to_memory_id','?')} (conf={c.get('confidence',0):.2f})")
            print(f"    {c.get('from_summary','')[:60]} → {c.get('to_summary','')[:60]}")
    return 0

async def cmd_stats():
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{PORT_5050_URL}/stats")
        s = resp.json().get("result", {})
        print(f"\n📊 Luca Brain Stats:")
        for k, v in s.items():
            print(f"  {k}: {v}")
    return 0


# ─── CLI 엔트리포인트 ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Claude Code <-> Luca Brain Memory Bridge v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="서버 상태 확인")
    sub.add_parser("stats",  help="[Phase1-3] 메모리 시스템 통계")

    p = sub.add_parser("raw-query", help="Port 5050 직접 쿼리")
    p.add_argument("question", type=str)

    p = sub.add_parser("query", help="ASMR 3인방 분석")
    p.add_argument("question", type=str)

    p = sub.add_parser("ingest", help="공유 메모리에 저장")
    p.add_argument("text", type=str)

    p = sub.add_parser("observe", help="세션 로그 분석 + ingest")
    p.add_argument("log", type=str)

    p = sub.add_parser("ontology", help="온톨로지 지식그래프 탐색")
    p.add_argument("question", type=str)

    p = sub.add_parser("search",  help="[Phase1] 벡터 시맨틱 검색")
    p.add_argument("query", type=str)
    p.add_argument("--top-k", type=int, default=5, dest="top_k")

    p = sub.add_parser("context", help="[Phase2] 능동적 컨텍스트 로드")
    p.add_argument("topic", type=str)

    p = sub.add_parser("reason",  help="[Phase3] 크로스타임 추론")
    p.add_argument("topic", type=str)

    p = sub.add_parser("predict", help="[Phase3] 다음 기억 예측")
    p.add_argument("context_text", type=str)

    p = sub.add_parser("causal",  help="[Phase2] 인과관계 체인 조회")
    p.add_argument("keyword", type=str, nargs="?", default=None)

    p = sub.add_parser("core-memory", help="Core Memory 관리")
    p.add_argument("action", choices=["get", "update"], help="get 또는 update")
    p.add_argument("content", type=str, nargs="?", default=None, help="update 시 내용")

    args = parser.parse_args()

    cmd_map = {
        "health":    lambda: cmd_health(),
        "stats":     lambda: cmd_stats(),
        "raw-query": lambda: cmd_raw_query(args.question),
        "query":     lambda: cmd_query(args.question),
        "ingest":    lambda: cmd_ingest(args.text),
        "observe":   lambda: cmd_observe(args.log),
        "ontology":  lambda: cmd_ontology(args.question),
        "search":    lambda: cmd_search(args.query, args.top_k),
        "context":   lambda: cmd_context(args.topic),
        "reason":    lambda: cmd_reason(args.topic),
        "predict":   lambda: cmd_predict(args.context_text),
        "causal":    lambda: cmd_causal(args.keyword),
        "core-memory": lambda: cmd_core_memory(args.action, args.content)
    }

    handler = cmd_map.get(args.command)
    if handler:
        exit_code = asyncio.run(handler())
    else:
        parser.print_help()
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
