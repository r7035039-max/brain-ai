from memory import search

print("Brain AI started!")
print("Type 'exit' to quit.")

while True:
    message = input("\nYou: ")

    if message.lower() == "exit":
        break

    results = search(message)

    print(f"\nFound {len(results)} memories:")

    for date, chat, speaker, text in results:
        print("-" * 40)
        print(f"Date: {date}")
        print(f"Chat: {chat}")
        print(f"Speaker: {speaker}")
        print(f"Message: {text}")