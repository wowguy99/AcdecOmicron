import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { BuildTest } from "./BuildTest";
import { Settings } from "./Settings";
import { Upload } from "./Upload";
import { TreeView } from "./TreeView";
import type { ProviderConfig, SubjectSummary } from "../types";

type Tab = "subjects" | "testing" | "settings";

export function ToolScreen() {
  const [tab, setTab] = useState<Tab>("subjects");
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [cfg, setCfg] = useState<ProviderConfig | null>(null);
  const [deleteErr, setDeleteErr] = useState("");
  const [importMsg, setImportMsg] = useState("");
  const [importErr, setImportErr] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  function refreshSubjects() {
    api.listSubjects().then(setSubjects);
  }
  function refreshCfg() {
    api.getConfig().then(setCfg);
  }

  async function deleteSubject(e: React.MouseEvent, id: number, name: string) {
    e.stopPropagation();
    setDeleteErr("");
    if (
      !window.confirm(
        `Delete "${name}" and all its cards?\n\nThis permanently removes the subject, tree, and uploaded PDF.`
      )
    ) {
      return;
    }
    try {
      await api.deleteSubject(id);
      if (active === id) setActive(null);
      refreshSubjects();
    } catch (err: unknown) {
      setDeleteErr(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  function exportSubject(e: React.MouseEvent, id: number) {
    e.stopPropagation();
    const a = document.createElement("a");
    a.href = api.exportSubjectUrl(id);
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function importSubject(file: File) {
    setImportErr("");
    setImportMsg("");
    setImportBusy(true);
    try {
      const result = await api.importSubject(file);
      setImportMsg(`Imported "${result.name}".`);
      refreshSubjects();
    } catch (err: unknown) {
      setImportErr(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImportBusy(false);
      if (importInputRef.current) importInputRef.current.value = "";
    }
  }

  useEffect(() => {
    refreshSubjects();
    refreshCfg();
  }, []);

  const keySet = cfg?.api_key === true;

  return (
    <div className="app">
      <header className="top tool-header">
        <div className="tool-header-left">
          <h1>AcDec Atomic Flashcard Generator</h1>
          <span className={keySet ? "badge det" : "badge exc"}>
            {keySet ? "API key set" : "no API key"}
          </span>
        </div>
        <img
          className="tool-header-brand"
          src="/images/partialLogo.png"
          alt=""
        />
      </header>

      <div className="tabs">
        <button
          className={tab === "subjects" ? "active" : ""}
          onClick={() => {
            setTab("subjects");
            setActive(null);
            refreshSubjects();
          }}
        >
          Subjects
        </button>
        <button
          className={tab === "testing" ? "active" : ""}
          onClick={() => setTab("testing")}
        >
          Testing
        </button>
        <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
          Settings
        </button>
      </div>

      {tab === "testing" && <BuildTest />}

      {tab === "settings" && <Settings onSaved={refreshCfg} />}

      {tab === "subjects" && active === null && (
        <>
          {!keySet && (
            <div className="card">
              <span className="muted">
                Tip: set your AI provider API key in{" "}
                <button className="link" onClick={() => setTab("settings")}>
                  Settings
                </button>{" "}
                before generating. Glossary and timeline cards are generated without the AI.
              </span>
            </div>
          )}
          <Upload
            onCreated={(id) => {
              refreshSubjects();
              setActive(id);
            }}
          />
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Your subjects</h3>
            <div
              className="row"
              style={{ gap: 8, marginBottom: 16, alignItems: "center" }}
              onClick={(e) => e.stopPropagation()}
            >
              <input
                ref={importInputRef}
                type="file"
                accept=".zip,application/zip"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void importSubject(file);
                }}
              />
              <button
                type="button"
                disabled={importBusy}
                onClick={() => importInputRef.current?.click()}
              >
                {importBusy ? "Importing…" : "Import subject"}
              </button>
              <span className="muted">From a .acdec-subject.zip export file</span>
            </div>
            {importMsg && <p className="ok">{importMsg}</p>}
            {importErr && <div className="error">{importErr}</div>}
            {subjects.length === 0 && (
              <p className="muted">No subjects yet. Upload a guide above.</p>
            )}
            {subjects.map((s) => (
              <div className="subject-item" key={s.id} onClick={() => setActive(s.id)}>
                <div>
                  <strong>{s.name}</strong>
                  <div className="muted">
                    {s.filename} · {s.page_count} pages · {s.status}
                  </div>
                </div>
                <div className="row" onClick={(e) => e.stopPropagation()}>
                  <button className="ghost danger" onClick={(e) => deleteSubject(e, s.id, s.name)}>
                    Delete
                  </button>
                  <button className="ghost" onClick={(e) => exportSubject(e, s.id)}>
                    Export
                  </button>
                  <button className="ghost" onClick={() => setActive(s.id)}>
                    Open →
                  </button>
                </div>
              </div>
            ))}
            {deleteErr && <div className="error">{deleteErr}</div>}
          </div>
        </>
      )}

      {tab === "subjects" && active !== null && (
        <>
          <button className="link" onClick={() => setActive(null)}>
            ← back to subjects
          </button>
          <TreeView
            subjectId={active}
            textExportFormat={cfg?.text_export_format ?? "csv"}
          />
        </>
      )}
    </div>
  );
}
