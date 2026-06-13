import { useState } from "react";
import { api } from "../api";
import type { LicenseStatus, LicenseStatusCode } from "../types";
import { APP_VERSION } from "../version";

type Props = {
  initial: LicenseStatus;
  onActivated: () => void;
};

function statusMessage(status: LicenseStatusCode, expiresIso: string | null): string {
  switch (status) {
    case "expired":
      return expiresIso
        ? `Your product key expired on ${expiresIso}. Contact the owner for a new key.`
        : "Your product key has expired. Contact the owner for a new key.";
    case "wrong_machine":
      return "This key is for a different computer. Send your Machine ID to the owner for a new key.";
    case "bad_signature":
    case "malformed":
      return "That product key is not valid. Check for typos and try again.";
    case "missing":
      return "Enter a product key to use this app.";
    default:
      return "";
  }
}

export function LicenseGate({ initial, onActivated }: Props) {
  const [license, setLicense] = useState(initial);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);

  const banner = statusMessage(license.status, license.expires_iso);

  async function copyMachineId() {
    try {
      await navigator.clipboard.writeText(license.machine_id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setErr("Could not copy to clipboard.");
    }
  }

  async function activate() {
    setErr("");
    setBusy(true);
    try {
      const result = await api.saveLicense(key);
      setLicense(result);
      if (result.status === "valid") {
        onActivated();
        return;
      }
      setErr(statusMessage(result.status, result.expires_iso));
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Activation failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="landing license-gate">
      <main className="landing-main">
        <img
          className="landing-logo"
          src="/images/mainLogo1.png"
          alt="AcDec Flashcard Generator"
        />
        <div className="card license-card">
          <h2 style={{ marginTop: 0 }}>Product key required</h2>
          <p className="muted">
            This app is licensed for one computer. Send your Machine ID to the owner;
            they will send back a product key valid for one year.
          </p>

          <label>Your Machine ID</label>
          <div className="row" style={{ gap: 8, alignItems: "stretch" }}>
            <input
              className="mono"
              readOnly
              value={license.machine_id}
              onFocus={(e) => e.target.select()}
            />
            <button type="button" onClick={copyMachineId}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>

          <label style={{ marginTop: 16 }}>Product key</label>
          <input
            placeholder="Paste your product key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && key.trim()) void activate();
            }}
          />

          <div style={{ marginTop: 16 }}>
            <button
              type="button"
              className="primary"
              disabled={busy || !key.trim()}
              onClick={() => void activate()}
            >
              {busy ? "Verifying…" : "Activate"}
            </button>
          </div>

          {(banner || err) && (
            <div className={license.status === "expired" ? "error" : "error"} style={{ marginTop: 16 }}>
              {err || banner}
            </div>
          )}
        </div>
      </main>
      <footer className="landing-footer">
        <span className="landing-version muted">v{APP_VERSION}</span>
        <img className="landing-personal" src="/images/personalLogo.png" alt="" />
      </footer>
    </div>
  );
}
