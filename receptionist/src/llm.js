// Talks to any AI service that uses the common "OpenAI-compatible" chat format.
// By default that's Google's free Gemini plan, but Groq, OpenRouter and others
// work too: just change LLM_BASE_URL, LLM_MODEL and LLM_API_KEY.

export class LLM {
  /**
   * @param reasoningEffort  "none" | "low" | ... — how much the model "thinks" first.
   *                         "none" makes Gemini answer in about a second. "" = model default.
   * @param fallbackModel    tried once if the main model is busy, slow or failing.
   */
  constructor({ baseUrl, model, apiKey, reasoningEffort = "", fallbackModel = "", fetchImpl = globalThis.fetch, timeoutMs = 40000 }) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    Object.assign(this, { model, apiKey, reasoningEffort, fallbackModel, timeoutMs });
    this.fetch = fetchImpl;
  }

  async chat(messages, opts = {}) {
    try {
      return await this.#call(this.model, this.reasoningEffort, messages, opts);
    } catch (e) {
      const retryable = e.status === 429 || e.status === 503 || e.status === 502;
      if (!this.fallbackModel || !retryable) throw e;
      return this.#call(this.fallbackModel, "", messages, opts);
    }
  }

  async #call(model, effort, messages, { maxTokens = 400, temperature = 0.5 } = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    let res;
    try {
      res = await this.fetch(`${this.baseUrl}/chat/completions`, {
        method: "POST",
        signal: ctrl.signal,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.apiKey}` },
        body: JSON.stringify({ model, messages, max_tokens: maxTokens, temperature, ...(effort ? { reasoning_effort: effort } : {}) }),
      });
    } catch (e) {
      throw new LLMError(e.name === "AbortError" ? "The AI took too long to answer." : "Couldn't reach the AI service.", 503);
    } finally {
      clearTimeout(timer);
    }
    const json = await res.json().catch(() => ({}));
    const err = (Array.isArray(json) ? json[0] : json)?.error;
    if (res.status === 429) throw new LLMError("The free AI plan's limit was reached. Try again in a minute.", 429);
    if (!res.ok) throw new LLMError(err?.message || `AI service error ${res.status}`, res.status >= 500 ? 503 : 502);
    const text = json.choices?.[0]?.message?.content;
    if (typeof text !== "string" || !text.trim()) throw new LLMError("The AI sent back an empty answer.", 502);
    return text;
  }
}

export class LLMError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
