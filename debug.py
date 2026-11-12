import os
from dotenv import load_dotenv

load_dotenv()

k = os.getenv("OPENAI_API_KEY", "")
u = os.getenv("OPENAI_BASE_URL", "")

print("=== ENV CHECK ===")
print("Key length:", len(k))
print("Key starts with gsk_:", k.startswith("gsk_"))
print("Key first 10:", k[:10])
print("Key last 6:", k[-6:])
print("Key has space:", " " in k)
print("Key has quote:", ('"' in k) or ("'" in k))
print("Key has newline:", ("\n" in k) or ("\r" in k))
print("URL:", repr(u))

print()
print("=== API TEST ===")
from openai import OpenAI

c = OpenAI(api_key=k, base_url=u)
try:
    r = c.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=5,
    )
    print("SUCCESS:", r.choices[0].message.content)
except Exception as e:
    print("ERROR TYPE:", type(e).__name__)
    print("ERROR MSG:", str(e)[:500])
