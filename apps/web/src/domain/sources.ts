export interface SourceInventory {
  schema_version: number;
  audited_at: string;
  source_root: string;
  status: string;
  pdfs: Array<{
    id: string;
    file_name: string;
    pages: number;
    text_pages: number;
  }>;
  audio: Array<{
    test_number: number;
    file_name: string;
    duration_seconds: number;
  }>;
  candidate_exams?: Array<{ test_number: number; published?: boolean }>;
  audit_scope?: { published_exams?: number };
  findings?: Array<{ code: string; level: string; message: string }>;
}

export type InventoryResult =
  | { state: 'loading' }
  | { state: 'ready'; inventory: SourceInventory }
  | { state: 'error'; message: string };

export async function loadInventory(): Promise<InventoryResult> {
  try {
    const response = await fetch('/api/sources');
    const payload = await response.json();
    if (!response.ok) {
      return { state: 'error', message: payload.detail ?? '来源清单暂不可用。' };
    }
    return { state: 'ready', inventory: payload as SourceInventory };
  } catch {
    return { state: 'error', message: '无法连接本地 API。请确认本地服务仍在运行。' };
  }
}

export function formatDuration(seconds: number): string {
  const wholeSeconds = Math.round(seconds);
  const hours = Math.floor(wholeSeconds / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const remainder = wholeSeconds % 60;
  const formatted = `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  return hours > 0 ? `${hours}:${formatted}` : formatted;
}
