"""Run from backend/:  uv run python -m app.scripts.verify_llm

Proves the provider wiring (base_url + key + model) works end to end.
Prints only the model's reply — never the key.
"""

from openai import OpenAI

from app.config import settings


def main() -> None:
    if not settings.llm_api_key:
        print("LLM_API_KEY is empty in .env — fill it first.")
        return
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    resp = client.chat.completions.create(
        model=settings.model_chat,
        messages=[{"role": "user", "content": "Reply with exactly: scaffold llm ok"}],
        max_tokens=10,
    )
    print(resp.choices[0].message.content)


if __name__ == "__main__":
    main()
