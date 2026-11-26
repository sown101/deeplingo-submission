import { beforeEach, describe, expect, it } from "vitest";
import { PendingSubmissionStore, PENDING_SUBMISSIONS_KEY, type PendingEnvelope, type PendingStorage } from "./pendingSubmissionStore";
import { ids } from "../../../contracts/backendV1Fixtures";

class MemoryPendingStorage implements PendingStorage {
 value: PendingEnvelope | null = null;
 async get() { return this.value ? structuredClone(this.value) : null; }
 async put(value: PendingEnvelope) { this.value = structuredClone(value); }
 async deleteIfPrincipal(principalId?: string) {
  if (!principalId || this.value?.principalId === principalId) this.value = null;
 }
}
let persistence: MemoryPendingStorage;
describe("6B-1C durable submission transport (one-step answer, B4.2)",()=>{
 beforeEach(()=>{localStorage.clear();persistence=new MemoryPendingStorage();});
 it("a pending record that still holds a pre-B4.2 receipt is dropped, not resent",async()=>{
  const old={principalId:"A",records:{"practice:item":{activityId:"a",sessionId:"s",submissionId:crypto.randomUUID(),rawResponse:{text:"old"},attemptId:ids.attempt}}};
  persistence.value=structuredClone(old) as unknown as PendingEnvelope;
  expect(await new PendingSubmissionStore(persistence).read("A","practice:item")).toBeNull();
  expect(persistence.value).toBeNull();
 });
 it("A -> logout -> B cannot resume A; same principal restart preserves state",async()=>{
  const store=new PendingSubmissionStore(persistence),first=await store.prepare("A","review","activity","session",{selected_option:2});
  expect((await new PendingSubmissionStore(persistence).read("A","review"))?.submissionId).toBe(first.submissionId);
  await persistence.deleteIfPrincipal("A");expect(await store.read("B","review")).toBeNull();
  await store.prepare("A","review","activity","session",{text:"A private"});expect(await store.read("B","review")).toBeNull();
 });
 it("authority fields never enter transport storage; malformed persisted state fails closed",async()=>{
  const store=new PendingSubmissionStore(persistence);
  await expect(store.prepare("A","review","a","s",{text:"x",score:1} as never)).rejects.toThrow();
  localStorage.setItem(PENDING_SUBMISSIONS_KEY,JSON.stringify({principalId:"A",records:{review:{activityId:"a",sessionId:"s",submissionId:crypto.randomUUID(),rawResponse:{text:"x"},mastery:1}}}));
  await expect(store.read("A","review")).rejects.toThrow();
 });
 it("practice/review contexts share protocol but retain independent pending keys",async()=>{
  const store=new PendingSubmissionStore(persistence);
  const p=await store.prepare("A","practice:item","p","s",{text:"practice"});
  const r=await store.prepare("A","review","r","s2",{selected_option:0});
  expect(p.submissionId).not.toBe(r.submissionId);
  await store.discard("A","review",r.submissionId);
  expect(await store.read("A","review")).toBeNull();expect((await store.read("A","practice:item"))?.submissionId).toBe(p.submissionId);
 });
 it("migrates same-principal legacy pending only after durable write",async()=>{
  const old={principalId:"A",records:{review:{activityId:"a",sessionId:"s",submissionId:crypto.randomUUID(),rawResponse:{text:"old"}}}};
  localStorage.setItem(PENDING_SUBMISSIONS_KEY,JSON.stringify(old));
  expect((await new PendingSubmissionStore(persistence).read("A","review"))?.submissionId).toBe(old.records.review.submissionId);
  expect(persistence.value).toEqual(old);
  expect(localStorage.getItem(PENDING_SUBMISSIONS_KEY)).toBeNull();
 });
 it("quarantines stale A IndexedDB before migrating B's legacy record",async()=>{
  const store=new PendingSubmissionStore(persistence);
  await store.prepare("A","review","a","s",{text:"A private"});
  const old={principalId:"B",records:{review:{activityId:"b",sessionId:"s2",submissionId:crypto.randomUUID(),rawResponse:{text:"B answer"}}}};
  localStorage.setItem(PENDING_SUBMISSIONS_KEY,JSON.stringify(old));
  expect((await new PendingSubmissionStore(persistence).read("B","review"))?.submissionId).toBe(old.records.review.submissionId);
  expect(persistence.value).toEqual(old);
  expect(localStorage.getItem(PENDING_SUBMISSIONS_KEY)).toBeNull();
 });
});
