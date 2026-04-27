import json
import re

with open('/Users/adisu/Documents/Gamio/assets/story-builder/starting_phrases.json', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace smart quotes with straight quotes
content = content.replace('“', '"').replace('”', '"').replace('’', "'")

# Fix the [name\n] issue by removing newlines inside brackets
content = re.sub(r'\[name\s+\]', '[name]', content)
content = re.sub(r'\[name\n\]', '[name]', content)
content = re.sub(r'\[name\r\n\]', '[name]', content)
# Just to be safe, replace any whitespace within the brackets:
content = re.sub(r'\[name\s*\]', '[name]', content)

# It's currently a comma separated list of strings. Let's extract all the strings.
strings = re.findall(r'"([^"]*)"', content)

# Write back as proper JSON
with open('/Users/adisu/Documents/Gamio/assets/story-builder/starting_phrases.json', 'w', encoding='utf-8') as f:
    json.dump(strings, f, indent=4, ensure_ascii=False)

print(f"Fixed JSON, extracted {len(strings)} strings.")
