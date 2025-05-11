# topic_picker.py
import random, datetime, os, openai

openai.api_key = os.getenv("OPENAI_API_KEY")

SEED_TOPICS = [
    "sustainable travel", "AI ethics", "classical music",
    "space exploration", "healthy cooking", "mindfulness",
]

def pick() -> str:
    today = datetime.date.today().isoformat()
    prompt = (
        f"Suggest one fresh, trending topic for a podcast discussion on {today}. "
        "Return only the topic phrase."
    )
    try:
        rsp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        topic = rsp.choices[0].message.content.strip()
        return topic or random.choice(SEED_TOPICS)
    except Exception:
        return random.choice(SEED_TOPICS)

if __name__ == "__main__":
    print(pick())
