import re

with open('E:/Ank/prompt2/devolutiva_claude/server.py', 'r', encoding='utf-8') as f:
    new = f.read()
with open('E:/Ank/server/server.py', 'r', encoding='utf-8') as f:
    old = f.read()

old_routes = set(re.findall(r'elif path == ["\'](/api/[^"\']*)["\']', old))
new_routes = set(re.findall(r'elif path == ["\'](/api/[^"\']*)["\']', new))
print('New routes:', new_routes - old_routes)

old_methods = set(re.findall(r'def (api_\w+|_ws_\w+)\(', old))
new_methods = set(re.findall(r'def (api_\w+|_ws_\w+)\(', new))
print('New methods:', new_methods - old_methods)

# Check for ws/node-shell
if 'ws/node-shell' in new and 'ws/node-shell' not in old:
    print('WebSocket node-shell: NEW')
