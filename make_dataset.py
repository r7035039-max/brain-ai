import json
from datetime import datetime

GAP = 600  # секунд: пауза больше этой разрывает реплику

def ts(m):
    return datetime.fromisoformat(m["date"])

messages = []
with open("telegram_messages.jsonl", encoding="utf-8") as f:
    for line in f:
        messages.append(json.loads(line))

turns = []
for m in messages:
    t = ts(m)
    same = (turns
            and turns[-1]["chat_id"] == m["chat_id"]
            and turns[-1]["speaker"] == m["speaker"]
            and (t - turns[-1]["last"]).total_seconds() <= GAP)

    if same:
        turns[-1]["text"] += "\n" + m["text"]
        turns[-1]["last"] = t
    else:
        new = m.copy()
        new["last"] = t
        turns.append(new)
K = 6            # сколько прошлых реплик берём в контекст
MAX_CHARS = 1500 # лимит длины контекста
MIN_LEN = 2      # слишком короткие ответы не берём

samples = []
for i, turn in enumerate(turns):
    if turn["speaker"] != "me" or len(turn["text"]) < MIN_LEN:
        continue

    ctx = []
    j = i - 1
    while j >= 0 and len(ctx) < K and turns[j]["chat_id"] == turn["chat_id"]:
        ctx.append(turns[j])
        j -= 1
    ctx.reverse()

    # контекст должен начинаться с реплики собеседника
    while ctx and ctx[0]["speaker"] == "me":
        ctx.pop(0)
    if not ctx:
        continue

    # обрезаем по длине, выкидывая самые старые реплики
    while len(ctx) > 1 and sum(len(c["text"]) for c in ctx) > MAX_CHARS:
        ctx.pop(0)

    chat = [{"role": "user" if c["speaker"] == "other" else "assistant",
             "content": c["text"]} for c in ctx]
    chat.append({"role": "assistant", "content": turn["text"]})
    samples.append({"messages": chat})

with open("train.jsonl", "w", encoding="utf-8") as f:
    for s in samples:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print("samples:", len(samples))
print(len(messages), len(turns))
print(sum(x["speaker"] == "me" for x in turns), len(turns))