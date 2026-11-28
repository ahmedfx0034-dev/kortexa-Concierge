// Talks to any AI service that uses the common "OpenAI-compatible" chat format.
// By default that's Google's free Gemini plan, but Groq, OpenRouter and others
// work too: just change LLM_BASE_URL, LLM_MODEL and LLM_API_KEY.

export class LLM {
  /**
   * @param reasoningEffort  "none" | "low" | ... — how much the model "thinks" first.
   *                         "none" makes Gemini answer in about a second. "" = model default.
   * @param fallbackModel    tried once if the main model is busy, slow or failing.
   */
  constructor({ baseUrl, model, apiKey, reasoningEffort = "", fallbackModel = "", fetchImpl = globalThis.fetch, timeoutMs = 40000, firstTryMs = 4000 }) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    // With a backup model, the main one gets only firstTryMs before we switch, so a busy
    // model costs a few seconds instead of a minute.
    Object.assign(this, { model, apiKey, reasoningEffort, fallbackModel, timeoutMs, firstTryMs });
    this.last = null; // {model, ms} of the last answer, for the speed check
    this.fetch = fetchImpl;
  }

  async chat(messages, opts = {}) {
    const start = Date.now();
    const record = (model, extra = {}) => (text) => { this.last = { model, ms: Date.now() - start, ...extra }; return text; };
    if (!this.fallbackModel) return this.#call(this.model, this.reasoningEffort, messages, opts, this.timeoutMs).then(record(this.model));
    const retryable = (e) => e.status === 429 || e.status === 503 || e.status === 502;
    // Ask the main model. If it hasn't answered after firstTryMs, or fails because it's busy,
    // also ask the backup, and use whichever answers first.
    return new Promise((resolve, reject) => {
      let pending = 1, backup = false, settled = false;
      const finish = (fn, v) => { if (!settled) { settled = true; clearTimeout(timer); fn(v); } };
      const ok = (model, extra) => (text) => finish(resolve, record(model, extra)(text));
      const fail = (e) => { if (--pending === 0 && (backup || !retryable(e))) finish(reject, e); };
      const startBackup = (why) => {
        if (backup || settled) return;
        backup = true; pending++;
        this.#call(this.fallbackModel, "", messages, opts, this.timeoutMs).then(ok(this.fallbackModel, { mainSlow: why }), fail);
      };
      const timer = setTimeout(() => startBackup(`no answer after ${this.firstTryMs} ms`), this.firstTryMs);
      this.#call(this.model, this.reasoningEffort, messages, opts, this.timeoutMs).then(ok(this.model), (e) => {
        if (retryable(e)) startBackup(e.message);
        fail(e);
      });
    });
  }

  async #call(model, effort, messages, { maxTokens = 400, temperature = 0.5 } = {}, timeoutMs = this.timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
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
