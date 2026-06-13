import { useEffect, useState } from "react";
import { api } from "./api";
import type { LicenseStatus } from "./types";
import { LandingScreen } from "./components/LandingScreen";
import { LicenseGate } from "./components/LicenseGate";
import { ToolScreen } from "./components/ToolScreen";

type Screen = "loading" | "locked" | "landing" | "tool";

export default function App() {
  const [screen, setScreen] = useState<Screen>("loading");
  const [license, setLicense] = useState<LicenseStatus | null>(null);
  const [loadErr, setLoadErr] = useState("");

  useEffect(() => {
    api
      .getLicense()
      .then((status) => {
        setLicense(status);
        setScreen(status.status === "valid" ? "landing" : "locked");
      })
      .catch((e: Error) => {
        setLoadErr(e.message);
        setScreen("locked");
      });
  }, []);

  if (screen === "loading") {
    return <div className="card" style={{ margin: 24 }}>Loading…</div>;
  }

  if (screen === "locked") {
    if (loadErr || !license) {
      return (
        <div className="card" style={{ margin: 24 }}>
          <div className="error">{loadErr || "Could not load license status."}</div>
        </div>
      );
    }
    return (
      <LicenseGate
        initial={license}
        onActivated={() => setScreen("landing")}
      />
    );
  }

  if (screen === "landing") {
    return <LandingScreen onLaunch={() => setScreen("tool")} />;
  }

  return <ToolScreen />;
}
