# Luca Memory System 🧠

Luca Memory System은 에이전트(Claude Code, Antigravity, OpenClaw 등)가 다중 테넌트(Multi-Tenancy) 환경에서 컨텍스트를 유지하고, 장기적인 기억과 추론을 수행할 수 있도록 설계된 **4-Tier 메모리 아키텍처**입니다. 

## 🌟 주요 아키텍처 (4-Tier)

1. **Core / Working Memory (단기 기억)**
   - 에이전트가 현재 작업 중인 핵심 컨텍스트, 대표님의 지시 사항을 기록합니다.
   - 글자 수 제한(예: 2000자)을 통해 토큰 효율을 극대화합니다.
   - CLI 명령어(`core-memory get/update`)를 통해 여러 서브 에이전트 간 즉각적인 상태 동기화가 가능합니다.

2. **Persistent Shared Memory (장기 기억 / 포트 5050)**
   - 로컬 파일 시스템 의존성을 탈피하고, 통합된 데이터베이스(`SQLite`, `Supabase` 연동)에 모든 기억과 지식을 보관합니다.
   - REST API 엔드포인트를 제공하여 어떤 에이전트든 통신할 수 있습니다.

3. **Hybrid GraphRAG (시맨틱 & 온톨로지 결합)**
   - 단순 벡터 유사도를 넘어서, 지식 그래프(Ontology)와 연결된 개체 관계를 분석하여 풍부한 컨텍스트를 제공합니다.
   - `gemini-3.0-flash` (또는 `gemini-2.5-flash`) 모델을 통해 메모리 조각들의 연관성을 추론합니다.

4. **ASMR (Automated Session Memory Recall) & Conflict Resolution**
   - 로컬 오프라인 모델(Local Gemma 기반 Ollama)을 활용하여, 외부 API 의존 없이 보안성을 유지한 채 로그를 요약하고 핵심 기억을 추출합니다.
   - 백그라운드 스레드에서 주기적으로 충돌 해소(Conflict Resolution) 알고리즘이 동작하여, 모순되거나 오래된 기억을 벡터 유사도 기반으로 자동 정리(`status='superseded'`)합니다.

## 🚀 구성 요소

- `memory_layer/` : 5050 포트로 실행되는 Flask 기반 메모리 백엔드 서버 및 Core 로직 (Gemini API 연동).
- `shared/claude_memory_bridge.py` : 각 에이전트(꼬봉이들)가 CLI 환경에서 메모리 서버와 통신할 수 있도록 돕는 Python 브릿지 스크립트.
- `skills/` : 에이전트 프롬프트 스킬 명세 및 ASMR 파이프라인.

## 🛠️ 사용 방법

### 1. 서버 시작 (PM2 권장)
```bash
pm2 start memory_layer/memory_server.py --name memory-server
```

### 2. 브릿지(Bridge) CLI 활용
```bash
# 서버 헬스 체크
python shared/claude_memory_bridge.py health

# Core Memory (단기 작업 컨텍스트) 조회 및 업데이트
python shared/claude_memory_bridge.py core-memory get
python shared/claude_memory_bridge.py core-memory update "현재 프로젝트는 A단계 진행 중"

# 장기 메모리 시맨틱 검색 (Phase 1)
python shared/claude_memory_bridge.py search "최근 검색된 키워드"

# 능동적 컨텍스트 로드 및 크로스 타임 추론 (Phase 2 & 3)
python shared/claude_memory_bridge.py context "리서치 주제"
python shared/claude_memory_bridge.py reason "투자 트렌드"
```

## 🔒 보안 및 프라이버시

- 로컬 오프라인 기반의 ASMR(`local_gemma_call`)을 사용하여, 민감한 로그 정보가 외부 API로 노출되는 것을 방지합니다.
- `user_id` 및 `session_id` 기반의 멀티 테넌시(Multi-Tenancy) 구조를 통해 여러 환경(병원 진료실, 자택 등) 간의 데이터가 철저하게 격리됩니다.
