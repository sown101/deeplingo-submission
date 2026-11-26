import { ApiError } from "../../../lib/api/errors";
import type { ActivityAnswer } from "./activityModels";

// Read only for migration from the pre-6B-1C-R localStorage transport.
export const PENDING_SUBMISSIONS_KEY = "deeplingo.pending-submissions.v1";
const DATABASE = "deeplingo.pending-submissions";
const OBJECT_STORE = "transport";
const RECORD_KEY = "v2";

export interface PendingSubmission {
  activityId: string;
  sessionId: string;
  submissionId: string;
  rawResponse: ActivityAnswer;
}
export interface PendingEnvelope { principalId: string; records: Record<string, PendingSubmission> }
export interface PendingStorage {
  get(): Promise<PendingEnvelope | null>;
  put(value: PendingEnvelope): Promise<void>;
  deleteIfPrincipal(principalId?: string): Promise<void>;
}

// Transaction completion, not a request's success callback, is the write
// acknowledgement. Strict durability fences the network POST on supported
// browsers; denied/unsupported storage fails closed before the POST.
class IndexedDbPendingStorage implements PendingStorage {
  private async open(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open(DATABASE, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(OBJECT_STORE);
      request.onsuccess = () => {
        request.result.onversionchange = () => request.result.close();
        resolve(request.result);
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Pending storage is blocked."));
    });
  }

  async get(): Promise<PendingEnvelope | null> {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      let value: PendingEnvelope | null = null;
      const tx = db.transaction(OBJECT_STORE, "readonly");
      const request = tx.objectStore(OBJECT_STORE).get(RECORD_KEY);
      request.onsuccess = () => { value = (request.result as PendingEnvelope | undefined) ?? null; };
      tx.oncomplete = () => { db.close(); resolve(value); };
      tx.onabort = tx.onerror = () => { db.close(); reject(tx.error ?? new Error("Pending read failed.")); };
    });
  }

  async put(value: PendingEnvelope): Promise<void> {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(OBJECT_STORE, "readwrite", { durability: "strict" });
      tx.objectStore(OBJECT_STORE).put(value, RECORD_KEY);
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onabort = tx.onerror = () => { db.close(); reject(tx.error ?? new Error("Pending write failed.")); };
    });
  }

  async deleteIfPrincipal(principalId?: string): Promise<void> {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(OBJECT_STORE, "readwrite", { durability: "strict" });
      const store = tx.objectStore(OBJECT_STORE);
      const request = store.get(RECORD_KEY);
      request.onsuccess = () => {
        const value = request.result as PendingEnvelope | undefined;
        if (value && (!principalId || value.principalId === principalId)) store.delete(RECORD_KEY);
      };
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onabort = tx.onerror = () => { db.close(); reject(tx.error ?? new Error("Pending cleanup failed.")); };
    });
  }
}

export async function clearPendingSubmissions(principalId?: string): Promise<void> {
  // The old store is not authoritative after migration, but must never expose
  // a previous principal's answer to another account.
  window.localStorage.removeItem(PENDING_SUBMISSIONS_KEY);
  await new IndexedDbPendingStorage().deleteIfPrincipal(principalId);
}

function safeAnswer(value: unknown): value is ActivityAnswer {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  return Object.keys(v).length === 1 &&
    (typeof v.text === "string" || (Number.isInteger(v.selected_option) && typeof v.selected_option === "number"));
}
function sameAnswer(a: ActivityAnswer, b: ActivityAnswer): boolean {
  return "text" in a && "text" in b ? a.text === b.text :
    "selected_option" in a && "selected_option" in b && a.selected_option === b.selected_option;
}
function validate(raw: unknown): PendingEnvelope {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new ApiError("validation", null, { message: "Invalid pending transport state." });
  const value = raw as PendingEnvelope;
  if (typeof value.principalId !== "string" || !value.records ||
    typeof value.records !== "object" || Array.isArray(value.records))
    throw new ApiError("validation", null, { message: "Invalid pending transport state." });
  for (const item of Object.values(value.records)) {
    if (!item || typeof item.activityId !== "string" || typeof item.sessionId !== "string" ||
      typeof item.submissionId !== "string" || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(item.submissionId) ||
      !safeAnswer(item.rawResponse) ||
      Object.keys(item).some(k => !["activityId", "sessionId", "submissionId", "rawResponse", "attemptId"].includes(k)))
      throw new ApiError("validation", null, { message: "Invalid pending transport state." });
  }
  return value;
}

export class PendingSubmissionStore {
  constructor(private readonly storage: PendingStorage = new IndexedDbPendingStorage()) {}

  private async load(principalId: string): Promise<PendingEnvelope> {
    let raw = await this.storage.get();
    if (raw) {
      const persisted = validate(raw);
      if (persisted.principalId !== principalId) {
        await this.storage.deleteIfPrincipal(persisted.principalId);
        raw = null;
      }
    }
    if (!raw) {
      const legacy = window.localStorage.getItem(PENDING_SUBMISSIONS_KEY);
      if (legacy) {
        try { raw = validate(JSON.parse(legacy)); }
        catch { throw new ApiError("validation", null, { message: "Pending submission cannot be read safely." }); }
        if (raw.principalId === principalId) await this.storage.put(raw);
        window.localStorage.removeItem(PENDING_SUBMISSIONS_KEY);
      }
    }
    if (!raw) return { principalId, records: {} };
    const value = validate(raw);
    // Before B4.2 a stored receipt (`attemptId`) meant "saved, not yet assessed". Such an Attempt was never
    // graded and cannot be graded now, so the record is dropped instead of resent.
    const legacy = Object.entries(value.records).filter(([, item]) => "attemptId" in item);
    if (legacy.length) {
      for (const [context] of legacy) delete value.records[context];
      if (Object.keys(value.records).length) await this.storage.put(value);
      else await this.storage.deleteIfPrincipal(principalId);
    }
    return value;
  }

  async read(principalId: string, context: string): Promise<PendingSubmission | null> {
    return (await this.load(principalId)).records[context] ?? null;
  }

  async prepare(principalId: string, context: string, activityId: string, sessionId: string, answer: ActivityAnswer): Promise<PendingSubmission> {
    const value = await this.load(principalId);
    const old = value.records[context];
    if (old) {
      if (old.activityId !== activityId || !sameAnswer(old.rawResponse, answer))
        throw new ApiError("conflict", 409, { message: "A different answer cannot replace a pending submission." });
      return old;
    }
    if (!safeAnswer(answer)) throw new ApiError("validation", 422, { message: "Invalid raw response." });
    const item = { activityId, sessionId, submissionId: crypto.randomUUID(), rawResponse: { ...answer } };
    value.records[context] = item;
    await this.storage.put(value); // Must complete BEFORE submitAnswer issues POST.
    return item;
  }

  // The answer is finished: graded and received, or refused for good (the question is closed or answered).
  async discard(principalId: string, context: string, submissionId: string): Promise<void> {
    const value = await this.load(principalId);
    if (value.records[context]?.submissionId !== submissionId) return;
    delete value.records[context];
    if (Object.keys(value.records).length) await this.storage.put(value);
    else await this.storage.deleteIfPrincipal(principalId);
  }

}
