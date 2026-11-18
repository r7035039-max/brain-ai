
import json
import re
import urllib.request

from memory import search

API_URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "Qwen3-4B"
tok = AutoTokenizer.from_pretrained(base)
model = AutoModelForCausalLM.from_pretrained(base)
model = PeftModel.from_pretrained(model, "ckpt/ИМЯ_ПАПКИ")
model.eval()



def ask_model(messages, max_tokens=4096):
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens
    }

    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read().decode("utf-8"))

    choice = data["choices"][0]
    message = choice["message"]

    content = message.get("content", "")

    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )

    content = re.sub(
        r"<think>[\s\S]*?</think>",
        "",
        content
    ).strip()

    if not content:
        raise RuntimeError(
            f"Qwen returned an empty answer: {data}"
        )

    finish_reason = choice.get("finish_reason")

    if finish_reason == "length":
        content += (
            "\n\n[WARNING: Response reached the token limit. "
            "The answer may be incomplete.]"
        )

    return content


def make_reasoning_summary(question, answer, sources):
    source_text = "\n".join(
        f"- {source}" for source in sources
    ) or "- База знаний не использовалась"

    messages = [
        {
            "role": "system",
            "content": (
                "Ты объясняешь ответы AI на русском языке. "
                "Кратко объясни, на чём основан ответ. "
                "Не раскрывай скрытые внутренние рассуждения. "
                "Не выдумывай использованные источники. "
                "Используй максимум 4 коротких пункта."
            )
        },
        {
            "role": "user",
            "content": (
                f"Вопрос:\n{question}\n\n"
                f"Ответ:\n{answer}\n\n"
                f"Источники:\n{source_text}"
            )
        }
    ]

    try:
        explanation = ask_model(messages, max_tokens=1024)
    except Exception:
        explanation = "Не удалось создать объяснение."

    return (
        "Краткое объяснение:\n"
        + explanation
        + "\n\nИспользованные источники:\n"
        + source_text
    )

def route_question(question):
    messages = [
        {
            "role": "system",
            "content": (
                "You are a router for a personal AI assistant. "
                "Decide whether the user needs information from their "
                "personal message history database.\n\n"
                "Use memory ONLY for questions about the user's past, "
                "personal experiences, preferences, projects, plans, "
                "conversations, or previously shared facts.\n\n"
                "Do NOT use memory for greetings, ordinary conversation, "
                "general knowledge, coding help, or questions about "
                "how the current program works.\n\n"
                "Return ONLY valid JSON in this format:\n"
                '{"needs_memory": false, "search_terms": []}\n\n'
                "If memory is needed, provide 5-10 specific search terms "
                "or short phrases. Include Russian and English variants "
                "when useful. Preserve names and technical terms.\n"
                "Do not answer the user's question."
            )
        },
        {
            "role": "user",
            "content": question + "\n/no_think"
        }
    ]

    response = ask_model(messages, max_tokens=200)

    match = re.search(r"\{[\s\S]*\}", response)

    if not match:
        print("Router failed. Using normal chat.")
        return False, []

    try:
        data = json.loads(match.group())

        needs_memory = data.get("needs_memory", False)
        terms = data.get("search_terms", [])

        if not isinstance(needs_memory, bool):
            return False, []

        if not isinstance(terms, list):
            return False, []

        terms = [
            str(term).strip()
            for term in terms
            if str(term).strip()
        ]

        return needs_memory and bool(terms), terms

    except (ValueError, TypeError):
        print("Router returned invalid JSON. Using normal chat.")
        return False, []


def answer_question(question, memory=""):
    if memory:
        system_prompt = (
            "You are my personal AI assistant. "
            "You have access to retrieved excerpts from my personal history. "
            "Use them as evidence when answering questions about my past. "
            "Do not invent personal facts. "
            "If the excerpts do not contain the answer, say so. "
            "You can also have a natural conversation. "
            "Answer in the same language as the user. "
            "Be concise and natural."
        )

        user_prompt = (
            f"Retrieved memories:\n{memory}\n\n"
            f"User's question: {question}\n/no_think"
        )

    else:
        system_prompt = (
            "You are my personal AI assistant. "
            "Have a natural conversation with the user. "
            "Answer in the same language as the user. "
            "Do not claim to have accessed personal memories "
            "unless they were actually provided. "
            "Be concise and natural."
        )

        user_prompt = question + "\n/no_think"

    return ask_model(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=4096
    )


def ask(question):
    needs_memory, terms = route_question(question)

    memory = ""

    if needs_memory:
        print("MEMORY SEARCH:", terms)

        results = search(terms)

        print("FOUND:", len(results))

        for date, chat_name, speaker, snippet in results:
            memory += (
                f"\nDate: {date}"
                f"\nChat: {chat_name}"
                f"\nSpeaker: {speaker}"
                f"\nMessage: {snippet}\n"
            )

        if not results:
            memory = ""

    else:
        print("MODE: normal chat")

    if needs_memory and not memory:
        return "Я не нашёл подходящих сообщений в своей базе."

    return answer_question(question, memory)


while True:
    question = input("\nYou: ").strip()

    if question.lower() in ["exit", "quit"]:
        break

    if not question:
        continue

    try:
        print("\nAI:", ask(question))

    except Exception as e:
        print("\nERROR:", e)
