export type SelectedMaterial = {
  doc_id: string;
  title: string;
  filename: string | null;
  scope: "global" | "thread" | "user";
};

export function parseSelectedMaterials(raw: string | null): SelectedMaterial[] {
  if (!raw) {
    return [];
  }

  try {
    const payload = JSON.parse(raw) as unknown;
    if (!Array.isArray(payload)) {
      return [];
    }
    return payload
      .map<SelectedMaterial | null>((item) => {
        if (!item || typeof item !== "object") {
          return null;
        }

        const material = item as Record<string, unknown>;
        const docId = String(material.doc_id ?? "").trim();
        const title = String(material.title ?? "").trim();
        if (!docId || !title) {
          return null;
        }

        const scope = material.scope;
        return {
          doc_id: docId,
          title,
          filename:
            typeof material.filename === "string" ? material.filename : null,
          scope:
            scope === "global" || scope === "thread" || scope === "user"
              ? scope
              : "global",
        };
      })
      .filter((item): item is SelectedMaterial => item !== null);
  } catch {
    return [];
  }
}
