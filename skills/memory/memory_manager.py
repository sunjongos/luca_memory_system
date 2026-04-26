"""
Luca Memory System — 공유 장기 기억 관리 클라이언트 (Port 5050)
기존의 로컬 memory.json 방식을 폐기하고, 중앙 관제탑(Port 5050) 및 OneDrive 기반 
Shared Memory Server와 통신합니다.

사용법:
  python memory_manager.py save "주제" "내용"
  python memory_manager.py get "질문"
  python memory_manager.py query "질문"
"""

import sys
import argparse
import requests

API_URL = "http://localhost:5050"
AGENT_ID = "Luca"

def cmd_save(key: str, value: str):
    text = f"주제: {key}\n내용: {value}"
    try:
        res = requests.post(f"{API_URL}/ingest", json={"text": text, "agent_id": AGENT_ID})
        if res.status_code == 200:
            print(f"✅ 기억 저장 완료 [{AGENT_ID}]:\n{text}")
        else:
            print(f"❌ 저장 실패 (상태 코드 {res.status_code}): {res.text}")
    except requests.exceptions.ConnectionError:
        print(f"❌ 메모리 서버(Port 5050)에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.")
    except Exception as e:
        print(f"❌ 서버 연결 실패: {e}")

def cmd_query(question: str):
    try:
        res = requests.post(f"{API_URL}/query", json={"question": question, "agent_id": AGENT_ID})
        if res.status_code == 200:
            data = res.json()
            print(f"🧠 [초거대 공유 기억망 응답 - {AGENT_ID}]:\n{data.get('result', '')}")
        else:
            print(f"❌ 조회 실패 (상태 코드 {res.status_code}): {res.text}")
    except requests.exceptions.ConnectionError:
        print(f"❌ 메모리 서버(Port 5050)에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.")
    except Exception as e:
        print(f"❌ 서버 연결 실패: {e}")

def main():
    parser = argparse.ArgumentParser(description="Luca 공유 장기 기억 관리 도구 (Port 5050 API)")
    subparsers = parser.add_subparsers(dest="command")

    # save 명령어
    p_save = subparsers.add_parser("save", help="새로운 기억 저장 (ingest)")
    p_save.add_argument("key", help="기억의 주제(또는 키)")
    p_save.add_argument("value", help="실제 기억할 내용")
    p_save.add_argument("--category", default="general", help="역호환성 구문")

    # query / get 명령어 (동일 기능 수행)
    p_query = subparsers.add_parser("query", help="공유 메모리 체인에 질문하여 답 얻기")
    p_query.add_argument("question", help="기억해내야 하는 내용 / 질문")

    p_get = subparsers.add_parser("get", help="query와 동일하게 공유 메모리에 질문하기")
    p_get.add_argument("key", help="기억해내야 하는 내용 / 질문")

    # 기존 명령어들 무시 및 안내 (호환성)
    p_list = subparsers.add_parser("list", help="Not Supported on Shared DB")
    p_list.add_argument("--category", default=None)
    
    p_del = subparsers.add_parser("delete", help="Not Supported on Shared DB")
    p_del.add_argument("key", help="키")

    p_sum = subparsers.add_parser("summary", help="Not Supported on Shared DB")

    args = parser.parse_args()

    if args.command == "save":
        cmd_save(args.key, args.value)
    elif args.command in ["query", "get"]:
        question = getattr(args, "question", getattr(args, "key", ""))
        print(f"🔍 서버(Port 5050)에서 기억을 찾는 중입니다. 잠시만 기다려주세요...")
        cmd_query(question)
    elif args.command in ["list", "delete", "summary"]:
        print(f"⚠️ Shared Memory System에서는 '{args.command}' 명령어를 클라이언트에서 직접 지원하지 않습니다. AI 쿼리를 통해 질문하세요.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
