import type { Card, LicenseStatus, ProviderConfig, SubjectSummary, SubsectionInfo, Tree, ValidationReport } from "./types";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getConfig: () => fetch("/api/config").then((r) => j<ProviderConfig>(r)),

  saveConfig: (cfg: Partial<ProviderConfig>) =>
    fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    }).then((r) => j<ProviderConfig>(r)),

  getLicense: () => fetch("/api/license").then((r) => j<LicenseStatus>(r)),

  saveLicense: (key: string) =>
    fetch("/api/license", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }).then((r) => j<LicenseStatus>(r)),

  listSubjects: () => fetch("/api/subjects").then((r) => j<SubjectSummary[]>(r)),

  deleteSubject: (id: number) =>
    fetch(`/api/subjects/${id}`, { method: "DELETE" }).then((r) => j<{ ok: boolean }>(r)),

  exportSubjectUrl: (id: number) => `/api/subjects/${id}/export`,

  importSubject: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/subjects/import", { method: "POST", body: fd }).then((r) =>
      j<{ subject_id: number; name: string }>(r)
    );
  },

  uploadSubject: (
    name: string,
    file: File,
    tags: { name: string; definition: string }[],
    isIad = false
  ) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("file", file);
    fd.append("tags", JSON.stringify(tags));
    fd.append("is_iad", isIad ? "true" : "false");
    return fetch("/api/subjects", { method: "POST", body: fd }).then((r) =>
      j<{ subject_id: number }>(r)
    );
  },

  getTree: (id: number) => fetch(`/api/subjects/${id}/tree`).then((r) => j<Tree>(r)),

  renameNode: (id: number, title: string) =>
    fetch(`/api/nodes/${id}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => j(r)),

  deleteNode: (id: number) =>
    fetch(`/api/nodes/${id}`, { method: "DELETE" }).then((r) => j(r)),

  excludeNode: (id: number, excluded: boolean) =>
    fetch(`/api/nodes/${id}/exclude`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ excluded }),
    }).then((r) => j(r)),

  mergeNode: (id: number) =>
    fetch(`/api/nodes/${id}/merge`, { method: "POST" }).then((r) => j(r)),

  approve: (id: number) =>
    fetch(`/api/subjects/${id}/approve`, { method: "POST" }).then((r) => j(r)),

  generateSection: (nodeId: number) =>
    fetch(`/api/nodes/${nodeId}/generate`, { method: "POST" }).then((r) =>
      j<{ started: boolean; pending_chunks: number; section_title: string; message?: string }>(r)
    ),

  resume: (id: number) =>
    fetch(`/api/subjects/${id}/resume`, { method: "POST" }).then((r) => j(r)),

  stopGeneration: (id: number) =>
    fetch(`/api/subjects/${id}/stop`, { method: "POST" }).then((r) =>
      j<{ ok: boolean; stopped: boolean }>(r)
    ),

  regenerate: (nodeId: number) =>
    fetch(`/api/nodes/${nodeId}/regenerate`, { method: "POST" }).then((r) =>
      j<{
        ok: boolean;
        started: boolean;
        pending_chunks: number;
        section_title: string;
        message?: string;
      }>(r)
    ),

  reparseSubject: (subjectId: number) =>
    fetch(`/api/subjects/${subjectId}/reparse`, { method: "POST" }).then((r) =>
      j<{ ok: boolean; nodes_updated: number; warnings: string[] }>(r)
    ),

  listCards: (nodeId: number, track: string) =>
    fetch(`/api/nodes/${nodeId}/cards?track=${track}`).then((r) => j<Card[]>(r)),

  updateCard: (id: number, front: string, back: string, tag: string) =>
    fetch(`/api/cards/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ front, back, tag }),
    }).then((r) => j(r)),

  deleteCard: (id: number) =>
    fetch(`/api/cards/${id}`, { method: "DELETE" }).then((r) => j(r)),

  downloadUrl: (nodeId: number, track: "A" | "master") =>
    `/api/download?node_id=${nodeId}&track=${track}`,

  validateNode: (nodeId: number, track: "A" | "master") =>
    fetch(`/api/nodes/${nodeId}/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track }),
    }).then((r) => j<ValidationReport>(r)),

  reviewCard: (
    nodeId: number,
    cardId: number,
    track: "A" | "master",
    front: string,
    back: string,
    tag: string
  ) =>
    fetch(`/api/nodes/${nodeId}/validate/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: cardId, track, front, back, tag }),
    }).then((r) => j<{ ok: boolean }>(r)),

  completeValidation: (nodeId: number, track: "A" | "master") =>
    fetch(`/api/nodes/${nodeId}/validate/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track }),
    }).then((r) => j<{ ok: boolean; validated: boolean }>(r)),

  getSubsectionInfo: (nodeId: number) =>
    fetch(`/api/nodes/${nodeId}/info`).then((r) => j<SubsectionInfo>(r)),
};
