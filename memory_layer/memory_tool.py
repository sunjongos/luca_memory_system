import sys
import requests
import json

SERVER_URL = "http://localhost:5050"

def ingest(text):
    try:
        response = requests.post(f"{SERVER_URL}/ingest", json={"text": text}, timeout=120)
        response.raise_for_status()
        print(f"Ingested: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"Ingestion failed: {e}")

def query(question):
    try:
        response = requests.post(f"{SERVER_URL}/query", json={"question": question}, timeout=120)
        response.raise_for_status()
        print(f"Query Result:\n{response.json().get('result', 'No result')}")
    except Exception as e:
        print(f"Query failed: {e}")

def consolidate():
    try:
        response = requests.post(f"{SERVER_URL}/consolidate", timeout=120)
        response.raise_for_status()
        print(f"Consolidation triggered: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"Consolidation failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python memory_cli.py [ingest|query|consolidate] [text/question]")
        sys.exit(1)

    command = sys.argv[1]
    
    if command == "ingest" and len(sys.argv) > 2:
        ingest(sys.argv[2])
    elif command == "query" and len(sys.argv) > 2:
        query(sys.argv[2])
    elif command == "consolidate":
        consolidate()
    else:
        print("Invalid command or missing arguments.")
