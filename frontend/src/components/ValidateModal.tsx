import { useEffect, useState } from "react";
import { api } from "../api";
import type { ValidationItem, ValidationReport } from "../types";

export function ValidateModal({
  nodeId,
  title,
  track,
  onClose,
  onComplete,
}: {
  nodeId: number;
  title: string;
  track: "A" | "master";
  onClose: () => void;
  onComplete: () => void;
}) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [idx, setIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    setLoading(true);
    setErr("");
    setMsg("");
    api
      .validateNode(nodeId, track)
      .then((r) => {
        setReport(r);
        setIdx(0);
        setLoading(false);
      })
      .catch((e: Error) => {
        setErr(e.message);
        setLoading(false);
      });
  }, [nodeId, track]);

  const items = report?.items ?? [];
  const item: ValidationItem | undefined = items[idx];
  const remaining = items.length;
  const reviewed = report?.reviewed_count ?? 0;
  const total = report?.total_count ?? 0;
  const autoPassed = report?.auto_passed_count ?? 0;
  const flagged = report?.flagged_count ?? remaining;
  // Walkthrough scope: flagged cards still to review + already reviewed this validation.
  const walkthroughTotal = reviewed + remaining;
  const currentStep = reviewed + idx + 1;
  const walkthroughPct =
    walkthroughTotal > 0 ? (currentStep / walkthroughTotal) * 100 : 100;

  async function goNext() {
    if (!item || !report || saving || removing) return;
    const card = item;
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await api.reviewCard(nodeId, card.card_id, track, card.front, card.back, card.tag);
      const nextItems = report.items.filter((c) => c.card_id !== card.card_id);
      setReport({
        ...report,
        items: nextItems,
        reviewed_count: report.reviewed_count + 1,
        issue_count: nextItems.length,
      });
      setIdx((i) => Math.min(i, Math.max(0, nextItems.length - 1)));
      setMsg("Card saved and marked reviewed.");
      onComplete();
    } catch (e: any) {
      setErr(e?.message ?? "Failed to save card.");
    } finally {
      setSaving(false);
    }
  }

  async function removeCurrent() {
    if (!item || !report || removing) return;
    const removedId = item.card_id;

    setRemoving(true);
    setErr("");
    setMsg("");
    try {
      await api.deleteCard(removedId);
      setReport((prev) => {
        if (!prev) return prev;
        const nextItems = prev.items.filter((c) => c.card_id !== removedId);
        return {
          ...prev,
          items: nextItems,
          issue_count: nextItems.length,
          flagged_count: Math.max(0, prev.flagged_count - 1),
        };
      });
      setIdx((i) => Math.min(i, Math.max(0, items.length - 2)));
      setMsg("Card removed.");
      onComplete();
    } catch (e: any) {
      setErr(e?.message ?? "Failed to remove card.");
    } finally {
      setRemoving(false);
    }
  }

  async function finish() {
    setSaving(true);
    setErr("");
    try {
      if (item) {
        await api.reviewCard(nodeId, item.card_id, track, item.front, item.back, item.tag);
      }
      await api.completeValidation(nodeId, track);
      onComplete();
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal validate-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row spread">
          <h3 style={{ margin: 0 }}>Validate — {title}</h3>
          <button type="button" className="ghost" onClick={onClose}>Close</button>
        </div>

        {loading && <p className="muted">Running checks…</p>}
        {err && <p className="error">{err}</p>}
        {msg && <p className="ok">{msg}</p>}

        {report && !loading && (
          <>
            <div className="validate-summary">
              <span className="muted">
                {remaining} need review
                {autoPassed > 0 ? ` · ${autoPassed} auto-passed` : ""}
                {reviewed > 0 ? ` · ${reviewed} already reviewed` : ""}
                {total > 0 ? ` · ${total} total` : ""}
                {flagged > 0 ? ` · ${flagged} flagged` : ""}
                {" · "}
                {report.ai_calls} AI check{report.ai_calls === 1 ? "" : "s"}
              </span>
              {report.warning && <span className="warn-text">{report.warning}</span>}
            </div>

            {remaining === 0 ? (
              <div>
                <p className="muted">
                  {flagged === 0
                    ? `All ${total} card${total === 1 ? "" : "s"} passed automated checks. Complete validation to enable downloads.`
                    : reviewed > 0
                      ? "All flagged cards have been reviewed. Complete validation to enable downloads."
                      : "No cards to validate for this track."}
                </p>
                <button
                  type="button"
                  className="primary"
                  style={{ marginTop: 12 }}
                  disabled={saving}
                  onClick={finish}
                >
                  {saving ? "Saving…" : "Complete validation"}
                </button>
              </div>
            ) : item ? (
              <>
                <div className="validate-progress">
                  Card {currentStep} of {walkthroughTotal} to review
                  {remaining > 0 ? ` (${remaining} left)` : ""}
                  <div className="progress" style={{ marginTop: 6 }}>
                    <div style={{ width: `${walkthroughPct}%` }} />
                  </div>
                </div>

                <div className="validate-card">
                  <label>Front</label>
                  <textarea
                    rows={2}
                    value={item.front}
                    disabled={removing || saving}
                    onChange={(e) =>
                      setReport({
                        ...report,
                        items: report.items.map((c) =>
                          c.card_id === item.card_id ? { ...c, front: e.target.value } : c
                        ),
                      })
                    }
                  />
                  <label>Back</label>
                  <textarea
                    rows={3}
                    value={item.back}
                    disabled={removing || saving}
                    onChange={(e) =>
                      setReport({
                        ...report,
                        items: report.items.map((c) =>
                          c.card_id === item.card_id ? { ...c, back: e.target.value } : c
                        ),
                      })
                    }
                  />

                  {item.flags.length > 0 && (
                    <div className="flag-list">
                      {item.flags.map((f) => (
                        <span key={f.code} className={`flag flag-${f.severity}`} title={f.message}>
                          {f.message}
                        </span>
                      ))}
                    </div>
                  )}

                  {item.ai_verdict && (
                    <div className={`ai-verdict ai-${item.ai_verdict}`}>
                      AI: {item.ai_verdict === "error" ? "Issue" : "OK"}
                      {item.ai_message ? ` — ${item.ai_message}` : ""}
                    </div>
                  )}

                  {item.source_snippet && (
                    <div className="source-snippet">
                      <label>Source text</label>
                      <p>{item.source_snippet}</p>
                    </div>
                  )}
                </div>

                <div className="row spread" style={{ marginTop: 16 }}>
                  <div className="row">
                    <button
                      type="button"
                      className="ghost"
                      disabled={idx === 0 || removing || saving}
                      onClick={() => setIdx(idx - 1)}
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      className="ghost danger"
                      disabled={removing || saving}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => removeCurrent()}
                      title="Remove this redundant card"
                    >
                      {removing ? "Removing…" : "Remove card"}
                    </button>
                  </div>
                  {idx < remaining - 1 ? (
                    <button
                      type="button"
                      className="primary"
                      disabled={removing || saving}
                      onClick={goNext}
                    >
                      {saving ? "Saving…" : "Next"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="primary"
                      disabled={saving || removing}
                      onClick={finish}
                    >
                      {saving ? "Saving…" : "Complete validation"}
                    </button>
                  )}
                </div>
              </>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
