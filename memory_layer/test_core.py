import asyncio
import os

from dotenv import load_dotenv

load_dotenv()
# (If GEMINI_API_KEY is not in .env, ensure it is set properly using the user's .env configuration)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from core import build_memory_agents, get_db

async def test_memory():
    # 1. Clear DB for a clean test
    db = get_db()
    db.execute("DELETE FROM memories")
    db.execute("DELETE FROM consolidations")
    db.commit()
    db.close()
    
    # 2. Setup the orchestrator
    agent = build_memory_agents()
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="test_memory", session_service=session_service)
    
    session = await session_service.create_session(app_name="test_memory", user_id="tester")
    
    # helper for running questions
    async def ask(msg: str):
        print(f"\n🗣️ USER: {msg}")
        content = types.Content(role="user", parts=[types.Part.from_text(text=msg)])
        print("🤖 AGENT: ", end="", flush=True)
        async for event in runner.run_async(user_id="tester", session_id=session.id, new_message=content):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        print(part.text, end="", flush=True)
        print()

    # 3. Test Ingestion
    await ask("Please remember this: My dog's name is Max, and he loves eating carrots.")
    await ask("Also, I have an important meeting tomorrow at 10 AM with the marketing team about the new hospital CRM.")
    
    # 4. Check raw SQLite output visually
    db = get_db()
    print("\n--- SQLite Raw Memories ---")
    for r in db.execute("SELECT id, summary, entities, topics FROM memories").fetchall():
        print(dict(r))
    db.close()
    
    # 5. Test Query
    await ask("What is my dog's name and what does he eat?")
    await ask("What is my schedule for tomorrow?")
    
    # 6. Test Consolidation
    await ask("Please run consolidation on my recent unconsolidated memories.")
    
    # 7. Check raw Consolidations visually
    db = get_db()
    print("\n--- SQLite Consolidations ---")
    for r in db.execute("SELECT id, summary, insight FROM consolidations").fetchall():
        print(dict(r))
    db.close()

if __name__ == "__main__":
    # Ensure google.adk and google.genai are installed
    # Run: pip install google-genai google-adk
    asyncio.run(test_memory())
