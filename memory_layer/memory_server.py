from flask import Flask, request, jsonify
import asyncio
import os
import sys
import io
import time
import threading
import traceback

# Fix cp949 encoding on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded to prevent hardcoding leaks
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path, override=True)

# Inject API key globally for ADK if missing in env
if "GEMINI_API_KEY" not in os.environ and "GOOGLE_API_KEY" in os.environ:
    os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]
elif "GEMINI_API_KEY" not in os.environ:
    raise ValueError("GEMINI_API_KEY is not set in the environment or .env file.")

from core import (
    build_memory_agents,
    semantic_search, get_proactive_context, query_causal_chains,
    predict_next_memories, cross_time_reasoning, get_memory_stats,
    apply_temporal_decay, store_causal_chain, resolve_memory_conflicts,
    get_core_memory, update_core_memory, sync_from_supabase
)
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


# ── API Error Alerting ─────────────────────────────────────────────────────
def check_api_error_and_alert(e):
    err_str = str(e).lower()
    if '429' in err_str or 'quota' in err_str or 'exhausted' in err_str or 'billing' in err_str:
        print("\n" + "="*60)
        print("🚨 [CRITICAL] GEMINI API BILLING OR QUOTA LIMIT REACHED! 🚨")
        print("="*60 + "\n")
        import time
        now = time.time()
        if not hasattr(check_api_error_and_alert, 'last_alert') or (now - getattr(check_api_error_and_alert, 'last_alert', 0) > 600):
            check_api_error_and_alert.last_alert = now
            try:
                import webbrowser
                webbrowser.open("https://console.cloud.google.com/billing")
            except:
                pass
            import sys
            if sys.platform == "win32":
                import threading
                import ctypes
                def show_popup():
                    ctypes.windll.user32.MessageBoxW(0, "Gemini API 호출 한도 초과 (Billing/Quota Limit)\n\nGoogle Cloud Console 결제 상태를 확인하세요.\n브라우저에 결제 페이지를 띄웠습니다.", "Luca ASMR Memory Server - 결제 경고", 0x10 | 0x0)
                threading.Thread(target=show_popup, daemon=True).start()

app = Flask(__name__)

# ── Rate Limiting ──────────────────────────────────────────────────────────
MAX_CALLS_PER_HOUR = 300
call_records = []

def check_rate_limit():
    global call_records
    now = time.time()
    call_records = [t for t in call_records if now - t < 3600]
    if len(call_records) >= MAX_CALLS_PER_HOUR:
        raise Exception("Rate limit exceeded (300/hr)")
    call_records.append(now)

# ── Persistent Async Loop (FIXED - no more new_event_loop per request) ─────
_bg_loop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True, name="luca-async-loop")
_bg_thread.start()

def run_async(coro):
    """Submit coroutine to persistent background event loop (thread-safe)."""
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout=120)

# ── ADK Memory Agent ───────────────────────────────────────────────────────
class MemoryAgent:
    def __init__(self):
        self.agent = build_memory_agents()
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=self.agent,
            app_name="luca_memory_layer",
            session_service=self.session_service,
        )

    async def run(self, message: str) -> str:
        session = await self.session_service.create_session(
            app_name="luca_memory_layer", user_id="luca_bot",
        )
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
        response = ""
        async for event in self.runner.run_async(
            user_id="luca_bot", session_id=session.id, new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response += part.text
        return response

memory_agent = MemoryAgent()

# ── Existing Endpoints ─────────────────────────────────────────────────────
@app.route('/ingest', methods=['POST'])
def ingest():
    try:
        check_rate_limit()
        data = request.json
        text = data.get('text')
        if not text:
            return jsonify({"error": "text is required"}), 400
        agent_id = data.get('agent_id', 'ClaudeCode')
        msg = f"Remember this information (agent: {agent_id}):\n\n{text}"
        result = run_async(memory_agent.run(msg))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/query', methods=['POST'])
def query():
    try:
        check_rate_limit()
        data = request.json
        question = data.get('question')
        if not question:
            return jsonify({"error": "question is required"}), 400
        msg = f"Query memory: {question}"
        print("DEBUG: /query called. GEMINI_API_KEY =", os.environ.get("GEMINI_API_KEY"))
        import google.genai
        print("DEBUG: google_genai fallback exists?", hasattr(google.genai, '_api_client'))
        result = run_async(memory_agent.run(msg))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/consolidate', methods=['POST'])
def consolidate():
    try:
        result = run_async(memory_agent.run("Consolidate all recent unconsolidated memories now."))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e)}), 500

# ── Phase 1: Semantic Search ───────────────────────────────────────────────
@app.route('/search', methods=['POST'])
def search():
    try:
        data = request.json
        query_text = data.get('query')
        if not query_text:
            return jsonify({"error": "query is required"}), 400
        top_k    = int(data.get('top_k', 5))
        agent_id = data.get('agent_id')
        result = semantic_search(query_text, top_k=top_k, agent_id=agent_id)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/decay', methods=['POST'])
def decay():
    try:
        data = request.json or {}
        result = apply_temporal_decay(memory_id=data.get('memory_id'))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e)}), 500

# ── Phase 2: Proactive Context + Causal Chains ────────────────────────────
@app.route('/context', methods=['POST'])
def context():
    try:
        data = request.json
        topic = data.get('topic')
        if not topic:
            return jsonify({"error": "topic is required"}), 400
        top_k = int(data.get('top_k', 7))
        result = get_proactive_context(topic, top_k=top_k)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/causal', methods=['POST'])
def causal():
    try:
        data = request.json or {}
        result = query_causal_chains(
            memory_id=data.get('memory_id'),
            keyword=data.get('keyword')
        )
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e)}), 500

@app.route('/causal/store', methods=['POST'])
def causal_store():
    try:
        data = request.json
        result = store_causal_chain(
            from_memory_id=data['from_memory_id'],
            to_memory_id=data['to_memory_id'],
            cause_description=data['cause_description'],
            effect_description=data['effect_description'],
            confidence=data.get('confidence', 0.7),
            agent_id=data.get('agent_id', 'ClaudeCode')
        )
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e)}), 500

# ── Phase 3: Prediction + Cross-Time Reasoning ────────────────────────────
@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.json
        context_text = data.get('context')
        if not context_text:
            return jsonify({"error": "context is required"}), 400
        top_k = int(data.get('top_k', 5))
        result = predict_next_memories(context_text, top_k=top_k)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/reason', methods=['POST'])
def reason():
    try:
        data = request.json
        topic = data.get('topic')
        if not topic:
            return jsonify({"error": "topic is required"}), 400
        result = cross_time_reasoning(topic)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/stats', methods=['GET'])
def stats():
    try:
        result = get_memory_stats()
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e)}), 500

@app.route('/core-memory', methods=['GET', 'POST'])
def core_memory():
    try:
        if request.method == 'GET':
            user_id = request.args.get('user_id', 'default_user')
            session_id = request.args.get('session_id', 'default_session')
            agent_id = request.args.get('agent_id', 'system')
            content = get_core_memory(user_id, session_id, agent_id)
            return jsonify({"status": "success", "content": content})
        elif request.method == 'POST':
            data = request.json
            user_id = data.get('user_id', 'default_user')
            session_id = data.get('session_id', 'default_session')
            agent_id = data.get('agent_id', 'system')
            content = data.get('content', '')
            res = update_core_memory(user_id, session_id, agent_id, content)
            return jsonify(res)
    except Exception as e:
        check_api_error_and_alert(e)
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

# ── Health Check ───────────────────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    s = get_memory_stats()
    return jsonify({
        "status": "ok",
        "port": 5050,
        "total_memories": s.get("total", 0),
        "with_embeddings": s.get("with_embedding", 0),
        "causal_chains": s.get("causal_chains", 0),
        "endpoints": ["/ingest", "/query", "/search", "/context", "/causal",
                      "/predict", "/reason", "/decay", "/consolidate", "/stats", "/health"]
    })

# ── Background Jobs ────────────────────────────────────────────────────────
def background_consolidation_loop():
    while True:
        try:
            time.sleep(3600)
            print("[Auto-Consolidation] Triggering hourly consolidation...")
            run_async(memory_agent.run("Consolidate all recent unconsolidated memories now."))
            
            print("[Auto-Resolution] Resolving memory conflicts...")
            res = resolve_memory_conflicts()
            if res.get("resolved_count", 0) > 0:
                print(f"   => Resolved {res['resolved_count']} conflicting memories.")
        except Exception as e:
            check_api_error_and_alert(e)
        check_api_error_and_alert(e)
            print(f"[Auto-Consolidation Error] {e}")

def background_decay_loop():
    while True:
        try:
            time.sleep(21600)  # 6시간마다 감쇠 적용
            print("[Auto-Decay] Applying temporal decay...")
            apply_temporal_decay()
        except Exception as e:
            check_api_error_and_alert(e)
        check_api_error_and_alert(e)
            print(f"[Auto-Decay Error] {e}")

if __name__ == '__main__':
    print("🔄 초기화 중: 외부 장기 메모리(Supabase) 동기화...")
    sync_from_supabase()

    threading.Thread(target=background_consolidation_loop, daemon=True).start()
    threading.Thread(target=background_decay_loop, daemon=True).start()
    print("🚀 Luca World-Best Memory Server v2.0 on port 5050")
    print("   Endpoints: /ingest /query /search /context /causal /predict /reason /stats /health /core-memory")
    app.run(host='0.0.0.0', port=5050)
