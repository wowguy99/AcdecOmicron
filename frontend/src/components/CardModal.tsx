import { useEffect, useState } from "react";
import { api } from "../api";
import type { Card } from "../types";

export function CardModal({
  nodeId,
  title,
  onClose,
  onRegenerate,
}: {
  nodeId: number;
  title: string;
  onClose: () => void;
  onRegenerate?: () => Promise<void>;
}) {
  const [cards, setCards] = useState<Card[]>([]);
  const [track, setTrack] = useState<"A" | "master">("master");
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [regenErr, setRegenErr] = useState("");

  function load() {
    setLoading(true);
    api.listCards(nodeId, track).then((c) => {
      setCards(c);
      setLoading(false);
    });
  }
  useEffect(load, [nodeId, track]);

  async function save(card: Card) {
    await api.updateCard(card.id, card.front, card.back, card.tag);
  }
  async function remove(id: number) {
    await api.deleteCard(id);
    setCards(cards.filter((c) => c.id !== id));
  }
  function edit(id: number, patch: Partial<Card>) {
    setCards(cards.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }

  async function regen() {
    if (!onRegenerate) return;
    setRegenErr("");
    setRegenerating(true);
    try {
      await onRegenerate();
      load();
    } catch (e: unknown) {
      setRegenErr(e instanceof Error ? e.message : "Regenerate failed.");
    } finally {
      setRegenerating(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="row spread">
          <h3 style={{ margin: 0 }}>Cards — {title}</h3>
          <div className="row">
            {onRegenerate && (
              <button
                type="button"
                className="ghost"
                disabled={regenerating}
                title="Delete AI cards for this topic and regenerate from current section text"
                onClick={() => void regen()}
              >
                {regenerating ? "Regenerating…" : "↻ Regenerate"}
              </button>
            )}
            <button type="button" className="ghost" onClick={onClose}>Close</button>
          </div>
        </div>
        {regenErr && <div className="error">{regenErr}</div>}
        <div className="row" style={{ margin: "12px 0" }}>
          <button
            className={track === "master" ? "primary" : "ghost"}
            onClick={() => setTrack("master")}
          >
            Master (A + captions)
          </button>
          <button
            className={track === "A" ? "primary" : "ghost"}
            onClick={() => setTrack("A")}
          >
            Text-only (A)
          </button>
          <span className="muted">{cards.length} cards</span>
        </div>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: "38%" }}>Front</th>
                <th style={{ width: "38%" }}>Back</th>
                <th>Tag</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {cards.map((c) => (
                <tr key={c.id}>
                  <td>
                    <textarea
                      rows={2}
                      value={c.front}
                      onChange={(e) => edit(c.id, { front: e.target.value })}
                      onBlur={() => save(c)}
                    />
                  </td>
                  <td>
                    <textarea
                      rows={2}
                      value={c.back}
                      onChange={(e) => edit(c.id, { back: e.target.value })}
                      onBlur={() => save(c)}
                    />
                  </td>
                  <td>
                    <input
                      value={c.tag}
                      onChange={(e) => edit(c.id, { tag: e.target.value })}
                      onBlur={() => save(c)}
                    />
                    <span className="pill" style={{ marginTop: 4, display: "inline-block" }}>
                      {c.track === "B" ? "caption" : c.source}
                    </span>
                  </td>
                  <td>
                    <button className="ghost danger" onClick={() => remove(c.id)}>✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
