with open('tools/build_dashboard.py', 'r') as f:
    text = f.read()

text = text.replace('As of ${L.date}', 'As of ${{L.date}}')

with open('tools/build_dashboard.py', 'w') as f:
    f.write(text)
