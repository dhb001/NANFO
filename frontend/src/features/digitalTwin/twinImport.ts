export interface ImportSummary {
  modelFileName: string;
  modelType: "glb" | "gltf";
  mappingFileName: string | null;
  totalRows: number;
  matched: number;
  unmatched: number;
  duplicateKeys: string[];
  mappingByDeviceId: Record<string, string>;
}

export interface ImportGraphNode {
  device_id: string;
  spatial_ref_id: string | null;
}

export function validateModelFile(file: File): { ok: boolean; message: string } {
  const name = file.name.trim().toLowerCase();
  const isGlb = name.endsWith(".glb");
  const isGltf = name.endsWith(".gltf");
  if (!isGlb && !isGltf) {
    return {
      ok: false,
      message: "Model file must be .glb or .gltf.",
    };
  }
  return {
    ok: true,
    message: "ok",
  };
}

function inferModelType(fileName: string): "glb" | "gltf" {
  return fileName.trim().toLowerCase().endsWith(".glb") ? "glb" : "gltf";
}

export function parseMappingRows(value: unknown): Array<{ object_name: string; device_id?: string; spatial_ref_id?: string }> {
  const rowsSource = Array.isArray(value)
    ? value
    : typeof value === "object" && value !== null && Array.isArray((value as { mappings?: unknown }).mappings)
      ? (value as { mappings: unknown[] }).mappings
      : [];

  return rowsSource
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item) => {
      return {
        object_name: String(item.object_name ?? "").trim(),
        device_id: typeof item.device_id === "string" ? item.device_id.trim() : undefined,
        spatial_ref_id: typeof item.spatial_ref_id === "string" ? item.spatial_ref_id.trim() : undefined,
      };
    })
    .filter((item) => item.object_name.length > 0);
}

async function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") {
    return file.text();
  }
  if (typeof file.arrayBuffer === "function") {
    const buffer = await file.arrayBuffer();
    return new TextDecoder().decode(buffer);
  }
  throw new Error("Mapping file cannot be read.");
}

export async function parseImportSummary(
  modelFile: File,
  mappingFile: File | null,
  graphNodes: ImportGraphNode[],
): Promise<ImportSummary> {
  const graphDeviceIds = new Set(graphNodes.map((node) => node.device_id));
  const deviceIdsBySpatialRef = graphNodes.reduce<Record<string, string[]>>((acc, node) => {
    if (!node.spatial_ref_id) {
      return acc;
    }
    const key = node.spatial_ref_id.trim();
    if (!key) {
      return acc;
    }
    const bucket = acc[key] ?? [];
    bucket.push(node.device_id);
    acc[key] = bucket;
    return acc;
  }, {});

  if (!mappingFile) {
    return {
      modelFileName: modelFile.name,
      modelType: inferModelType(modelFile.name),
      mappingFileName: null,
      totalRows: 0,
      matched: 0,
      unmatched: 0,
      duplicateKeys: [],
      mappingByDeviceId: {},
    };
  }

  const raw = await readFileText(mappingFile);
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch {
    throw new Error("Mapping file must contain valid JSON.");
  }

  const rows = parseMappingRows(parsed);
  const duplicateKeys: string[] = [];
  const mappingByDeviceId: Record<string, string> = {};
  const seenObjectNames = new Set<string>();
  let matched = 0;
  let unmatched = 0;

  for (const row of rows) {
    if (seenObjectNames.has(row.object_name)) {
      duplicateKeys.push(row.object_name);
      continue;
    }
    seenObjectNames.add(row.object_name);

    const targetSpatialRef = row.spatial_ref_id?.trim() ?? "";
    const targetDeviceId = row.device_id?.trim() ?? "";

    if (targetDeviceId) {
      if (graphDeviceIds.has(targetDeviceId)) {
        mappingByDeviceId[targetDeviceId] = targetSpatialRef || row.object_name;
        matched += 1;
      } else {
        unmatched += 1;
      }
      continue;
    }

    if (targetSpatialRef) {
      const candidateDeviceIds = deviceIdsBySpatialRef[targetSpatialRef] ?? [];
      if (candidateDeviceIds.length === 1) {
        mappingByDeviceId[candidateDeviceIds[0]] = targetSpatialRef;
        matched += 1;
      } else {
        unmatched += 1;
      }
      continue;
    }

    unmatched += 1;
  }

  return {
    modelFileName: modelFile.name,
    modelType: inferModelType(modelFile.name),
    mappingFileName: mappingFile.name,
    totalRows: rows.length,
    matched,
    unmatched,
    duplicateKeys,
    mappingByDeviceId,
  };
}
