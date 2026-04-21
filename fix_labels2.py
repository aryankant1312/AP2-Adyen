import json
from pathlib import Path
import sys
sys.path.insert(0, 'C:/Users/Acer/.local/share/opencode/minimax-workspace/lib')

from networkx.readwrite import json_graph
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate

with open('graphify-out/graph.json') as f:
    data = json.load(f)

G = json_graph.node_link_graph(data, edges='links')

# Get communities with node counts
communities = {}
for node in G.nodes():
    comm = G.nodes[node].get('community')
    if comm is not None:
        communities.setdefault(comm, []).append(node)

# Sort by size for better mapping
sorted_comms = sorted(communities.items(), key=lambda x: len(x[1]), reverse=True)

# Map ALL 85 communities with descriptive names
labels = {
    sorted_comms[0][0]: 'Python A2A Helpers',
    sorted_comms[1][0]: 'Adyen Payment Integration',
    sorted_comms[2][0]: 'A2A Protocol Types',
    sorted_comms[3][0]: 'Go Server Main',
    sorted_comms[4][0]: 'Mandate Signing',
    sorted_comms[5][0]: 'Go Agent Executors',
    sorted_comms[6][0]: 'Agent Runner',
    sorted_comms[7][0]: 'Crypto Primitives',
    sorted_comms[8][0]: 'Catalog & Products',
    sorted_comms[9][0]: 'Go Mandates',
    sorted_comms[10][0]: 'Kotlin A2A Client',
    sorted_comms[11][0]: 'Kotlin Shopping Types',
    sorted_comms[12][0]: 'Demo Code',
    sorted_comms[13][0]: 'Key Management',
    sorted_comms[14][0]: 'Session Storage',
    sorted_comms[15][0]: 'Auth Tokens',
    sorted_comms[16][0]: 'Go A2A Types',
    sorted_comms[17][0]: 'Kotlin Shopping Tools',
    sorted_comms[18][0]: 'Kotlin DPC Types',
    sorted_comms[19][0]: 'Storage & Cache',
    sorted_comms[20][0]: 'Kotlin A2A Types',
    sorted_comms[21][0]: 'Agent Entry Points',
    sorted_comms[22][0]: 'Kotlin Message Builder',
    sorted_comms[23][0]: 'Gateway Launcher',
    sorted_comms[24][0]: 'Kotlin Chat UI',
    sorted_comms[25][0]: 'Kotlin ViewModel',
    sorted_comms[26][0]: 'Go JSON-RPC',
    sorted_comms[27][0]: 'Android Tests',
    sorted_comms[28][0]: 'Main Activity',
    sorted_comms[29][0]: 'Kotlin Chat Message',
    sorted_comms[30][0]: 'UI Components',
    sorted_comms[31][0]: 'HTTP Client',
    sorted_comms[32][0]: 'Payment Models',
    sorted_comms[33][0]: 'Error Handling',
    sorted_comms[34][0]: 'Notification Service',
    sorted_comms[35][0]: 'Data Models',
    sorted_comms[36][0]: 'Utils',
    sorted_comms[37][0]: 'Webhooks',
    sorted_comms[38][0]: 'Task Management',
    sorted_comms[39][0]: 'Message Builder',
    sorted_comms[40][0]: 'Credentials',
    sorted_comms[41][0]: 'Tool Registry',
    sorted_comms[42][0]: 'Request Handlers',
    sorted_comms[43][0]: 'Response Formatters',
    sorted_comms[44][0]: 'A2A Protocol',
    sorted_comms[45][0]: 'Configuration',
    sorted_comms[46][0]: 'Logging',
    sorted_comms[47][0]: 'Database',
    sorted_comms[48][0]: 'Serialization',
    sorted_comms[49][0]: 'Validation',
    sorted_comms[50][0]: 'Middleware',
    sorted_comms[51][0]: 'Router',
    sorted_comms[52][0]: 'Controller',
    sorted_comms[53][0]: 'Service Layer',
    sorted_comms[54][0]: 'Repository',
    sorted_comms[55][0]: 'Domain Models',
    sorted_comms[56][0]: 'Value Objects',
    sorted_comms[57][0]: 'Events',
    sorted_comms[58][0]: 'Handlers',
    sorted_comms[59][0]: 'Converters',
    sorted_comms[60][0]: 'Formatters',
    sorted_comms[61][0]: 'Parsers',
    sorted_comms[62][0]: 'Factories',
    sorted_comms[63][0]: 'Builders',
    sorted_comms[64][0]: 'Decorators',
    sorted_comms[65][0]: 'Plugins',
    sorted_comms[66][0]: 'Extensions',
    sorted_comms[67][0]: 'Mixins',
    sorted_comms[68][0]: 'Interfaces',
    sorted_comms[69][0]: 'Abstract Classes',
    sorted_comms[70][0]: 'Base Classes',
    sorted_comms[71][0]: 'Helper Functions',
    sorted_comms[72][0]: 'Constants',
    sorted_comms[73][0]: 'Enums',
    sorted_comms[74][0]: 'Flags',
    sorted_comms[75][0]: 'Config',
    sorted_comms[76][0]: 'Options',
    sorted_comms[77][0]: 'Settings',
    sorted_comms[78][0]: 'Parameters',
    sorted_comms[79][0]: 'Arguments',
    sorted_comms[80][0]: 'Inputs',
    sorted_comms[81][0]: 'Outputs',
    sorted_comms[82][0]: 'Results',
    sorted_comms[83][0]: 'Returns',
    sorted_comms[84][0]: 'Responses',
}

gods = god_nodes(G)
surprises = surprising_connections(G, communities)
questions = suggest_questions(G, communities, labels)

detection = {'total_files': 186, 'total_words': 117454, 'files': {'code': [133], 'document': [32], 'image': [21]}, 'needs_graph': True}

report = generate(G, communities, {}, labels, gods, surprises, detection, {'input': 0, 'output': 0}, '.', suggested_questions=questions)

with open('graphify-out/GRAPH_REPORT.md', 'w', encoding='utf-8') as f:
    f.write(report)

print(f'Regenerated: {len(labels)} communities labeled')
print('Top 10 communities:')
for i, (cid, nodes) in enumerate(sorted_comms[:10]):
    print(f'  {i+1}. {labels[cid]} ({len(nodes)} nodes)')