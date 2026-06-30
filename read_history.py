import json
import os

path = "C:/Users/ASUS/.gemini/antigravity/brain/257b891f-d28a-4f8a-92bd-27b1215afabe/.system_generated/logs/transcript.jsonl"
if not os.path.exists(path):
    print("History file not found.")
    exit(1)

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print("Total steps:", len(lines))
# Let's print the last 15 messages (type USER_INPUT or PLANNER_RESPONSE / MODEL etc.)
last_turns = []
for line in reversed(lines):
    try:
        step = json.loads(line)
        step_type = step.get("type")
        source = step.get("source")
        content = step.get("content")
        
        # We want to display messages from user and assistant
        if step_type in ["USER_INPUT", "PLANNER_RESPONSE", "MODEL"] or source in ["USER_EXPLICIT", "MODEL"]:
            last_turns.append(step)
            if len(last_turns) >= 20:
                break
    except Exception as e:
        pass

for step in reversed(last_turns):
    print(f"[{step.get('source')} / {step.get('type')}]")
    content = step.get("content", "")
    if content:
        print(content[:500])
    else:
        # Check if there are tool calls
        t_calls = step.get("tool_calls", [])
        if t_calls:
            print("Tool Calls:", [tc.get("name") for tc in t_calls])
    print("-" * 50)
