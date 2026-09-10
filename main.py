import json
import urllib.request
import urllib.error

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:8b"

SYSTEM_PROMPT = """
You are my personal desktop AI assistant.

Personality:
- Friendly, natural, calm, and conversational.
- Talk like a helpful friend, not like a formal customer-service bot.
- Keep ordinary replies reasonably concise.
- Don't over-explain simple things.
- Be useful and honest.
- When a task genuinely needs deeper reasoning, reason carefully internally.
"""

messages = [
    {"role": "system", "content": SYSTEM_PROMPT}
]


def ask_ollama(user_text: str) -> str:
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "think": False,
        "keep_alive": -1,
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    full_response = []

    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            while True:
                line = response.readline()

                if not line:
                    break

                line = line.decode("utf-8").strip()

                if not line:
                    continue

                data = json.loads(line)

                message = data.get("message", {})
                chunk = message.get("content", "")

                if chunk:
                    print(chunk, end="", flush=True)
                    full_response.append(chunk)

                if data.get("done"):
                    break

        answer = "".join(full_response)
        print("\n")

        messages.append(
            {"role": "assistant", "content": answer}
        )

        return answer

    except urllib.error.URLError as e:
        print("\nCould not connect to Ollama.")
        print("Make sure Ollama is running.")
        print(f"Details: {e}")

        # Remove the unanswered user message so the conversation
        # history stays clean.
        messages.pop()

        return ""


def main():
    print("=" * 60)
    print("MY AI — Qwen3 8B")
    print("Fast conversation mode")
    print("Type /think to enable deep reasoning.")
    print("Type /fast to return to fast mode.")
    print("Type /clear to clear conversation.")
    print("Type /exit to quit.")
    print("=" * 60)

    thinking = False

    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_text:
            continue

        if user_text.lower() == "/exit":
            print("Goodbye.")
            break

        if user_text.lower() == "/clear":
            messages[:] = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
            print("Conversation cleared.")
            continue

        if user_text.lower() == "/think":
            thinking = True
            print("Deep-thinking mode: ON")
            continue

        if user_text.lower() == "/fast":
            thinking = False
            print("Fast mode: ON")
            continue

        # Temporarily change the request setting.
        payload_think = thinking

        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": True,
            "think": payload_think,
            "keep_alive": -1,
        }

        request = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        print("AI: ", end="", flush=True)

        full_response = []

        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                while True:
                    line = response.readline()

                    if not line:
                        break

                    line = line.decode("utf-8").strip()

                    if not line:
                        continue

                    data = json.loads(line)
                    message = data.get("message", {})

                    # We deliberately don't print the thinking trace.
                    chunk = message.get("content", "")

                    if chunk:
                        print(chunk, end="", flush=True)
                        full_response.append(chunk)

                    if data.get("done"):
                        break

            answer = "".join(full_response)

            messages.append(
                {"role": "assistant", "content": answer}
            )

            print()

        except urllib.error.URLError as e:
            print("\nCould not connect to Ollama.")
            print(f"Details: {e}")
            messages.pop()


if __name__ == "__main__":
    main()