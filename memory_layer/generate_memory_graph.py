import requests
import json
import re
import os
import webbrowser
import sys

MEMORY_SERVER_URL = "http://127.0.0.1:5050/query"

def get_prompt(topic=None):
    if topic:
        focus = f"'{topic}'(와)과 관련된 모든 정보 중심(중점이 되는)으로 집중 분석하여 장기 기억 속 개념들을 추출해서"
    else:
        focus = "지금까지 저장된 모든 장기 기억 데이터와 전반적인 핵심 개념들을 추출해서"

    return f"""
당신은 현재 장기 기억 망 내부의 데이터와 지식을 분석하는 지식그래프 에이전트입니다. 
{focus} Obsidian 스타일의 지식 그래프를 구성해주세요.
핵심 개념/주제/인물 등을 '노드(nodes)'로 구성하고, 그들 간의 연관성과 맥락을 방향성 있는 네트워크 '엣지(edges)'로 연결하세요.

반드시 아래의 JSON 포맷으로만 응답해야 하며, 다른 설명은 포함하지 마세요.
group 속성에는 노드의 카테고리(예: 인물, 기술, 프로젝트, 역할, 목표, 아이디어 등)를 지정해주세요.

```json
{{
  "nodes": [
    {{"id": 1, "label": "개념1", "group": "카테고리명"}},
    {{"id": 2, "label": "개념2", "group": "카테고리명"}}
  ],
  "edges": [
    {{"from": 1, "to": 2, "label": "관계 설명"}}
  ]
}}
```
"""

def fetch_memory_graph(topic=None):
    if topic:
        print(f"⏳ 요청 중... '{topic}' 관련 지식 그래프 데이터를 추출하고 있습니다...")
    else:
        print("⏳ 요청 중... 전체 장기 기억 지식 그래프 데이터를 추출하고 있습니다...")
        
    prompt = get_prompt(topic)
    try:
        response = requests.post(MEMORY_SERVER_URL, json={"question": prompt}, timeout=120)
        response.raise_for_status()
        result = response.json().get("result", "")
        
        # Extract JSON
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', result, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'(\{.*\})', result, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = result
        
        graph_data = json.loads(json_str)
        return graph_data
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        try:
            print(f"RAW 응답 내용:\n{result}\n")
        except:
            pass
        print("💡 기본(Default) 데모 데이터를 사용하여 그래프를 렌더링합니다.")
        return {
            "nodes": [
                {"id": 1, "label": "Luca 에이전트", "group": "AI"},
                {"id": 2, "label": "장기 기억", "group": "System"}
            ],
            "edges": [
                {"from": 1, "to": 2, "label": "소유함"}
            ]
        }

def generate_html(graph_data, title="Luca Memory Graph"):
    html_template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #1e1e1e;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: #d3d3d3;
            overflow: hidden;
        }}
        #mynetwork {{
            width: 100vw;
            height: 100vh;
            border: none;
        }}
        #loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 1.2rem;
            color: #a9b7c6;
            display: none;
        }}
        .header-title {{
            position: absolute;
            top: 20px;
            left: 20px;
            z-index: 10;
            background: rgba(30, 30, 30, 0.85);
            padding: 15px 25px;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5);
            border: 1px solid #444;
            backdrop-filter: blur(5px);
        }}
        .header-title h1 {{
            margin: 0;
            font-size: 1.4rem;
            color: #ffffff;
            font-weight: 600;
        }}
        .header-title p {{
            margin: 8px 0 0 0;
            font-size: 0.9rem;
            color: #aaaaaa;
        }}
    </style>
</head>
<body>
    <div class="header-title">
        <h1>✨ {title}</h1>
        <p>Obsidian Style Knowledge Network</p>
    </div>
    <div id="loading">그래프 렌더링 중...</div>
    <div id="mynetwork"></div>

    <script type="text/javascript">
        const graphData = {json.dumps(graph_data)};
        
        const nodes = new vis.DataSet(graphData.nodes.map(node => ({{
            ...node,
            title: node.group ? `분류: ${{node.group}}` : ''
        }})));
        
        const edges = new vis.DataSet(graphData.edges.map(edge => ({{
            ...edge,
            font: {{ align: 'middle', color: '#888', size: 11, background: '#1e1e1e' }},
            arrows: 'to',
            color: {{ color: '#555', highlight: '#aaa' }}
        }})));

        const container = document.getElementById('mynetwork');
        const data = {{ nodes: nodes, edges: edges }};
        const options = {{
            nodes: {{
                shape: 'dot',
                size: 18,
                font: {{ color: '#f0f0f0', size: 14, face: 'Segoe UI', strokeWidth: 1, strokeColor: '#111' }},
                borderWidth: 2,
                color: {{
                    border: '#2b2b2b',
                    background: '#6a4ca6', 
                    highlight: {{ border: '#ffffff', background: '#9d7bea' }},
                    hover: {{ border: '#ffffff', background: '#9d7bea' }}
                }}
            }},
            edges: {{
                width: 1.5,
                smooth: {{ type: 'continuous' }}
            }},
            physics: {{
                forceAtlas2Based: {{
                    gravitationalConstant: -70,
                    centralGravity: 0.015,
                    springLength: 120,
                    springConstant: 0.08
                }},
                maxVelocity: 50,
                solver: 'forceAtlas2Based',
                timestep: 0.35,
                stabilization: {{ iterations: 150 }}
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 100,
                hideEdgesOnDrag: true
            }},
            groups: {{
                "인물": {{ color: {{ background: '#c45151', border: '#4c2323' }} }},
                "역할": {{ color: {{ background: '#d4883f', border: '#5c3a1b' }} }},
                "프로젝트": {{ color: {{ background: '#4ca66b', border: '#234c31' }} }},
                "기술": {{ color: {{ background: '#488cb8', border: '#20475f' }} }},
                "목표": {{ color: {{ background: '#c1ad4d', border: '#5b5123' }} }}
            }}
        }};

        const network = new vis.Network(container, data, options);
    </script>
</body>
</html>
"""
    return html_template

def main():
    args = sys.argv[1:]
    topic = " ".join(args) if args else None
    
    graph_data = fetch_memory_graph(topic)
    
    title = f"'{topic}' Focus Graph" if topic else "🌌 Luca Global Memory Graph"
    html_content = generate_html(graph_data, title=title)
    
    # Use topic in filename to not overwrite the global one
    filename = f"memory_graph_{topic.replace(' ', '_')}.html" if topic else "memory_graph.html"
    output_path = os.path.join(os.path.dirname(__file__), filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✅ 그래프가 생성되었습니다: {output_path}")
    print("🌐 브라우저에서 그래프를 엽니다...")
    webbrowser.open(f"file://{os.path.abspath(output_path)}")

if __name__ == "__main__":
    main()
