import json
import sys
from pathlib import Path
sys.path.insert(0, 'C:/Users/Acer/.local/share/opencode/minimax-workspace/lib')

from networkx.readwrite import json_graph
from graphify.build import build_from_json
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate

# Load graph from graphify-out/graph.json
with open('graphify-out/graph.json') as f:
    data = json.load(f)

G = json_graph.node_link_graph(data, edges='links')

# Get communities
communities = {}
for node in G.nodes():
    comm = G.nodes[node].get('community')
    if comm is not None:
        communities.setdefault(comm, []).append(node)

# Simple labels for top communities
labels = {
    0: 'Python A2A Helpers',
    1: 'Adyen Payment Integration',
    2: 'A2A Protocol Types',
    3: 'Go Server Main',
    4: 'Mandate Signing',
    5: 'Go Agent Executors',
    6: 'Agent Runner',
    7: 'Crypto Primitives',
    8: 'Catalog & Products',
    9: 'Go Mandates',
    10: 'Kotlin A2A Client',
    11: 'Kotlin Shopping Types',
    12: 'Demo Code',
    13: 'Key Management',
    14: 'Session Storage',
    15: 'Auth Tokens',
    16: 'Go Types',
    17: 'Kotlin Shopping Tools',
    18: 'Kotlin DPC Types',
    19: 'Storage',
}

# Add numbered labels for rest
for i in range(20, len(communities)):
    labels[i] = f'Component {i}'

gods = god_nodes(G)
surprises = surprising_connections(G, communities)
questions = suggest_questions(G, communities, labels)

detection = {'total_files': 186, 'total_words': 117454, 'files': {'code': [133], 'document': [32], 'image': [21]}, 'needs_graph': True}

report = generate(G, communities, {}, labels, gods, surprises, detection, {'input': 0, 'output': 0}, '.', suggested_questions=questions)

with open('graphify-out/GRAPH_REPORT.md', 'w', encoding='utf-8') as f:
    f.write(report)

print(f'Report regenerated: {len(labels)} communities labeled')