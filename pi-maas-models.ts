import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BASE_URL = "https://models.corp.redhat.com/oai/v1";
const FALLBACK_MODEL_ID = "deepseek-4-1-flash";
const DISCOVERY_TIMEOUT_MS = 10_000;
const MAX_MODELS = 500;

type MaaSModel = {
  id: string;
  name?: string;
  context_window?: number;
  max_tokens?: number;
  reasoning?: boolean;
  modalities?: string[];
};

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
      typeof model.max_tokens === "number" && Number.isFinite(model.max_tokens)
        ? model.max_tokens
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
    contextWindow: model.context_window && model.context_window > 0 ? model.context_window : 128_000,
    maxTokens: model.max_tokens && model.max_tokens > 0 ? model.max_tokens : 4_096,
  };
}

export default async function (pi: ExtensionAPI) {
  let models: MaaSModel[] = [];
  const apiKey = process.env.MAAS_API_KEY;

  if (apiKey) {
    try {
      const response = await fetch(`${BASE_URL}/models`, {
        headers: { Authorization: `Bearer ${apiKey}` },
        signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
      });
      if (!response.ok) throw new Error("MaaS model discovery failed");

      const payload = (await response.json()) as { data?: unknown };
      if (Array.isArray(payload.data)) {
        models = payload.data.map(parseModel).filter((model) => model !== undefined).slice(0, MAX_MODELS);
      }
      if (models.length === 0) throw new Error("No MaaS models returned");
    } catch {
      // Fall back below without logging response data or credentials.
      process.stderr.write(
        "MaaS model discovery failed; using the configured fallback model.\n",
      );
    }
  }

  if (!models.some((model) => model.id === FALLBACK_MODEL_ID)) {
    models.push({ id: FALLBACK_MODEL_ID });
  }

  pi.registerProvider("maas", {
    name: "Red Hat MaaS",
    baseUrl: BASE_URL,
    api: "openai-completions",
    apiKey: "MAAS_API_KEY",
    models: models.map(toPiModel),
  });
}
