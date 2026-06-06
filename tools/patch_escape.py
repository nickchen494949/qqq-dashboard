with open('tools/build_dashboard.py', 'r') as f:
    lines = f.readlines()

in_js = False
for i, line in enumerate(lines):
    if 'function barColors(yArr)' in line:
        in_js = True
    
    if in_js:
        # replace { with {{ and } with }} if they are single
        import re
        line = re.sub(r'(?<!\{)\{(?!\{)', '{{', line)
        line = re.sub(r'(?<!\})}(?!\})', '}}', line)
        lines[i] = line
        
        if 'renderVol();' in line:
            in_js = False

with open('tools/build_dashboard.py', 'w') as f:
    f.writelines(lines)
