import { useEffect, useState } from "react";
import { api } from "../api";
import type { SubsectionInfo } from "../types";

function formatPage(
  printed: number | null,
  pdf: number | null
): string {
  if (printed != null && pdf != null) {
    return `Printed p. ${printed} (PDF p. ${pdf})`;
  }
  if (pdf != null) {
    return `PDF p. ${pdf}`;
  }
  return "Page unknown";
}

export function SubsectionInfoModal({
  nodeId,
  title,
  onClose,
}: {
  nodeId: number;
  title: string;
  onClose: () => void;
}) {
  const [info, setInfo] = useState<SubsectionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    setLoading(true);
    setErr("");
    api
      .getSubsectionInfo(nodeId)
      .then((r) => {
        setInfo(r);
        setLoading(false);
      })
      .catch((e: Error) => {
        setErr(e.message);
        setLoading(false);
      });
  }, [nodeId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal info-modal" onClick={(e) => e.stopPropagation()}>
        <div className="row spread">
          <h3 style={{ margin: 0 }}>Info — {title}</h3>
          <button type="button" className="ghost" onClick={onClose}>
            Close
          </button>
        </div>

        {loading && <p className="muted">Loading…</p>}
        {err && <p className="error">{err}</p>}

        {info && !loading && (
          <>
            <p className="muted" style={{ marginTop: 8 }}>
              {info.section_type}
              {info.subheader_kind ? ` · ${info.subheader_kind.replace(/_/g, " ")}` : ""}
            </p>

            <section style={{ marginTop: 16 }}>
              <h4 style={{ margin: "0 0 8px" }}>Source text</h4>
              <p className="muted" style={{ fontSize: 12, margin: "0 0 12px" }}>
                End page is the next subsection boundary; content may end on the prior page.
              </p>
              <div className="info-snippet">
                <label>First sentence</label>
                <p>{info.first_sentence}</p>
                <span className="muted" style={{ fontSize: 12 }}>
                  {formatPage(info.printed_start_page, info.pdf_start_page)}
                </span>
              </div>
              <div className="info-snippet" style={{ marginTop: 12 }}>
                <label>Last sentence</label>
                <p>{info.last_sentence}</p>
                <span className="muted" style={{ fontSize: 12 }}>
                  {formatPage(info.printed_end_page, info.pdf_end_page)}
                </span>
              </div>
            </section>

            <section style={{ marginTop: 20 }}>
              <h4 style={{ margin: "0 0 8px" }}>Tag breakdown</h4>
              {info.cards_total === 0 ? (
                <p className="muted">No cards generated yet.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Tag</th>
                      <th>Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {info.tag_counts.map((t) => (
                      <tr key={t.name}>
                        <td title={t.definition || undefined}>
                          {t.name}
                          {t.builtin ? " (builtin)" : ""}
                        </td>
                        <td>{t.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section style={{ marginTop: 16 }}>
              <p className="muted" style={{ fontSize: 13, margin: 0 }}>
                Body: {info.body_char_count.toLocaleString()} chars
                {info.caption_char_count > 0
                  ? ` · Captions: ${info.caption_char_count.toLocaleString()} chars`
                  : ""}
                {info.cards_total > 0
                  ? ` · ${info.cards_total} card${info.cards_total === 1 ? "" : "s"}`
                  : ""}
              </p>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
