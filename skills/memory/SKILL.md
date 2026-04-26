---
name: Luca Memory System
description: Luca가 대표님의 선호, 프로젝트 컨텍스트, 중요 정보를 장기 기억으로 저장하고 불러오는 스킬입니다.
---

# 🧠 Luca Memory System — 장기 기억 관리

Luca가 대화 세션을 넘어 **중요 정보를 기억**하는 스킬입니다.
대표님의 선호, 반복 사용 명령, 프로젝트 컨텍스트, 중요 결정사항을 저장합니다.

## 📌 언제 사용하나
- 대표님이 "이거 기억해둬" 라고 할 때
- 자주 반복되는 설정, 선호, 정보를 저장할 때
- 프로젝트 시작 시 배경 맥락을 저장할 때
- 다음 세션에도 유지되어야 하는 결정사항이 있을 때

## 🏷️ 기억 카테고리

| 카테고리 | 설명 |
|----------|------|
| `general` | 일반 정보 (기본값) |
| `preference` | 대표님 선호 및 작업 스타일 |
| `project` | 프로젝트별 컨텍스트 |
| `contact` | 중요 연락처 및 관계 |
| `decision` | 주요 결정사항 |

## 🛠️ 실행 방법

```powershell
# 기억 저장
python .agent/skills/memory/memory_manager.py save "key" "value" --category project

# 기억 조회
python .agent/skills/memory/memory_manager.py get "key"

# 전체 목록
python .agent/skills/memory/memory_manager.py list

# 카테고리별 조회
python .agent/skills/memory/memory_manager.py list --category preference

# 요약
python .agent/skills/memory/memory_manager.py summary

# 삭제
python .agent/skills/memory/memory_manager.py delete "key"
```

## 💡 Luca 적용 원칙
- 대표님이 "기억해줘"라고 하면 즉시 `save` 실행
- 새 세션 시작 시 `summary`로 컨텍스트 파악
- 관련 기억이 있으면 `get`으로 불러와 브리핑에 활용
