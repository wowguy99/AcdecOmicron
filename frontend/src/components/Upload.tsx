import { useState } from "react";
import { api } from "../api";

interface TagDraft {
  name: string;
  definition: string;
}

export function Upload({ onCreated }: { onCreated: (id: number) => void }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isIad, setIsIad] = useState(false);
  const [tags, setTags] = useState<TagDraft[]>([
    { name: "statistic", definition: "A numeric fact, measurement, or quantity." },
    { name: "date", definition: "A specific year, date, or time period." },
  ]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function setTag(i: number, patch: Partial<TagDraft>) {
    setTags(tags.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  }

  async function submit() {
    setErr("");
    if (!file || !name.trim()) {
      setErr("Provide a subject name and a PDF.");
      return;
    }
    setBusy(true);
    try {
      const cleaned = tags.filter((t) => t.name.trim());
      const { subject_id } = await api.uploadSubject(name.trim(), file, cleaned, isIad);
      onCreated(subject_id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Upload a guide</h3>
      <label>Subject name</label>
      <input
        placeholder="e.g. Social Science"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <label>PDF guide</label>
      <input
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={isIad}
          onChange={(e) => setIsIad(e.target.checked)}
        />
        <span>IAD guide (author, title field order; enables IAD-specific parsing)</span>
      </label>

      <label style={{ marginTop: 18 }}>
        Tags (each card gets exactly one). Definitions guide the AI's choice.
      </label>
      {tags.map((t, i) => (
        <div className="tag-row" key={i}>
          <input
            placeholder="tag name"
            value={t.name}
            onChange={(e) => setTag(i, { name: e.target.value })}
          />
          <input
            placeholder="short definition"
            value={t.definition}
            onChange={(e) => setTag(i, { definition: e.target.value })}
          />
          <button className="ghost danger" onClick={() => setTags(tags.filter((_, x) => x !== i))}>
            ✕
          </button>
        </div>
      ))}
      <button className="link" onClick={() => setTags([...tags, { name: "", definition: "" }])}>
        + add tag
      </button>
      <p className="muted">A built-in "other" tag is always added automatically.</p>

      <div style={{ marginTop: 14 }}>
        <button className="primary" onClick={submit} disabled={busy}>
          {busy ? "Parsing PDF…" : "Upload & build blueprint"}
        </button>
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  );
}
