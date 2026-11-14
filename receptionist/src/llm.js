// Talks to any AI service that uses the common "OpenAI-compatible" chat format.
// By default that's Google's free Gemini plan, but Groq, OpenRouter and others
// work too: just change LLM_BASE_URL, LLM_MODEL and LLM_API_KEY.

export class LLM {
  constructor({ baseUrl, model, apiKey, fetchImpl = globalThis.fetch, timeoutMs = 30000 }) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.model = model;
    this.apiKey = apiKey;
    this.fetch = fetchImpl;
    this.timeoutMs = timeoutMs;
  }

  async chat(messages, { maxTokens = 400, temperature = 0.5 } = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    let res;
    try {
      res = await this.fetch(`${this.baseUrl}/chat/completions`, {
        method: "POST",
        signal: ctrl.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.apiKey}` },
        body: JSON.stringify({ model: this.model, messages, max_tokens: maxTokens, temperature }),
      });
    } catch (e) {
      throw new LLMError(e.name === "AbortError" ? "The AI took too long to answer." : "Couldn't reach the AI service.", 503);
    } finally {
      clearTimeout(timer);
    }
    const json = await res.json().catch(() => ({}));
    if (res.status === 429) throw new LLMError("The free AI plan's limit was reached. Try again in a minute.", 429);
    if (!res.ok) {
      const msg = (Array.isArray(json) ? json[0] : json)?.error?.message || `AI service error ${res.status}`;
      throw new LLMError(msg, res.status >= 500 ? 503 : 502);
    }
    const text = json.choices?.[0]?.message?.content;
    if (typeof text !== "string" || !text.trim()) throw new LLMError("The AI sent back an empty answer.", 502);
    return text;
  }
}

export class LLMError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
