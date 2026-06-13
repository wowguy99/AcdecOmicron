import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SubjectSummary, Tree, TreeNode } from "../types";

type TestType = "frq" | "mcq4" | "mcq5";
type Format = "online" | "print";
type Timing = "timed" | "untimed";

function collectDescendantIds(node: TreeNode): number[] {
  const ids = [node.id];
  for (const child of node.children) {
    ids.push(...collectDescendantIds(child));
  }
  return ids;
}

function collectAllNodeIds(sections: TreeNode[]): number[] {
  const ids: number[] = [];
  for (const section of sections) {
    ids.push(...collectDescendantIds(section));
  }
  return ids;
}

function getCheckboxState(
  node: TreeNode,
  selectedIds: Set<number>
): "checked" | "indeterminate" | "unchecked" {
  const subtreeIds = collectDescendantIds(node);
  const selectedCount = subtreeIds.filter((id) => selectedIds.has(id)).length;
  if (selectedCount === 0) return "unchecked";
  if (selectedIds.has(node.id) || selectedCount === subtreeIds.length) return "checked";
  return "indeterminate";
}

function SegButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`seg${active ? " active" : ""}`}
      aria-pressed={active}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function CheckboxNode({
  node,
  depth,
  selectedIds,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  selectedIds: Set<number>;
  onToggle: (node: TreeNode) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const state = getCheckboxState(node, selectedIds);
  const checkboxId = `build-test-node-${node.id}`;

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = state === "indeterminate";
    }
  }, [state, selectedIds]);

  return (
    <div className="tree-node" style={{ marginLeft: depth ? 6 : 0 }}>
      <label
        htmlFor={checkboxId}
        className={`node-line ${node.tier} ${node.excluded ? "excluded" : ""}`}
      >
        <input
          ref={inputRef}
          id={checkboxId}
          type="checkbox"
          checked={state === "checked"}
          onChange={() => onToggle(node)}
        />
        <span className="node-title">{node.title}</span>
        {node.deterministic && <span className="badge det">auto</span>}
        {node.excluded && <span className="badge exc">excluded</span>}
        <span className="count">
          {node.cards_a}A / {node.cards_b}B
        </span>
      </label>
      {node.children.map((child) => (
        <CheckboxNode
          key={child.id}
          node={child}
          depth={depth + 1}
          selectedIds={selectedIds}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

export function BuildTest() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [loadingSubjects, setLoadingSubjects] = useState(true);
  const [subjectsErr, setSubjectsErr] = useState("");
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [tree, setTree] = useState<Tree | null>(null);
  const [loadingTree, setLoadingTree] = useState(false);
  const [treeErr, setTreeErr] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [testType, setTestType] = useState<TestType | null>(null);
  const [format, setFormat] = useState<Format | null>(null);
  const [timing, setTiming] = useState<Timing>("untimed");
  const [timeLimit, setTimeLimit] = useState("");
  const [showComingSoon, setShowComingSoon] = useState(false);

  useEffect(() => {
    setLoadingSubjects(true);
    setSubjectsErr("");
    api
      .listSubjects()
      .then((list) => {
        setSubjects(list);
        setLoadingSubjects(false);
      })
      .catch((e: Error) => {
        setSubjectsErr(e.message);
        setLoadingSubjects(false);
      });
  }, []);

  useEffect(() => {
    if (subjectId === null) {
      setTree(null);
      setTreeErr("");
      setLoadingTree(false);
      return;
    }

    let cancelled = false;
    setLoadingTree(true);
    setTreeErr("");
    setTree(null);

    api
      .getTree(subjectId)
      .then((t) => {
        if (!cancelled) {
          setTree(t);
          setLoadingTree(false);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setTreeErr(e.message);
          setLoadingTree(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [subjectId]);

  function onSubjectChange(raw: string) {
    const id = raw === "" ? null : Number(raw);
    setSubjectId(id);
    setSelectedIds(new Set());
    setTree(null);
    setTreeErr("");
    setShowComingSoon(false);
    setTestType(null);
    setFormat(null);
    setTiming("untimed");
    setTimeLimit("");
  }

  function toggleNode(node: TreeNode) {
    const ids = collectDescendantIds(node);
    const allSelected = ids.every((id) => selectedIds.has(id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        for (const id of ids) next.delete(id);
      } else {
        for (const id of ids) next.add(id);
      }
      return next;
    });
  }

  function toggleSelectAll() {
    if (!tree) return;
    const allIds = collectAllNodeIds(tree.sections);
    const allSelected = allIds.length > 0 && allIds.every((id) => selectedIds.has(id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        for (const id of allIds) next.delete(id);
      } else {
        for (const id of allIds) next.add(id);
      }
      return next;
    });
  }

  const selectAllState = (() => {
    if (!tree || tree.sections.length === 0) return "unchecked" as const;
    const allIds = collectAllNodeIds(tree.sections);
    const selectedCount = allIds.filter((id) => selectedIds.has(id)).length;
    if (selectedCount === 0) return "unchecked" as const;
    if (selectedCount === allIds.length) return "checked" as const;
    return "indeterminate" as const;
  })();

  const selectAllRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectAllState === "indeterminate";
    }
  }, [selectAllState, selectedIds]);

  return (
    <div>
      <div className="card build-section">
        <h3 style={{ marginTop: 0 }}>Build Test</h3>
        <p className="muted">
          Choose a subject and content, configure the test type and format, then generate.
        </p>
      </div>

      <div className="card build-section">
        <h3 style={{ marginTop: 0 }}>1. Select Test Content</h3>

        {loadingSubjects && <p className="muted">Loading subjects…</p>}
        {subjectsErr && <div className="error">{subjectsErr}</div>}
        {!loadingSubjects && !subjectsErr && subjects.length === 0 && (
          <p className="muted">No subjects yet. Upload a guide in the Subjects tab.</p>
        )}

        {!loadingSubjects && subjects.length > 0 && (
          <>
            <label htmlFor="build-test-subject">Subject</label>
            <select
              id="build-test-subject"
              value={subjectId ?? ""}
              onChange={(e) => onSubjectChange(e.target.value)}
            >
              <option value="">— choose a subject —</option>
              {subjects.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.status})
                </option>
              ))}
            </select>
          </>
        )}

        {subjectId !== null && loadingTree && <p className="muted">Loading blueprint…</p>}
        {subjectId !== null && treeErr && <div className="error">{treeErr}</div>}

        {tree && (
          <div className="checkbox-tree" style={{ marginTop: 16 }}>
            <p className="muted">{selectedIds.size} items selected</p>

            <label className="node-line section">
              <input
                ref={selectAllRef}
                id="build-test-select-all"
                type="checkbox"
                checked={selectAllState === "checked"}
                onChange={toggleSelectAll}
              />
              <span className="node-title">
                {tree.subject.name} (whole subject)
              </span>
              <span className="count">
                {tree.subject.cards_a}A / {tree.subject.cards_b}B
              </span>
            </label>

            {tree.sections.map((section) => (
              <CheckboxNode
                key={section.id}
                node={section}
                depth={0}
                selectedIds={selectedIds}
                onToggle={toggleNode}
              />
            ))}
          </div>
        )}
      </div>

      <div className="card build-section">
        <h3 style={{ marginTop: 0 }}>2. Select Test Type</h3>
        <div className="seg-group">
          <SegButton active={testType === "frq"} onClick={() => setTestType("frq")}>
            FRQ
          </SegButton>
          <SegButton active={testType === "mcq4"} onClick={() => setTestType("mcq4")}>
            MCQ (4 options)
          </SegButton>
          <SegButton active={testType === "mcq5"} onClick={() => setTestType("mcq5")}>
            MCQ (5 options)
          </SegButton>
        </div>
      </div>

      <div className="card build-section">
        <h3 style={{ marginTop: 0 }}>3. Select Test Format</h3>
        <div className="seg-group">
          <SegButton active={format === "online"} onClick={() => setFormat("online")}>
            Online
          </SegButton>
          <SegButton active={format === "print"} onClick={() => setFormat("print")}>
            Print
          </SegButton>
        </div>

        {format === "online" && (
          <div style={{ marginTop: 16 }}>
            <div className="seg-group">
              <SegButton active={timing === "timed"} onClick={() => setTiming("timed")}>
                Timed
              </SegButton>
              <SegButton active={timing === "untimed"} onClick={() => setTiming("untimed")}>
                Untimed
              </SegButton>
            </div>
            {timing === "timed" && (
              <div style={{ marginTop: 12 }}>
                <label htmlFor="build-test-time-limit">Time limit (minutes)</label>
                <input
                  id="build-test-time-limit"
                  type="number"
                  min={1}
                  value={timeLimit}
                  onChange={(e) => setTimeLimit(e.target.value)}
                />
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card build-section">
        <h3 style={{ marginTop: 0 }}>4. Generate</h3>
        <button type="button" className="primary" onClick={() => setShowComingSoon(true)}>
          Generate Test
        </button>
        {showComingSoon && (
          <div className="coming-soon">
            Coming soon — test generation is not available yet.
          </div>
        )}
      </div>
    </div>
  );
}
