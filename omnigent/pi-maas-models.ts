import {
  createAssistantMessageEventStream,
  type Api,
  type AssistantMessage,
  type AssistantMessageEventStream,
  type Model,
  type SimpleStreamOptions,
  type TranscriptContext,
} from "@earendil-works/pi-ai";
import { getApiProvider } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BASE_URL = "https://models.corp.redhat.com/oai/v1";
const RHAI_BASE_URL = "https://maas.apps.ocp.cloud.rhai-tmm.dev/v1";
const FALLBACK_MODEL_ID = "deepseek-4-1-flash";
const RHAI_FALLBACK_MODEL_IDS = [
  "publishers/prelude-maas/models/gemma4",
  "publishers/prelude-maas/models/glm-53-flash",
  "publishers/prelude-maas/models/llama-32-3b",
  "publishers/prelude-maas/models/qwen38-27b",
];
const RHAI_DISCOVERY_ATTEMPTS = 4;
const DISCOVERY_TIMEOUT_MS = 10_000;
const MAX_MODELS = 500;
const REQUESTS_PER_MINUTE = 30;
const TOKENS_PER_MINUTE = 300_000;
const RATE_WINDOW_MS = 60_000;
const DEFAULT_CONTEXT_WINDOW = 128_000;
const DEFAULT_MAX_TOKENS = 16_384;

type MaaSModel = {
  id: string;
  name?: string;
  context_window?: number;
  max_tokens?: number;
  reasoning?: boolean;
  modalities?: string[];
};

type Reservation = {
  id: number;
  modelId: string;
  requestAt: number;
  tokenAt: number;
  tokens: number;
};

class MaaSRateLimiter {
  private readonly reservations = new Map<string, Reservation[]>();
  private nextId = 1;

  async acquire(modelId: string, estimatedTokens: number, signal?: AbortSignal): Promise<Reservation> {
    if (estimatedTokens > TOKENS_PER_MINUTE) {
      throw new Error(
        `Estimated request size (${estimatedTokens.toLocaleString()} tokens) exceeds the MaaS limit of ${TOKENS_PER_MINUTE.toLocaleString()} tokens per minute for ${modelId}. Reduce the prompt or output limit.`,
      );
    }

    let loggedWait = false;
    while (true) {
      if (signal?.aborted) throw signal.reason ?? new Error("MaaS request was cancelled");

      const now = Date.now();
      const current = (this.reservations.get(modelId) ?? []).filter(
        (entry) =>
          now - entry.requestAt < RATE_WINDOW_MS ||
          (entry.tokens > 0 && now - entry.tokenAt < RATE_WINDOW_MS),
      );
      this.reservations.set(modelId, current);

      const requestsInWindow = current.filter((entry) => now - entry.requestAt < RATE_WINDOW_MS);
      const tokenEntries = current.filter(
        (entry) => entry.tokens > 0 && now - entry.tokenAt < RATE_WINDOW_MS,
      );
      const tokensInWindow = tokenEntries.reduce((total, entry) => total + entry.tokens, 0);
      if (requestsInWindow.length < REQUESTS_PER_MINUTE && tokensInWindow + estimatedTokens <= TOKENS_PER_MINUTE) {
        const reservation: Reservation = {
          id: this.nextId++,
          modelId,
          requestAt: now,
          tokenAt: now,
          tokens: estimatedTokens,
        };
        current.push(reservation);
        return reservation;
      }

      let remainingRequests = requestsInWindow.length;
      let remainingTokens = tokensInWindow;
      let retryAt = now + RATE_WINDOW_MS;
      const expirations = [
        ...requestsInWindow.map((entry) => ({ at: entry.requestAt + RATE_WINDOW_MS, kind: "request" as const })),
        ...tokenEntries.map((entry) => ({ at: entry.tokenAt + RATE_WINDOW_MS, kind: "tokens" as const, tokens: entry.tokens })),
      ].sort((left, right) => left.at - right.at);
      for (const expiration of expirations) {
        if (expiration.kind === "request") remainingRequests--;
        else remainingTokens -= expiration.tokens;
        retryAt = expiration.at;
        if (
          remainingRequests < REQUESTS_PER_MINUTE &&
          remainingTokens + estimatedTokens <= TOKENS_PER_MINUTE
        ) {
          break;
        }
      }

      const delayMs = Math.max(1, retryAt - now);
      if (!loggedWait) {
        process.stderr.write(
          `MaaS ${modelId} quota reached; waiting ${Math.ceil(delayMs / 1000)}s before retrying.\n`,
        );
        loggedWait = true;
      }
      await wait(delayMs, signal);
    }
  }

  reconcile(reservation: Reservation, actualTokens: number): void {
    const current = this.reservations.get(reservation.modelId);
    const stored = current?.find((entry) => entry.id === reservation.id);
    if (stored && Number.isFinite(actualTokens) && actualTokens >= 0) {
      stored.tokens = actualTokens;
      stored.tokenAt = Date.now();
    }
  }
}

function wait(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delayMs);

    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(signal?.reason ?? new Error("MaaS request was cancelled"));
    };

    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}

function estimateRequestTokens(payload: unknown, model: Model<Api>): number {
  const serialized = JSON.stringify(payload ?? {});
  const inputEstimate = Math.ceil(new TextEncoder().encode(serialized).length / 3);
  const body = typeof payload === "object" && payload !== null
    ? payload as Record<string, unknown>
    : {};
  const requestedOutput = [body.max_completion_tokens, body.max_tokens].find(
    (value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0,
  );
  return inputEstimate + (requestedOutput ?? model.maxTokens);
}

const rateLimiter = new MaaSRateLimiter();

function streamWithRateLimit(
  model: Model<Api>,
  context: TranscriptContext,
  options?: SimpleStreamOptions,
): AssistantMessageEventStream {
  if (model.api !== "openai-completions") {
    throw new Error(`Unexpected MaaS API type: ${model.api}`);
  }

  const apiProvider = getApiProvider(model.api);
  if (!apiProvider) throw new Error("Pi's OpenAI completions provider is unavailable");

  const reservations: Reservation[] = [];
  const inner = apiProvider.streamSimple(model, context, {
    ...options,
    onPayload: async (payload, requestModel) => {
      const updated = await options?.onPayload?.(payload, requestModel);
      const finalPayload = updated === undefined ? payload : updated;
      const estimate = estimateRequestTokens(finalPayload, requestModel);
      reservations.push(await rateLimiter.acquire(model.id, estimate, options?.signal));
      return finalPayload;
    },
  });

  const outer = createAssistantMessageEventStream();
  void (async () => {
    try {
      for await (const event of inner) {
        const reservation = reservations.at(-1);
        if (reservation && event.type === "done" && event.message.usage.totalTokens > 0) {
          rateLimiter.reconcile(reservation, event.message.usage.totalTokens);
        } else if (reservation && event.type === "error") {
          rateLimiter.reconcile(reservation, 0);
        }
        outer.push(event);
      }
      outer.end(await inner.result());
    } catch (error) {
      const message: AssistantMessage = {
        role: "assistant",
        content: [],
        api: model.api,
        provider: model.provider,
        model: model.id,
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: "error",
        errorMessage: error instanceof Error ? error.message : String(error),
        timestamp: Date.now(),
      };
      outer.push({ type: "error", reason: "error", error: message });
      outer.end();
    }
  })();
  return outer;
}

function parseModel(value: unknown): MaaSModel | undefined {
  if (typeof value !== "object" || value === null || !("id" in value)) {
    return undefined;
  }

  const model = value as Record<string, unknown>;
  if (typeof model.id !== "string" || model.id.length === 0 || model.id.length > 200) {
    return undefined;
  }

  return {
    id: model.id,
    name: typeof model.name === "string" ? model.name : undefined,
    context_window:
      typeof model.context_window === "number" && Number.isFinite(model.context_window)
        ? model.context_window
        : undefined,
    max_tokens:
      typeof model.max_tokens === "number" && Number.isFinite(model.max_tokens) && model.max_tokens > 0
        ? model.max_tokens
        : typeof model.max_output_tokens === "number" && Number.isFinite(model.max_output_tokens) && model.max_output_tokens > 0
          ? model.max_output_tokens
        : undefined,
    reasoning: model.reasoning === true,
    modalities: Array.isArray(model.modalities)
      ? model.modalities.filter((modality): modality is string => typeof modality === "string")
      : undefined,
  };
}

function toPiModel(model: MaaSModel) {
  const input: ("text" | "image")[] = model.modalities?.includes("image")
    ? ["text", "image"]
    : ["text"];
  return {
    id: model.id,
    name: model.name || model.id,
    reasoning: model.reasoning === true,
    input,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow:
      model.context_window && model.context_window > 0
        ? model.context_window
        : DEFAULT_CONTEXT_WINDOW,
    maxTokens: model.max_tokens ?? DEFAULT_MAX_TOKENS,
  };
}

async function discoverModels(
  baseUrl: string,
  apiKey: string,
  label: string,
  attempts = 1,
): Promise<MaaSModel[]> {
  const signal = AbortSignal.timeout(DISCOVERY_TIMEOUT_MS);
  for (let attempt = 0; attempt < attempts && !signal.aborted; attempt++) {
    try {
      const response = await fetch(`${baseUrl}/models`, {
        headers: { Authorization: `Bearer ${apiKey}` },
        signal,
      });
      if (!response.ok) {
        await response.body?.cancel();
        continue;
      }

      const payload = (await response.json()) as { data?: unknown };
      if (Array.isArray(payload.data)) {
        const models = payload.data.map(parseModel).filter((model) => model !== undefined).slice(0, MAX_MODELS);
        if (models.length > 0) return models;
      }
    } catch {
      // Discovery errors can contain response data and credentials.
    }
  }
  process.stderr.write(`${label} model discovery failed; using configured fallback models.\n`);
  return [];
}

export default async function (pi: ExtensionAPI) {
  const apiKey = process.env.MAAS_API_KEY;
  const rhaiApiKey = process.env.RHAI_MAAS_API_KEY;
  const [models, rhaiModels] = await Promise.all([
    apiKey ? discoverModels(BASE_URL, apiKey, "Red Hat MaaS") : [],
    rhaiApiKey ? discoverModels(RHAI_BASE_URL, rhaiApiKey, "OpenShift AI MaaS", RHAI_DISCOVERY_ATTEMPTS) : [],
  ]);

  if (!models.some((model) => model.id === FALLBACK_MODEL_ID)) {
    models.push({ id: FALLBACK_MODEL_ID });
  }

  pi.registerProvider("maas", {
    name: "Red Hat MaaS",
    baseUrl: BASE_URL,
    api: "openai-completions",
    apiKey: "$MAAS_API_KEY",
    streamSimple: streamWithRateLimit,
    models: models.map(toPiModel),
  });

  if (rhaiApiKey) {
    const catalog = rhaiModels.length > 0 ? rhaiModels : RHAI_FALLBACK_MODEL_IDS.map((id) => ({ id }));
    pi.registerProvider("rhai-maas", {
      name: "OpenShift AI MaaS",
      baseUrl: RHAI_BASE_URL,
      api: "openai-completions",
      apiKey: "$RHAI_MAAS_API_KEY",
      models: catalog.map(toPiModel),
    });
  }
}
