// Opt-in native PostgreSQL tests; no shared database or provider credentials.
// Install outside the repo: @embedded-postgres/windows-x64@18.6.0-beta.19 and pg@8.16.3.
// Set AGENT_SQL_TEST_TOOLS to that directory and AGENT_TEST_PYTHON to the backend venv Python.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

if (!process.env.AGENT_SQL_TEST_TOOLS) throw new Error('Local PostgreSQL tool directory is required');
const require = createRequire(join(resolve(process.env.AGENT_SQL_TEST_TOOLS), 'package.json'));
const { initdb, pg_ctl } = require('@embedded-postgres/windows-x64');
const { Client } = require('pg');
const directory = mkdtempSync(join(tmpdir(), 'deeplingo-agent-correctness-'));
const data = join(directory, 'data'), port = 25441, clients = new Set();
let running = false, checks = 0;
const command = (file, args) => execFileSync(file, args, { windowsHide: true, stdio: 'ignore', timeout: 30000 });
const boot = () => {
  command(pg_ctl, ['-D', data, '-l', join(directory, 'postgres.log'), '-o', `-h 127.0.0.1 -p ${port}`, '-w', 'start']);
  running = true;
};
const stop = () => { command(pg_ctl, ['-D', data, '-m', 'fast', '-w', 'stop']); running = false; };
async function connect() {
  const client = new Client({ host: '127.0.0.1', port, database: 'postgres', user: 'postgres', connectionTimeoutMillis: 5000 });
  await client.connect(); clients.add(client); return client;
}
const close = async client => { await client.end(); clients.delete(client); };
const value = async (db, sql, args = []) => Object.values((await db.query(sql, args)).rows[0])[0];
const migration = name => readFileSync(new URL(`../../supabase/migrations/${name}`, import.meta.url), 'utf8');
const context = (db, session, user, concept) => value(db, 'select v3.speaking_review_context($1,$2,$3)', [session, user, concept]);
const commit = (db, session, user, concept, payload) => value(db, 'select v3.commit_speaking_review($1,$2,$3,$4)', [session, user, concept, payload]);
function transition(ctx, session, user, concept) {
  const python = `import json,sys
from uuid import UUID
from app.modules.review.application.speaking_review import SpeakingReviewService
from app.modules.review.infrastructure.fsrs_adapter import FSRSAdapter
data=json.load(sys.stdin)
class Store:
    def context(self,*args): return data['context']
    def commit(self,*args): self.payload=args[3]; return 'applied'
store=Store()
SpeakingReviewService(store=store,adapter=FSRSAdapter()).apply(*[UUID(data[k]) for k in ('session','user','concept')])
print(json.dumps(store.payload))`;
  return JSON.parse(execFileSync(process.env.AGENT_TEST_PYTHON || 'python', ['-c', python], {
    input: JSON.stringify({ context: ctx, session, user, concept }), encoding: 'utf8', windowsHide: true,
    env: { ...process.env, ENVIRONMENT: 'test', AI_PROVIDER: 'fake' }, timeout: 15000,
  }));
}

try {
  command(initdb, ['-D', data, '-U', 'postgres', '-A', 'trust', '--no-locale', '--encoding=UTF8']);
  boot(); let db = await connect();
  await db.query(`create schema v3; create schema auth; create schema extensions;
    create role anon; create role authenticated; create role service_role bypassrls;
    grant usage on schema v3, auth to anon, authenticated, service_role;
    create function auth.uid() returns uuid language sql as 'select null::uuid';
    create function extensions.gen_random_uuid() returns uuid language sql as 'select gen_random_uuid()';
    create type v3.review_mode as enum ('concept_to_meaning','meaning_to_concept','audio_to_text','text_to_meaning','production_prompt','shadowing_prompt');
    create type v3.fsrs_state as enum ('new','learning','review','relearning');
    create table v3.profiles(id uuid primary key); create table v3.learner_videos(id uuid primary key);
    create table v3.concepts(id uuid primary key, language_code text not null);
    create table v3.saved_concepts(user_id uuid, concept_id uuid, status text, primary key(user_id,concept_id));
    create table v3.learner_known_concepts(user_id uuid, concept_id uuid);
    create table v3.attempts(id uuid primary key);
    create table v3.target_events(user_id uuid, concept_id uuid, kind text, outcome text, event_key text,
      context_key text, judge jsonb, occurred_at timestamptz, unique(user_id,event_key));`);
  await db.query(migration('023_review_states.sql'));
  await db.query('alter table v3.review_states add column version integer not null default 0');
  await db.query(migration('024_review_events.sql'));
  await db.query(migration('20261026200927_l2_session_events.sql'));
  if (!process.argv.includes('--before')) await db.query(migration('20261107090825_agent_word_evidence_review.sql'));
  await db.query('grant all on all tables in schema v3 to service_role');
  const owner = randomUUID(), other = randomUUID();
  await db.query('insert into v3.profiles values ($1),($2)', [owner, other]);
  async function seed({ status = 'active', kind = 'spontaneous_use', known = false, language = 'en', savedOwner = owner } = {}) {
    const concept = randomUUID(), session = randomUUID();
    await db.query('insert into v3.concepts values ($1,$2)', [concept, language]);
    await db.query('insert into v3.saved_concepts values ($1,$2,$3)', [savedOwner, concept, status]);
    if (known) await db.query('insert into v3.learner_known_concepts values ($1,$2)', [owner, concept]);
    await db.query(`insert into v3.speaking_sessions(id,user_id,language_code,context_key,targets,status,occurred_at,expires_at)
      values ($1,$2,'en','home:synthetic',$3,'processing',now(),now()+interval '15 minutes')`,
      [session, owner, JSON.stringify([{ concept_id: concept, text: 'travel' }])]);
    const events = await value(db, 'select v3.complete_speaking_session($1,$2,$3)', [session,
      JSON.stringify([{ concept_id: concept, kind, occurred_at: new Date(Date.now() - 120000).toISOString() }]), 'fake']);
    return { concept, session, events };
  }
  const paused = await seed({ status: 'suspended' });
  assert.equal(paused.events.length, 1, 'paused words must retain their independent-use evidence');
  if (process.argv.includes('--before')) throw new Error('Expected the original migration to reject the paused word');
  assert.equal((await context(db, paused.session, owner, paused.concept)).eligible, false);
  assert.equal(await commit(db, paused.session, owner, paused.concept, null), 'skipped');
  assert.equal(await value(db, 'select count(*)::int from v3.review_states where concept_id=$1', [paused.concept]), 0);
  assert.equal(await value(db, 'select status from v3.saved_concepts where concept_id=$1', [paused.concept]), 'suspended');
  await db.query("update v3.saved_concepts set status='active' where concept_id=$1", [paused.concept]);
  assert.equal(await context(db, paused.session, owner, paused.concept), null);
  checks++;
  for (const options of [{ known: true }, { language: 'zh' }, { savedOwner: other }]) {
    assert.equal((await seed(options)).events.length, 0);
  }
  const assisted = await seed({ kind: 'framed_use' });
  assert.equal(assisted.events.length, 1);
  assert.equal(await context(db, assisted.session, owner, assisted.concept), null);
  assert.equal(await commit(db, assisted.session, owner, assisted.concept, null), 'skipped');
  checks++;
  const independent = await seed();
  assert.equal(await context(db, independent.session, other, independent.concept), null);
  const ctx = await context(db, independent.session, owner, independent.concept);
  const payload = transition(ctx, independent.session, owner, independent.concept);
  assert.equal(await commit(db, independent.session, other, independent.concept, payload), 'skipped');
  const wrong = structuredClone(payload); wrong.next.user_id = other;
  await assert.rejects(commit(db, independent.session, owner, independent.concept, wrong), /invalid_speaking_review_transition/);
  checks++;
  // Twelve independent native connections must commit one FSRS review for this session/word.
  const racers = await Promise.all(Array.from({ length: 12 }, connect));
  await Promise.all(racers.map(client => client.query('set role service_role')));
  const outcomes = await Promise.all(racers.map(client => commit(client, independent.session, owner, independent.concept, payload)));
  assert.equal(outcomes.filter(x => x === 'applied').length, 1);
  assert.equal(outcomes.filter(x => x === 'duplicate').length, 11);
  await Promise.all(racers.map(close));
  assert.equal(await value(db, 'select reps from v3.review_states where concept_id=$1', [independent.concept]), 1);
  assert.equal(await value(db, 'select count(*)::int from v3.review_events where review_state_id=$1', [payload.next.review_state_id]), 1);
  checks++;
  async function anotherSession(concept, secondsAgo) {
    const session = randomUUID();
    await db.query(`insert into v3.speaking_sessions(id,user_id,language_code,context_key,targets,status,occurred_at,expires_at)
      values ($1,$2,'en','home:synthetic',$3,'processing',now(),now()+interval '15 minutes')`,
      [session, owner, JSON.stringify([{ concept_id: concept, text: 'travel' }])]);
    await value(db, 'select v3.complete_speaking_session($1,$2,$3)', [session,
      JSON.stringify([{ concept_id: concept, kind: 'spontaneous_use', occurred_at: new Date(Date.now() - secondsAgo * 1000).toISOString() }]), 'fake']);
    return session;
  }
  const concurrent = await anotherSession(independent.concept, 60);
  const stale = transition(await context(db, concurrent, owner, independent.concept), concurrent, owner, independent.concept);
  await db.query(`update v3.review_states set version=version+1, reps=reps+1,
    last_reviewed_at=last_reviewed_at+interval '10 seconds' where concept_id=$1`, [independent.concept]);
  assert.equal(await commit(db, concurrent, owner, independent.concept, stale), 'conflict');
  const refreshed = transition(await context(db, concurrent, owner, independent.concept), concurrent, owner, independent.concept);
  assert.equal(await commit(db, concurrent, owner, independent.concept, refreshed), 'applied');
  assert.equal(await value(db, 'select reps from v3.review_states where concept_id=$1', [independent.concept]), 3);
  checks++;
  const late = await anotherSession(independent.concept, 180);
  const skipped = transition(await context(db, late, owner, independent.concept), late, owner, independent.concept);
  assert.equal(skipped, null);
  assert.equal(await commit(db, late, owner, independent.concept, skipped), 'skipped');
  assert.equal(await value(db, 'select reps from v3.review_states where concept_id=$1', [independent.concept]), 3);
  const pausedAfterRead = await seed();
  const pausedPayload = transition(await context(db, pausedAfterRead.session, owner, pausedAfterRead.concept), pausedAfterRead.session, owner, pausedAfterRead.concept);
  await db.query("update v3.saved_concepts set status='suspended' where concept_id=$1", [pausedAfterRead.concept]);
  assert.equal(await commit(db, pausedAfterRead.session, owner, pausedAfterRead.concept, pausedPayload), 'skipped');
  assert.equal(await value(db, 'select count(*)::int from v3.review_states where concept_id=$1', [pausedAfterRead.concept]), 0);
  checks++;
  // Force the last insert to fail: neither the schedule nor the consumed marker may survive.
  const atomic = await seed();
  const atomicPayload = transition(await context(db, atomic.session, owner, atomic.concept), atomic.session, owner, atomic.concept);
  await db.query(`create function v3.test_abort_review() returns trigger language plpgsql as $$begin raise exception 'synthetic_insert_failure'; end$$;
    create trigger test_abort_review before insert on v3.review_events for each row execute function v3.test_abort_review()`);
  await assert.rejects(commit(db, atomic.session, owner, atomic.concept, atomicPayload), /synthetic_insert_failure/);
  assert.equal(await value(db, 'select count(*)::int from v3.review_states where concept_id=$1', [atomic.concept]), 0);
  assert.notEqual(await context(db, atomic.session, owner, atomic.concept), null);
  await db.query('drop trigger test_abort_review on v3.review_events; drop function v3.test_abort_review()');
  assert.equal(await commit(db, atomic.session, owner, atomic.concept, atomicPayload), 'applied');
  checks++;
  for (const role of ['anon', 'authenticated']) {
    await db.query(`set role ${role}`);
    await assert.rejects(context(db, independent.session, owner, independent.concept), error => error.code === '42501');
    await assert.rejects(commit(db, independent.session, owner, independent.concept, payload), error => error.code === '42501');
    await db.query('reset role');
  }
  checks++;
  await close(db); stop(); boot(); db = await connect();
  assert.equal(await commit(db, independent.session, owner, independent.concept, payload), 'duplicate');
  assert.equal(await value(db, 'select reps from v3.review_states where concept_id=$1', [independent.concept]), 3);
  checks++;
  console.log(`PASS: ${checks} native PostgreSQL checks (paused evidence, eligibility, ownership, concurrent commits, rollback, permissions, restart)`);
} finally {
  await Promise.allSettled([...clients].map(close));
  if (running) stop();
}
