import os
import re

frontend_dir = os.path.abspath(r'd:\tender-compliance\frontend')

def get_relative_path(file_path, target_alias):
    file_dir = os.path.dirname(os.path.abspath(file_path))
    target_abs = os.path.join(frontend_dir, target_alias)
    rel = os.path.relpath(target_abs, file_dir)
    rel = rel.replace('\\', '/')
    if not rel.startswith('.'):
        rel = './' + rel
    return rel

updated = 0
for root, dirs, files in os.walk(frontend_dir):
    if 'node_modules' in root or '.next' in root:
        continue
    for file in files:
        if file.endswith('.ts') or file.endswith('.tsx'):
            file_path = os.path.join(root, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            def replacer(match):
                prefix = match.group(1)
                target = match.group(2)
                suffix = match.group(3)
                rel = get_relative_path(file_path, target)
                return prefix + rel + suffix

            new_content = re.sub(r'(from\s+[\'"])@/([^\'"]+)([\'"])', replacer, content)
            
            if new_content != content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Updated {file_path}")
                updated += 1

print(f"Total files updated: {updated}")
