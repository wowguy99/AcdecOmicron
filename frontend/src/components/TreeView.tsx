import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Tree, TreeNode } from "../types";
import { CardModal } from "./CardModal";
import { SubsectionInfoModal } from "./SubsectionInfoModal";
import { ValidateModal } from "./ValidateModal";

const GENERATABLE = new Set(["BODY", "INTRODUCTION", "CONCLUSION"]);

export function TreeView({
  subjectId,
  textExportFormat = "csv",
}: {
  subjectId: number;
  textExportFormat?: "csv" | "google_sheet";
}) {
  const [tree, setTree] = useState<Tree | null>(null);
  const [err, setErr] = useState("");
  const [nodeErr, setNodeErr] = useState("");
  const [nodeMsg, setNodeMsg] = useState("");
  const [reparsing, setReparsing] = useState(false);
  const [cardNode, setCardNode] = useState<{ id: number; title: string } | null>(null);
  const [validateNode, setValidateNode] = useState<{
    id: number;
    title: string;
    track: "A" | "master";
  } | null>(null);
  const [infoNode, setInfoNode] = useState<{ id: number; title: string } | null>(null);
  const pollRef = useRef<number | null>(null);
  const wasGenerating = useRef(false);
  const [jobWatch, setJobWatch] = useState(false);

  function refresh() {
    api.getTree(subjectId).then(setTree).catch((e) => setErr(e.message));
  }
  useEffect(() => {
    refresh();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [subjectId]);

  const job = tree?.job;
  const status = tree?.subject.status;
  const generating = job?.status === "running" || status === "generating";
  const showRunning = generating || jobWatch;

  useEffect(() => {
    if (showRunning && !pollRef.current) {
      pollRef.current = window.setInterval(refresh, 800);
    }
    if (!showRunning && pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (wasGenerating.current && !showRunning) {
      refresh();
    }
    wasGenerating.current = showRunning;
  }, [showRunning]);

  useEffect(() => {
    if (!jobWatch) return;
    if (generating) return;
    const terminal = job?.status === "done" || job?.status === "error" || job?.status === "cancelled";
    if (terminal) setJobWatch(false);
  }, [jobWatch, generating, job?.status]);

  function notifyJobStarted() {
    setJobWatch(true);
    setCardNode(null);
    refresh();
  }

  if (err) return <div className="card error">{err}</div>;
  if (!tree) return <div className="card">Loading blueprint…</div>;

  const preApproval = status === "uploaded";
  const showDownloads = !preApproval;

  async function approve() {
    try {
      await api.approve(subjectId);
      refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function handleRegenerate(nodeId: number) {
    setNodeErr("");
    setNodeMsg("");
    try {
      const res = await api.regenerate(nodeId);
      if (res.message) setNodeMsg(res.message);
      if (res.started) {
        notifyJobStarted();
      } else {
        refresh();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Regenerate failed.";
      setNodeErr(msg);
      throw e;
    }
  }

  return (
    <div>
      <div className="card">
        <div className="row spread">
          <div>
            <h3 style={{ margin: 0 }}>{tree.subject.name}</h3>
            <span className="muted">
              {tree.subject.page_count} pages · status: {status} ·{" "}
              {tree.subject.cards_a} text cards / {tree.subject.cards_b} caption cards
            </span>
          </div>
          <div className="row">
            {showDownloads && (
              <button
                type="button"
                className="ghost"
                disabled={showRunning || reparsing}
                title="Re-run the PDF parser and refresh section text (keeps your tree edits). Use ↻ on a section afterward to rebuild cards."
                onClick={() => {
                  setNodeErr("");
                  setNodeMsg("");
                  setReparsing(true);
                  api
                    .reparseSubject(subjectId)
                    .then((res) => {
                      const warn =
                        res.warnings.length > 0 ? ` ${res.warnings.join(" ")}` : "";
                      setNodeMsg(
                        `Re-parsed PDF (${res.nodes_updated} nodes updated).${warn} Use ↻ on affected sections to rebuild cards.`
                      );
                      refresh();
                    })
                    .catch((e: Error) => setNodeErr(e.message))
                    .finally(() => setReparsing(false));
                }}
              >
                {reparsing ? "Re-parsing…" : "Re-parse PDF"}
              </button>
            )}
            {showRunning && (
              <button
                className="ghost danger"
                title="Stop after the current chunk finishes — no further AI calls"
                onClick={() => api.stopGeneration(subjectId).then(refresh)}
              >
                Stop running
              </button>
            )}
            <span className="muted">Tags:</span>
            {tree.tags.map((t) => (
              <span className="badge" key={t.name} title={t.definition}>{t.name}</span>
            ))}
          </div>
        </div>

        {preApproval && (
          <div style={{ marginTop: 16 }}>
            <p className="muted">
              Review and edit the structure below (rename, delete, exclude, merge).
              After approval, use <strong>Generate</strong> on each section to create
              flashcards one section at a time (saves API quota).
            </p>
            <button className="primary" onClick={approve}>Approve tree structure</button>
          </div>
        )}

        {(showRunning || (job && !preApproval)) && (
          <div style={{ marginTop: 16 }}>
            <div className="row spread">
              <span className={job?.status === "error" ? "error" : "muted"}>
                {showRunning
                  ? `running — ${job?.message ?? "Starting generation…"} (${job?.completed ?? 0}/${job?.total ?? "?"} chunks)`
                  : `${job!.status} — ${job!.message} (${job!.completed}/${job!.total} chunks)`}
              </span>
              <div className="row">
                {showRunning && (
                  <button
                    className="ghost danger"
                    title="Stop after the current chunk finishes — no further AI calls"
                    onClick={() => api.stopGeneration(subjectId).then(refresh)}
                  >
                    Stop running
                  </button>
                )}
                {job && (job.status === "paused" || job.status === "error") && (
                  <button className="ghost" onClick={() => api.resume(subjectId).then(refresh)}>
                    Resume
                  </button>
                )}
              </div>
            </div>
            {tree.chunk_errors.length > 0 && (
              <ul className="chunk-errors">
                {tree.chunk_errors.map((e) => (
                  <li key={e.id}>
                    <strong>
                      {e.section_title && e.tier === "subheader"
                        ? `${e.section_title} › ${e.node_title}`
                        : e.node_title}
                    </strong>
                    {" · "}
                    {e.track === "B" ? "caption" : "text"} chunk {e.idx + 1}
                    {e.attempts > 1 ? ` (${e.attempts} attempts)` : ""}: {e.error}
                  </li>
                ))}
              </ul>
            )}
            <div className="progress" style={{ marginTop: 8 }}>
              <div
                style={{
                  width: `${
                    showRunning && !job?.total
                      ? 5
                      : job?.total
                        ? (100 * (job.completed ?? 0)) / job.total
                        : 0
                  }%`,
                }}
              />
            </div>
          </div>
        )}
        {nodeMsg && <p className="ok" style={{ marginTop: 16, marginBottom: 0 }}>{nodeMsg}</p>}
        {nodeErr && <div className="error" style={{ marginTop: nodeMsg ? 8 : 16 }}>{nodeErr}</div>}
      </div>

      <div className="card">
        {/* Subject-level downloads */}
        {showDownloads && (
          <div className="node-line section">
            <span className="node-title">{tree.subject.name} (whole subject)</span>
            <span className="count">
              {tree.subject.cards_a}A / {tree.subject.cards_b}B
            </span>
            <DownloadButtons
              nodeId={subjectId}
              a={tree.subject.cards_a}
              b={tree.subject.cards_b}
              validated={tree.subject.all_validated}
              subjectDownload
              validateHint="Validate each section below first"
              onValidate={() => {}}
              textExportFormat={textExportFormat}
              onExportError={setNodeErr}
            />
          </div>
        )}
        {tree.sections.map((s) => (
          <NodeRow
            key={s.id}
            node={s}
            depth={0}
            showDownloads={showDownloads}
            editable={preApproval}
            jobRunning={showRunning}
            onChanged={refresh}
            onError={setNodeErr}
            onRegenerate={handleRegenerate}
            onJobStarted={notifyJobStarted}
            onReviewCards={(id, title) => setCardNode({ id, title })}
            onValidate={(id, title, track) => setValidateNode({ id, title, track })}
            onInfo={(id, title) => setInfoNode({ id, title })}
            textExportFormat={textExportFormat}
            onExportError={setNodeErr}
          />
        ))}
      </div>

      {cardNode && (
        <CardModal
          nodeId={cardNode.id}
          title={cardNode.title}
          onClose={() => setCardNode(null)}
          onRegenerate={async () => {
            await handleRegenerate(cardNode.id);
          }}
        />
      )}
      {validateNode && (
        <ValidateModal
          nodeId={validateNode.id}
          title={validateNode.title}
          track={validateNode.track}
          onClose={() => setValidateNode(null)}
          onComplete={refresh}
        />
      )}
      {infoNode && (
        <SubsectionInfoModal
          nodeId={infoNode.id}
          title={infoNode.title}
          onClose={() => setInfoNode(null)}
        />
      )}
    </div>
  );
}

function NodeRow({
  node,
  depth,
  showDownloads,
  editable,
  jobRunning,
  onChanged,
  onError,
  onRegenerate,
  onJobStarted,
  onReviewCards,
  onValidate,
  onInfo,
  textExportFormat = "csv",
  onExportError,
}: {
  node: TreeNode;
  depth: number;
  showDownloads: boolean;
  editable: boolean;
  jobRunning: boolean;
  onChanged: () => void;
  onError: (msg: string) => void;
  onRegenerate: (nodeId: number) => Promise<void>;
  onJobStarted: () => void;
  onReviewCards: (id: number, title: string) => void;
  onValidate: (id: number, title: string, track: "A" | "master") => void;
  onInfo: (id: number, title: string) => void;
  textExportFormat?: "csv" | "google_sheet";
  onExportError?: (msg: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [title, setTitle] = useState(node.title);

  async function rename() {
    await api.renameNode(node.id, title);
    setRenaming(false);
    onChanged();
  }

  const isGeneratableNode =
    node.tier === "section" || node.tier === "subheader";
  const scopeLabel = node.tier === "subheader" ? "this topic" : "this section";

  const canGenerate =
    showDownloads &&
    isGeneratableNode &&
    !node.excluded &&
    GENERATABLE.has(node.section_type) &&
    ((node.chunks_pending ?? 0) > 0 || (node.chunks_failed ?? 0) > 0);

  const needsGenerate =
    (node.chunks_pending ?? 0) > 0 || (node.chunks_failed ?? 0) > 0;
  const hasCards = (node.cards_a ?? 0) > 0 || (node.cards_b ?? 0) > 0;
  const canValidate =
    hasCards && !needsGenerate && (node.chunks_failed ?? 0) === 0;
  const generateLabel =
    (node.chunks_failed ?? 0) > 0
      ? "Retry"
      : (node.chunks_done ?? 0) > 0
        ? "Continue"
        : "Generate";

  return (
    <div className="tree-node" style={{ marginLeft: depth ? 6 : 0 }}>
      <div className={`node-line ${node.tier} ${node.excluded ? "excluded" : ""}`}>
        {node.children.length > 0 ? (
          <button className="link" onClick={() => setOpen(!open)} style={{ width: 18 }}>
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span style={{ width: 18 }} />
        )}

        {renaming ? (
          <input
            value={title}
            autoFocus
            onChange={(e) => setTitle(e.target.value)}
            onBlur={rename}
            onKeyDown={(e) => e.key === "Enter" && rename()}
            style={{ flex: 1 }}
          />
        ) : (
          <span
            className="node-title"
            onClick={() => (showDownloads ? onReviewCards(node.id, node.title) : setRenaming(true))}
            title={showDownloads ? "Review cards" : "Click to rename"}
          >
            {node.title}
          </span>
        )}

        {node.deterministic && <span className="badge det">auto</span>}
        {node.excluded && <span className="badge exc">excluded</span>}

        {showDownloads && (
          <span className="count">
            {node.cards_a}A / {node.cards_b}B
          </span>
        )}

        {showDownloads && (node.chunks_failed ?? 0) > 0 && (
          <span className="badge exc" title="Some chunks failed — see error details above">
            failed
          </span>
        )}

        {node.tier === "subheader" && (
          <button
            type="button"
            className="ghost"
            title="View parse details and tag counts"
            onClick={(e) => {
              e.stopPropagation();
              onInfo(node.id, node.title);
            }}
          >
            info
          </button>
        )}

        {editable && (
          <span className="dl">
            <button className="ghost" onClick={() => setRenaming(true)}>rename</button>
            <button
              className="ghost"
              onClick={() => api.excludeNode(node.id, !node.excluded).then(onChanged)}
            >
              {node.excluded ? "include" : "exclude"}
            </button>
            {node.tier === "subheader" && (
              <button
                className="ghost"
                onClick={() =>
                  api
                    .mergeNode(node.id)
                    .then(() => {
                      onError("");
                      onChanged();
                    })
                    .catch((e: Error) => onError(e.message))
                }
              >
                merge↑
              </button>
            )}
            <button className="ghost danger" onClick={() => api.deleteNode(node.id).then(onChanged)}>
              delete
            </button>
          </span>
        )}

        {canGenerate && (
          <button
            className="ghost"
            disabled={jobRunning}
            title={
              jobRunning
                ? "Generation in progress"
                : `${generateLabel}: run AI on pending text chunks for ${scopeLabel} only (skips chunks already done)`
            }
            onClick={() =>
              api
                .generateSection(node.id)
                .then((res) => {
                  onError("");
                  if (!res.started && res.message) onError(res.message);
                  if (res.started) {
                    onJobStarted();
                  } else {
                    onChanged();
                  }
                })
                .catch((e: Error) => onError(e.message))
            }
          >
            {generateLabel}
          </button>
        )}

        {showDownloads && isGeneratableNode && !needsGenerate && (
          <span className="muted" style={{ fontSize: 12 }} title="Fully generated">
            ✓
          </span>
        )}

        {showDownloads && (
          <DownloadButtons
            nodeId={node.id}
            a={node.cards_a}
            b={node.cards_b}
            validated={node.validated}
            canValidate={canValidate}
            onValidate={(track) => onValidate(node.id, node.title, track)}
            showRegen={
              isGeneratableNode &&
              ((node.cards_a ?? 0) > 0 ||
                (node.cards_b ?? 0) > 0 ||
                (node.chunks_failed ?? 0) > 0)
            }
            regenScope={scopeLabel}
            regenBusy={regenerating}
            jobRunning={jobRunning}
            onRegen={() => {
              setRegenerating(true);
              return onRegenerate(node.id).finally(() => setRegenerating(false));
            }}
            textExportFormat={textExportFormat}
            onExportError={onExportError}
          />
        )}
      </div>

      {open &&
        node.children.map((c) => (
          <NodeRow
            key={c.id}
            node={c}
            depth={depth + 1}
            showDownloads={showDownloads}
            editable={editable}
            jobRunning={jobRunning}
            onChanged={onChanged}
            onError={onError}
            onRegenerate={onRegenerate}
            onJobStarted={onJobStarted}
            onReviewCards={onReviewCards}
            onValidate={onValidate}
            onInfo={onInfo}
            textExportFormat={textExportFormat}
            onExportError={onExportError}
          />
        ))}
    </div>
  );
}

function DownloadButtons({
  nodeId,
  a,
  b,
  validated,
  canValidate = false,
  subjectDownload,
  validateHint,
  onValidate,
  showRegen,
  regenScope = "this section",
  regenBusy = false,
  jobRunning = false,
  onRegen,
  textExportFormat = "csv",
  onExportError,
}: {
  nodeId: number;
  a: number;
  b: number;
  validated: boolean;
  canValidate?: boolean;
  subjectDownload?: boolean;
  validateHint?: string;
  onValidate: (track: "A" | "master") => void;
  showRegen?: boolean;
  regenScope?: string;
  regenBusy?: boolean;
  jobRunning?: boolean;
  onRegen?: () => void | Promise<void>;
  textExportFormat?: "csv" | "google_sheet";
  onExportError?: (msg: string) => void;
}) {
  const hasMaster = a > 0 || b > 0;
  const hasA = a > 0;
  const [exporting, setExporting] = useState(false);

  function downloadHref(track: "A" | "master") {
    if (subjectDownload) return `/api/subjects/${nodeId}/download?track=${track}`;
    return api.downloadUrl(nodeId, track);
  }

  async function exportTextOnly() {
    if (!validated || !hasA || exporting) return;
    setExporting(true);
    onExportError?.("");
    try {
      const result = subjectDownload
        ? await api.exportSubjectSheet(nodeId)
        : await api.exportNodeSheet(nodeId);
      window.open(result.url, "_blank", "noopener,noreferrer");
    } catch (e: unknown) {
      onExportError?.(e instanceof Error ? e.message : "Google Sheet export failed.");
    } finally {
      setExporting(false);
    }
  }

  const textOnlyEnabled = hasA && validated;
  const useGoogleSheet = textExportFormat === "google_sheet";

  return (
    <span className="dl" onClick={(e) => e.stopPropagation()}>
      {!subjectDownload && (
        <button
          type="button"
          className={`ghost validate-btn${validated ? " validated" : ""}`}
          disabled={!canValidate}
          title={
            validated
              ? "Validation complete — click to re-run walkthrough"
              : canValidate
                ? "Run validation walkthrough before downloading"
                : "Generate cards for this section first"
          }
          onClick={() => onValidate(hasA ? "A" : "master")}
        >
          {validated ? "✓ Validated" : "Validate"}
        </button>
      )}
      {subjectDownload && validated && (
        <span className="validate-hint validated">✓ All sections validated</span>
      )}
      {subjectDownload && !validated && validateHint && (
        <span className="muted validate-hint">{validateHint}</span>
      )}
      {useGoogleSheet ? (
        <button
          type="button"
          className={`ghost${textOnlyEnabled ? "" : " disabled"}`}
          disabled={!textOnlyEnabled || exporting}
          title={
            validated
              ? "Create a new Google Sheet with text-only cards"
              : "Validate first"
          }
          onClick={() => void exportTextOnly()}
        >
          {exporting ? "Exporting…" : "Text-Only"}
        </button>
      ) : (
        <a
          className={textOnlyEnabled ? "" : "disabled"}
          href={textOnlyEnabled ? downloadHref("A") : undefined}
          title={validated ? "Download text-only CSV" : "Validate first"}
        >
          Text-Only
        </a>
      )}
      <a
        className={`master ${hasMaster && validated ? "" : "disabled"}`}
        href={hasMaster && validated ? downloadHref("master") : undefined}
        title={validated ? "Download master CSV" : "Validate first"}
      >
        Master
      </a>
      {showRegen && onRegen && (
        <button
          type="button"
          className="ghost"
          disabled={jobRunning || regenBusy}
          onClick={() => void onRegen()}
          title={
            jobRunning
              ? "Wait for the current generation job to finish"
              : `Regenerate: delete existing AI cards for ${regenScope} and run AI again from scratch`
          }
        >
          {regenBusy ? "…" : "↻"}
        </button>
      )}
    </span>
  );
}

