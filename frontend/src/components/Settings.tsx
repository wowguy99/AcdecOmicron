import { useEffect, useState } from "react";
import { api } from "../api";
import type { LicenseStatus, LicenseStatusCode, ProviderConfig } from "../types";

const GEMINI_MODELS: Record<
  string,
  { label: string; rpm: number; rpd: number; note: string }
> = {
  "gemini-2.5-flash-lite": {
    label: "Gemini 2.5 Flash-Lite",
    rpm: 15,
    rpd: 1000,
    note: "Default. Fastest free tier — ~15 RPM, 1,000 req/day, 250k TPM.",
  },
  "gemini-2.5-flash": {
    label: "Gemini 2.5 Flash",
    rpm: 10,
    rpd: 1500,
    note: "Better quality than Flash-Lite — ~10 RPM, 1,500 req/day, 250k TPM.",
  },
  "gemini-2.0-flash": {
    label: "Gemini 2.0 Flash",
    rpm: 15,
    rpd: 1500,
    note: "Higher TPM (~1M/min). Useful if hitting token limits on 2.5 models.",
  },
};

const GEMINI_CUSTOM = "__custom__";

const PRESETS: Record<string, { model: string; rpm: number; rpd: number; note: string }> = {
  gemini: {
    model: "gemini-2.5-flash-lite",
    rpm: 15,
    rpd: 1000,
    note: "Get a key at aistudio.google.com, then pick a Gemini model below.",
  },
  groq: {
    model: "llama-3.1-8b-instant",
    rpm: 30,
    rpd: 14400,
    note: "Highest free volume (~30 RPM / 14,400 req/day), lower fidelity. Key at console.groq.com.",
  },
  openai_compat: {
    model: "gpt-4o-mini",
    rpm: 60,
    rpd: 10000,
    note: "Any OpenAI-compatible endpoint. Set base_url and your own limits.",
  },
};

function geminiModelKey(model: string): string {
  return model in GEMINI_MODELS ? model : GEMINI_CUSTOM;
}

function licenseStatusLabel(status: LicenseStatusCode, expiresIso: string | null): string {
  switch (status) {
    case "valid":
      return expiresIso ? `Valid until ${expiresIso}` : "Valid";
    case "expired":
      return expiresIso ? `Expired on ${expiresIso}` : "Expired";
    case "wrong_machine":
      return "Key is for a different computer";
    case "bad_signature":
    case "malformed":
      return "Invalid product key";
    case "missing":
      return "No product key on file";
    default:
      return status;
  }
}

export function Settings({ onSaved }: { onSaved?: () => void }) {
  const [cfg, setCfg] = useState<ProviderConfig | null>(null);
  const [license, setLicense] = useState<LicenseStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [licenseKey, setLicenseKey] = useState("");
  const [licenseMsg, setLicenseMsg] = useState("");
  const [licenseErr, setLicenseErr] = useState("");
  const [copied, setCopied] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api.getConfig().then(setCfg).catch((e) => setErr(e.message));
    api.getLicense().then(setLicense).catch((e) => setErr(e.message));
  }, []);

  if (!cfg || !license) return <div className="card">Loading settings…</div>;

  const hasKey = cfg.api_key === true;
  const preset = PRESETS[cfg.provider];
  const geminiKey = cfg.provider === "gemini" ? geminiModelKey(cfg.model) : "";
  const geminiPreset = geminiKey !== GEMINI_CUSTOM ? GEMINI_MODELS[geminiKey] : null;

  function applyPreset(provider: string) {
    const p = PRESETS[provider];
    setCfg({ ...cfg!, provider, model: p.model, rpm: p.rpm, rpd: p.rpd });
  }

  function applyGeminiModel(key: string) {
    if (key === GEMINI_CUSTOM) {
      setCfg({ ...cfg! });
      return;
    }
    const g = GEMINI_MODELS[key];
    setCfg({ ...cfg!, model: key, rpm: g.rpm, rpd: g.rpd });
  }

  async function save() {
    setErr("");
    setMsg("");
    try {
      const saved = await api.saveConfig({
        provider: cfg!.provider,
        model: cfg!.model,
        api_key: apiKey || undefined,
        base_url: cfg!.base_url || undefined,
        rpm: cfg!.rpm,
        rpd: cfg!.rpd,
        temperature: cfg!.temperature,
      });
      setCfg(saved);
      setApiKey("");
      setMsg("Saved.");
      onSaved?.();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function copyMachineId() {
    if (!license) return;
    try {
      await navigator.clipboard.writeText(license.machine_id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setLicenseErr("Could not copy to clipboard.");
    }
  }

  async function saveLicenseKey() {
    setLicenseErr("");
    setLicenseMsg("");
    try {
      const result = await api.saveLicense(licenseKey);
      setLicense(result);
      if (result.status === "valid") {
        setLicenseKey("");
        setLicenseMsg("Product key saved.");
      } else {
        setLicenseErr(licenseStatusLabel(result.status, result.expires_iso));
      }
    } catch (e: any) {
      setLicenseErr(e.message);
    }
  }

  return (
    <>
    <div className="card" style={{ marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Product Key</h3>
      <p className="muted">
        Licensed for one computer. Send your Machine ID to the owner to receive a
        one-year product key.
      </p>

      <label>Machine ID</label>
      <div className="row" style={{ gap: 8, alignItems: "stretch" }}>
        <input
          className="mono"
          readOnly
          value={license.machine_id}
          onFocus={(e) => e.target.select()}
        />
        <button type="button" onClick={() => void copyMachineId()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <p style={{ marginTop: 12 }}>
        Status:{" "}
        <span className={license.status === "valid" ? "ok" : "muted"}>
          {licenseStatusLabel(license.status, license.expires_iso)}
        </span>
      </p>

      <label>Product key {license.has_key && license.status === "valid" && (
        <span className="muted">(enter a new key to replace)</span>
      )}</label>
      <input
        placeholder="Paste product key"
        value={licenseKey}
        onChange={(e) => setLicenseKey(e.target.value)}
      />

      <div style={{ marginTop: 16 }}>
        <button
          className="primary"
          disabled={!licenseKey.trim()}
          onClick={() => void saveLicenseKey()}
        >
          Save product key
        </button>
        {licenseMsg && <span className="ok" style={{ marginLeft: 12 }}>{licenseMsg}</span>}
      </div>
      {licenseErr && <div className="error">{licenseErr}</div>}
    </div>

    <div className="card">
      <h3 style={{ marginTop: 0 }}>AI Provider</h3>
      <p className="muted">
        Your API key is stored only on this machine (a git-ignored local file) and
        is used by the backend to call the provider. The key is never shown again.
      </p>

      <label>Provider</label>
      <select value={cfg.provider} onChange={(e) => applyPreset(e.target.value)}>
        <option value="gemini">Google Gemini</option>
        <option value="groq">Groq</option>
        <option value="openai_compat">OpenAI-compatible</option>
      </select>
      <p className="muted">{preset?.note}</p>

      {cfg.provider === "gemini" ? (
        <>
          <label>Gemini model</label>
          <select value={geminiKey} onChange={(e) => applyGeminiModel(e.target.value)}>
            {Object.entries(GEMINI_MODELS).map(([id, g]) => (
              <option key={id} value={id}>
                {g.label}
              </option>
            ))}
            <option value={GEMINI_CUSTOM}>Custom model ID…</option>
          </select>
          <p className="muted">
            {geminiPreset?.note ??
              "Enter any Gemini model ID below (e.g. from ai.google.dev). Adjust RPM/RPD to match its free-tier limits."}
          </p>
          {geminiKey === GEMINI_CUSTOM && (
            <>
              <label>Custom model ID</label>
              <input
                placeholder="gemini-2.5-flash"
                value={cfg.model}
                onChange={(e) => setCfg({ ...cfg, model: e.target.value })}
              />
            </>
          )}
        </>
      ) : (
        <>
          <label>Model</label>
          <input value={cfg.model} onChange={(e) => setCfg({ ...cfg, model: e.target.value })} />
        </>
      )}

      {cfg.provider === "openai_compat" && (
        <>
          <label>Base URL</label>
          <input
            placeholder="https://host/v1"
            value={cfg.base_url ?? ""}
            onChange={(e) => setCfg({ ...cfg, base_url: e.target.value })}
          />
        </>
      )}

      <label>API key {hasKey && <span className="ok">(key on file — leave blank to keep)</span>}</label>
      <input
        type="password"
        placeholder={hasKey ? "••••••••" : "Paste your API key"}
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
      />

      <div className="row" style={{ gap: 16 }}>
        <div style={{ flex: 1 }}>
          <label>Requests / min (throttle)</label>
          <input
            type="number"
            value={cfg.rpm}
            onChange={(e) => setCfg({ ...cfg, rpm: Number(e.target.value) })}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label>Requests / day (free cap)</label>
          <input
            type="number"
            value={cfg.rpd}
            onChange={(e) => setCfg({ ...cfg, rpd: Number(e.target.value) })}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label>Temperature</label>
          <input
            type="number"
            step="0.05"
            value={cfg.temperature}
            onChange={(e) => setCfg({ ...cfg, temperature: Number(e.target.value) })}
          />
        </div>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        RPM/RPD auto-fill when you pick a Gemini model; you can lower them further if you see 429 errors.
      </p>

      <div style={{ marginTop: 16 }}>
        <button className="primary" onClick={save}>Save settings</button>
        {msg && <span className="ok" style={{ marginLeft: 12 }}>{msg}</span>}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
    </>
  );
}
