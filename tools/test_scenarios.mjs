// Edge-case scenarios for the generated shortcuts, run on the simulated iPhone in sim.mjs. Each scenario plays real
// events (your agent's messages through the Message automation, your typed messages from the iPhone or another
// device, voice notes through Talk to Hermes, tapbacks, delays, time-zone changes, failures) and checks the chat
// that's saved and the Lock Screen that's drawn.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { Device, Img, flatten, asText } from './sim.mjs';

const [, , workflowsPath, tokensPath, manifestPath] = process.argv;
const workflows = JSON.parse(readFileSync(workflowsPath, 'utf8'));
const T = JSON.parse(readFileSync(tokensPath, 'utf8'));
const M = JSON.parse(readFileSync(manifestPath, 'utf8'));
const RS = '␞', FS = '␟';
const FIELDS = ['role', 'id', 'key', 'ms', 'kind', 'src', 'fp', 'react', 'by', 'rowH', 'bx', 'bw', 'bh', 'day', 'time', 'timeW', 'text'];
const W = T.canvas.width, AGENT = 'Hermes';

function phone(opts = {}) {
  const d = new Device(opts);
  for (const [name, wf] of Object.entries(workflows)) d.install(name, wf);
  const asset = (name, w, h) => d.files.set(`Hermes/${name}`, new Img(w, h, { name }));
  asset('wall.png', W, T.canvas.height); asset('veil.png', W, 1000); asset('blue.png', W, 1000);
  asset('tail-left.png', M.tailBox.w, M.tailBox.h); asset('tail-right.png', M.tailBox.w, M.tailBox.h);
  asset('typing-turn.png', W, M.typing.turnHeight); asset('typing-same.png', W, M.typing.sameHeight);
  asset('fade-mask.png', W, T.canvas.height + 1000); asset('avatar.png', T.empty.avatar, T.empty.avatar);
  asset('audio-me.png', T.audio.width, 110); asset('audio-them.png', T.audio.width, 110);
  asset('tapback-me.png', M.tapback.w, M.tapback.h); asset('tapback-them.png', M.tapback.w, M.tapback.h);
  asset('tapback-hole.png', 2 * W, 1700);
  asset('clear.png', W, 1500); asset('gap-same.png', W, T.bubble.sameGap - T.bubble.tailRoom); asset('gap-turn.png', W, T.bubble.turnGap - T.bubble.tailRoom);
  asset('receipt-canvas.png', W, T.receipt.gap + T.receipt.height); asset('stamp-canvas.png', W, T.stamp.above + T.type.time.pitch + T.stamp.below);
  // The renderer's agent name is the import answer: set it like the import question does.
  const r = workflows['Hermes Chat Renderer'];
  const q = r.WFWorkflowImportQuestions[0];
  const wf = JSON.parse(JSON.stringify(r));
  wf.WFWorkflowActions[q.ActionIndex].WFWorkflowActionParameters.WFTextActionText = { Value: { string: opts.agentName ?? AGENT }, WFSerializationType: 'WFTextTokenString' };
  d.install('Hermes Chat Renderer', wf);
  // Sending a voice note puts it in Messages (from you, as an audio attachment).
  d.onSend = content => d.message({ from: d.me, attach: content.name + '', indexedAfter: d.indexLag });
  return d;
}

// What happens on the phone.
const automation = (d, m) => d.run('Hermes Lock Screen', d.trigger(m));
function agentSays(d, body, { run = true, lag, attach = '' } = {}) {
  const m = d.message({ from: AGENT, body, attach, indexedAfter: lag ?? d.indexLag });
  if (run) automation(d, m);
  d.advance(1500);
  return m;
}
const VERBS = { Like: 'Liked', Love: 'Loved', Dislike: 'Disliked', Laugh: 'Laughed at', Emphasize: 'Emphasized', Question: 'Questioned' };
function quoteOf(m) { return m.body ? `“${m.body}”` : (m.attach.startsWith('Audio') ? 'an audio message' : 'an attachment'); }
function agentReacts(d, target, reaction = 'Like', { run = true, lag } = {}) {
  const body = reaction.startsWith('emoji:') ? `Reacted ${reaction.slice(6)} to ${quoteOf(target)}` : `${VERBS[reaction]} ${quoteOf(target)}`;
  const m = d.message({ from: AGENT, body, type: 'Reaction', reaction: reaction.startsWith('emoji:') ? reaction.slice(6) : reaction, ref: target, indexedAfter: lag ?? d.indexLag });
  if (run) automation(d, m);
  d.advance(800);
  return m;
}
function iType(d, body, { lag } = {}) { const m = d.message({ from: d.me, body, indexedAfter: lag ?? d.indexLag }); d.advance(1200); return m; }
function iReact(d, target, reaction = 'Love') {
  const m = d.message({ from: d.me, body: `${VERBS[reaction]} ${quoteOf(target)}`, type: 'Reaction', reaction, ref: target });
  d.advance(600); return m;
}
function voiceNote(d, words, { fails = false } = {}) {
  d.transcribeFails = fails;
  const before = d.messages.length;
  const recName = () => d.messages[d.messages.length - 1];
  d.transcriptsNext = words;
  const origSend = d.onSend;
  d.onSend = content => { d.transcripts.set(content.name.replace(/\.[^.]+$/, ''), words); origSend(content); };
  try { d.run('Talk to Hermes'); } catch (e) { if (!fails) throw e; }
  d.onSend = origSend;
  d.advance(1000);
  return d.messages.length > before ? recName() : null;
}

// What is saved and what shows.
function chat(d) {
  const f = d.files.get('Hermes/chat.json');
  if (!f) return [];
  const log = JSON.parse(f.data).log;
  return log ? log.split(RS).map(r => Object.fromEntries(r.split(FS).map((v, i) => [FIELDS[i], v]))) : [];
}
const said = d => chat(d).map(r => `${r.role}: ${r.kind === 'a' ? '🎤' + (r.text ? ' ' + r.text : '') : r.text}${r.react ? ' [' + r.react + ']' : ''}`);
const status = d => JSON.parse(d.files.get('Hermes/chat.json').data).status;
function screen(d) {
  const last = d.wallpapers[d.wallpapers.length - 1];
  assert(last, 'no wallpaper was set');
  return flatten(last.img).filter(x => x.text !== undefined).sort((a, b) => a.y - b.y || a.x - b.x);
}
const screenText = d => screen(d).map(x => x.text);
function checkInvariants(d, name) {
  const recs = chat(d);
  const keys = recs.map(r => r.key);
  assert.equal(new Set(keys).size, keys.length, `${name}: duplicate keys ${keys}`);
  const ids = recs.map(r => r.id);
  assert.equal(new Set(ids).size, ids.length, `${name}: two records share a row file`);
  for (let i = 1; i < recs.length; i++) assert(Number(recs[i].ms) >= Number(recs[i - 1].ms), `${name}: out of order at ${i}`);
  for (const r of recs) {
    assert(d.files.has(`Hermes/rows/${r.id}.png`), `${name}: missing row ${r.id}`);
    assert(Number(r.rowH) > 0, `${name}: record never drawn: ${r.text}`);
  }
  assert(recs.length <= T.log.keep, `${name}: more than ${T.log.keep} records`);
}

const scenarios = [];
const scenario = (name, fn, opts = {}) => scenarios.push({ name, fn, opts });

scenario('empty chat draws the empty state', d => {
  d.run('Hermes Lock Screen');
  assert.deepEqual(screenText(d).filter(t => t.length > 2), [AGENT, 'Hold the Action button to talk.']);
});

scenario('a reply, the number "4." and an emoji-only reply all show', d => {
  const q = iType(d, 'What is 2+2?');
  agentReacts(d, q);
  agentSays(d, '4.');
  agentSays(d, '❤️');
  assert.deepEqual(said(d), ['me: What is 2+2? [👍]', 'h: 4.', 'h: ❤️']);
  const big = screen(d).find(x => x.text === '❤️');
  assert.equal(big.size, T.jumbo.size, 'an emoji alone is drawn large');
});

scenario('typed on this iPhone: captured from the tapback, then confirmed from Messages without a duplicate', d => {
  const q = iType(d, 'Respond now pls');
  agentReacts(d, q);
  assert.deepEqual(said(d), ['me: Respond now pls [👍]']);
  assert(chat(d)[0].key.startsWith('m'), 'confirmed by the sync in the same update');
  assert.equal(status(d), 'thinking');
  agentSays(d, 'Hey Sam—I’m here 👋');
  assert.deepEqual(said(d), ['me: Respond now pls [👍]', 'h: Hey Sam—I’m here 👋']);
  assert.equal(status(d), '');
});

scenario('typed on the laptop: shows when the agent answers, in order', d => {
  const a = iType(d, 'sent from my laptop');
  const b = iType(d, 'and another one');
  agentSays(d, 'Got both.');
  assert.deepEqual(said(d), ['me: sent from my laptop', 'me: and another one', 'h: Got both.']);
});

scenario('Messages slow to index: the notification is shown at once and confirmed later, never twice', d => {
  d.indexLag = 60000;
  const q = iType(d, 'check my flight');
  agentReacts(d, q);
  agentSays(d, 'On time, gate C4.');
  assert.deepEqual(said(d), ['me: check my flight [👍]', 'h: On time, gate C4.']);
  assert(chat(d).every(r => r.key.startsWith('p')), 'nothing confirmed yet');
  d.advance(70000);
  d.indexLag = 0;
  agentSays(d, 'Anything else?');
  assert.deepEqual(said(d), ['me: check my flight [👍]', 'h: On time, gate C4.', 'h: Anything else?']);
  assert(chat(d).every(r => r.key.startsWith('m')), 'all confirmed');
});

scenario('an update that overwrote another (two quick messages) is repaired by the next', d => {
  const q = iType(d, 'question');
  agentReacts(d, q);
  agentSays(d, 'first answer');
  // Simulate the race: the next update saves a chat that lost "first answer".
  const f = d.files.get('Hermes/chat.json'), state = JSON.parse(f.data);
  state.log = state.log.split(RS).filter(r => !r.includes('first answer')).join(RS);
  f.data = JSON.stringify(state);
  d.advance(31000);                  // the next read of Messages is due
  agentSays(d, 'second answer');
  assert.deepEqual(said(d), ['me: question [👍]', 'h: first answer', 'h: second answer']);
}, { senderNames: true });   // needs to know who sent each message (iOS 26 doesn't say)

scenario('offline: a burst arrives late and only some automations run; order comes from Messages', d => {
  d.indexLag = 0;
  iType(d, 'one'); iType(d, 'two');
  const a = agentSays(d, 'reply one', { run: false });
  const b = agentSays(d, 'reply two', { run: false });
  const c = agentSays(d, 'reply three', { run: false });
  automation(d, c);                 // back online: only the newest automation runs
  assert.deepEqual(said(d), ['me: one', 'me: two', 'h: reply one', 'h: reply two', 'h: reply three']);
}, { senderNames: true });   // needs to know who sent each message (iOS 26 doesn't say)

scenario('automations run out of order: still in order', d => {
  const a = agentSays(d, 'alpha', { run: false, lag: 999999 });
  const b = agentSays(d, 'beta', { run: false, lag: 999999 });
  automation(d, b);
  automation(d, a);
  assert.deepEqual(said(d), ['h: beta', 'h: alpha'], 'notifications alone: in arrival order of the automations');
  for (const m of d.messages) m.indexedAt = d.clock;
  d.advance(31000);
  automation(d, agentSays(d, 'gamma', { run: false }));
  assert.deepEqual(said(d), ['h: alpha', 'h: beta', 'h: gamma'], 'Messages puts them back in order');
});

scenario('the same message triggering twice adds it once', d => {
  const m = agentSays(d, 'hello there');
  automation(d, m);
  assert.deepEqual(said(d), ['h: hello there']);
});

scenario('repeated identical messages are all kept', d => {
  const a = iType(d, '4'); agentReacts(d, a); agentSays(d, '4.');
  d.advance(60000);
  const b = iType(d, '4'); agentReacts(d, b); agentSays(d, '4.');
  assert.deepEqual(said(d), ['me: 4 [👍]', 'h: 4.', 'me: 4 [👍]', 'h: 4.']);
});

scenario('a late tapback after the reply does not bring the typing bubble back', d => {
  const q = iType(d, 'Hello? Say something');
  agentSays(d, 'I’m here.');
  agentReacts(d, q);
  assert.equal(status(d), '');
  assert.deepEqual(said(d), ['me: Hello? Say something [👍]', 'h: I’m here.']);
});

scenario('status lines keep the typing bubble without adding bubbles', d => {
  const q = iType(d, 'summarize the thread');
  agentReacts(d, q);
  agentSays(d, '⏳ Working — 1 min');
  agentSays(d, '💻 `ls`...');
  assert.deepEqual(said(d), ['me: summarize the thread [👍]']);
  assert.notEqual(status(d), '');
  agentSays(d, 'Here is the summary.');
  assert.equal(status(d), '');
});

scenario('voice note: sent first, waveform shows, transcript joins it', d => {
  const v = voiceNote(d, 'Can you hear me?');
  assert.deepEqual(said(d), ['me: 🎤 Can you hear me?']);
  agentReacts(d, v);
  agentSays(d, 'Loud and clear.');
  assert.deepEqual(said(d), ['me: 🎤 Can you hear me? [👍]', 'h: Loud and clear.']);
  assert(chat(d)[0].key.startsWith('m'), 'your agent’s reaction says when the voice note was sent: it is confirmed by that');
});

scenario('voice note: the agent acknowledges before the transcript is ready', d => {
  // Messages has the voice note and the agent's tapback before Talk to Hermes finishes transcribing.
  const m = d.message({ from: d.me, attach: 'Audio Recording 2026-10-28 at 11.53.57 AM.m4a' });
  d.advance(1000);
  agentReacts(d, m);
  assert.deepEqual(said(d), ['me: 🎤 [👍]']);
  d.run('Hermes Lock Screen', 'me-audio[Audio Recording 2026-10-28 at 11.53.57 AM]: Testing, testing');
  assert.deepEqual(said(d), ['me: 🎤 Testing, testing [👍]']);
});

scenario('voice note: transcription fails, the voice note still shows once', d => {
  const v = voiceNote(d, '', { fails: true });
  agentReacts(d, v);
  agentSays(d, 'Got your voice note.');
  assert.deepEqual(said(d), ['me: 🎤 [👍]', 'h: Got your voice note.']);
});

scenario('voice note sent from Messages or another device (no transcript) shows as a waveform once your agent reacts', d => {
  const m = d.message({ from: d.me, attach: 'Audio Message.caf' });
  d.advance(500);
  agentSays(d, 'Heard you.');
  assert.deepEqual(said(d), ['h: Heard you.'], 'its attachment can’t be read, so reading Messages leaves it out');
  agentReacts(d, m);
  assert.deepEqual(said(d), ['me: 🎤 [👍]', 'h: Heard you.']);
});

scenario('your own reactions (from any device) badge the agent’s bubbles; removal clears them', d => {
  const r = agentSays(d, 'Turn on Professional mode.');
  iReact(d, r, 'Love');
  d.advance(31000);
  agentSays(d, 'Anything else?');
  assert.deepEqual(said(d), ['h: Turn on Professional mode. [❤️]', 'h: Anything else?']);
  d.message({ from: d.me, body: `Removed a heart from “Turn on Professional mode.”`, type: 'Reaction', reaction: '', ref: r });
  d.advance(31000);
  agentSays(d, 'ok');
  assert.deepEqual(said(d), ['h: Turn on Professional mode.', 'h: Anything else?', 'h: ok']);
});

scenario('custom emoji tapbacks show their emoji', d => {
  const q = iType(d, 'ship it');
  agentReacts(d, q, 'emoji:🔥');
  assert.deepEqual(said(d), ['me: ship it [🔥]']);
  assert(screen(d).some(x => x.text === '🔥' && x.size === T.tapback.emoji));
});

scenario('a photo from the agent shows as an attachment (iOS 26 can’t say more without stopping)', d => {
  agentSays(d, '', { attach: 'IMG_3528.png' });
  assert.deepEqual(said(d), ['h: 📎 Attachment']);
});

scenario('travel: a time-zone change neither duplicates nor reorders', d => {
  d.tz = -240;
  const q = iType(d, 'leaving New York'); agentReacts(d, q); agentSays(d, 'Safe travels!');
  d.advance(5 * 3600 * 1000);
  d.tz = -420;                       // landed in Seattle
  const q2 = iType(d, 'landed'); agentReacts(d, q2); agentSays(d, 'Welcome to Seattle.');
  assert.deepEqual(said(d), ['me: leaving New York [👍]', 'h: Safe travels!', 'me: landed [👍]', 'h: Welcome to Seattle.']);
});

scenario('/new from you clears the chat, and reading Messages doesn’t bring the old one back', d => {
  const q = iType(d, 'old question'); agentReacts(d, q); agentSays(d, 'old answer');
  const n = iType(d, '/new'); agentReacts(d, n); agentSays(d, 'Fresh start.');
  assert.deepEqual(said(d), ['h: Fresh start.']);
  agentSays(d, 'Still fresh.');
  assert.deepEqual(said(d), ['h: Fresh start.', 'h: Still fresh.']);
});

scenario('reading Messages stops partway (e.g. locked): messages still show, and updates stop failing', d => {
  d.findFails = true;
  assert.throws(() => agentSays(d, 'first'));
  assert.deepEqual(said(d), ['h: first']);
  assert.equal(statusOf(d).stage, 'running: reading Messages', 'it shows where it stopped');
  const before = d.clock;
  agentSays(d, 'second');                                    // that read began moments ago: it may still be going
  const shown = d.wallpapers.at(-1).at - before;
  assert(shown < (T.sync.lockSeconds + 4) * 1000, `waited only for the lock to expire (${shown} ms)`);
  assert(statusOf(d).stage.endsWith('busy'), statusOf(d).stage);
  d.advance(T.sync.deadSeconds * 1000);
  agentSays(d, 'third');                                     // long enough ago: it stopped, so reading pauses
  assert(statusOf(d).stage.endsWith('paused'), statusOf(d).stage);
  const q = iType(d, 'still there?'); agentReacts(d, q);     // a tapback would read Messages, but not while paused
  assert.deepEqual(said(d), ['h: first', 'h: second', 'h: third', 'me: still there? [👍]']);
  assert.throws(() => d.run('Hermes Lock Screen'), 'run by hand, it still tries, and shows the error');
  d.findFails = false;
  d.advance(T.sync.deadSeconds * 1000 + 1000);
  d.run('Hermes Lock Screen');                               // by hand once it works: reading resumes
  assert.equal(statusOf(d).paused_until, '');
  assert(chat(d).every(r => r.key.startsWith('m')), 'everything confirmed from Messages');
  d.advance(31000);
  agentSays(d, 'fourth');
  assert(!/paused|busy/.test(statusOf(d).stage), statusOf(d).stage);
  assert(chat(d).at(-1).key.startsWith('m'), 'confirmed from Messages: reading is back for automations too');
});

scenario('a pause ends by itself', d => {
  d.findFails = true;
  assert.throws(() => agentSays(d, 'first'));
  d.advance(T.sync.deadSeconds * 1000);
  agentSays(d, 'second');
  assert(statusOf(d).stage.endsWith('paused'));
  d.findFails = false;
  d.advance(T.sync.pauseHours * 3600 * 1000);
  agentSays(d, 'third');
  assert(!/paused|busy/.test(statusOf(d).stage), statusOf(d).stage);
  assert.deepEqual(said(d), ['h: first', 'h: second', 'h: third']);
  assert(chat(d).every(r => r.key.startsWith('m')), 'read from Messages again');
});

scenario('run by hand, the first pass reads Messages too, and each step is noted before it runs', d => {
  const stages = [];
  const set = d.files.set.bind(d.files);
  d.files.set = (k, v) => { if (k === 'Hermes/update-status.json') stages.push(JSON.parse(v.data).stage); return set(k, v); };
  d.message({ from: AGENT, body: 'already here', at: d.clock - 60000 });
  d.run('Hermes Lock Screen');
  assert.deepEqual(stages, ['running', 'running: setting the wallpaper', 'running: reading Messages',
    'applied, nothing new']);
  assert.equal(d.wallpapers.length, 1, 'one redraw, with what Messages had');
  assert.deepEqual(said(d), ['h: already here']);
  stages.length = 0;
  d.advance(60000);
  agentSays(d, 'from a notification');
  assert.deepEqual(stages.slice(0, 2), ['running', 'running: reading Messages'], 'automations note less, to stay quick');
  assert(stages.at(-1).startsWith('applied'), stages.at(-1));
}, { senderNames: true });   // needs to know who sent each message (iOS 26 doesn't say)

scenario('the renderer run by itself reads Messages too: iOS can ask for access only then', d => {
  agentSays(d, 'hi');
  iType(d, 'typed on the laptop');
  const img = d.run('Hermes Chat Renderer');
  assert(img instanceof Img, 'it outputs the screen');
  assert.deepEqual(said(d), ['h: hi', 'me: typed on the laptop']);
  assert.match(JSON.parse(d.files.get('Hermes/chat.json').data).perf, /total \d+ · sync$/);
});

scenario('a Time of Day automation only changes the wall; it doesn’t read Messages', d => {
  agentSays(d, 'hi');
  d.findFails = true;                                        // reading Messages would fail (locked)
  atLocal(d, T.hours.day, 0);
  const n = d.wallpapers.length;
  d.run('Hermes Lock Screen');
  assert.equal(d.wallpapers.length, n + 1, 'redrawn once');
  assert(statusOf(d).stage.endsWith('wall'), statusOf(d).stage);
  d.advance(60000);
  d.run('Hermes Lock Screen', new Date(d.clock));            // a time trigger that passes its date
  assert.deepEqual(said(d), ['h: hi'], 'a date adds nothing');
  d.advance(5 * 60000);
  assert.throws(() => d.run('Hermes Lock Screen'), 'run by hand at another time, it reads Messages');
});

scenario('a new install fills the screen from Messages, and later reads don’t reach further back', d => {
  for (let i = 0; i < 20; i++) d.message({ from: AGENT, body: `earlier ${i}`, at: d.clock - (20 - i) * 600000 });
  d.run('Hermes Lock Screen');
  const first = said(d);
  assert.equal(first.length, T.sync.backfillKeep);
  assert.equal(first.at(-1), 'h: earlier 19');
  d.advance(31000);
  agentSays(d, 'new');
  assert.deepEqual(said(d), [...first, 'h: new']);
}, { senderNames: true });   // needs to know who sent each message (iOS 26 doesn't say)

scenario('a message without a date, or a tapback whose message is gone, is skipped without stopping the read', d => {
  d.message({ from: AGENT, body: 'no date', noDate: true });
  d.message({ from: AGENT, body: 'Liked “something old”', type: 'Reaction', reaction: 'Like', ref: null });
  d.advance(1000);
  agentSays(d, 'dated');
  d.advance(31000);
  d.run('Hermes Lock Screen');
  assert.deepEqual(said(d), ['h: dated']);
});

scenario('an update that is still running makes the next one wait, then go', d => {
  agentSays(d, 'one');
  const f = { kind: 'file', data: JSON.stringify({ stage: 'running', at: secondsOfYear(d) }) };
  d.files.set('Hermes/update-status.json', f);
  const before = d.clock;
  agentSays(d, 'two');
  assert(d.clock - before >= 2000, 'it waited');
  assert.deepEqual(said(d), ['h: one', 'h: two']);
});

scenario('the agent’s name typed differently from the contact (case, punctuation) still finds the conversation', d => {
  const p = phone({ agentName: 'HERMES.' });
  const q = iType(p, 'hi'); agentReacts(p, q); agentSays(p, 'hello');
  assert.deepEqual(said(p), ['me: hi [👍]', 'h: hello']);
  assert(chat(p)[0].key.startsWith('m'), 'your message was found in Messages');
  p.advance(31000); p.run('Hermes Lock Screen');
  assert(chat(p).every(r => r.key.startsWith('m')));
});

scenario('a different contact name: Messages isn’t matched, notifications still work', d => {
  const p = phone({ agentName: 'Hermes' });
  const q = iType(p, 'hi'); agentReacts(p, q); agentSays(p, 'hello');
  assert.deepEqual(said(p), ['me: hi [👍]', 'h: hello']);
});

scenario('other conversations never enter the chat', d => {
  d.message({ from: 'Mom', body: 'call me', conversation: 'Mom' });
  d.message({ from: d.me, body: 'ok mom', conversation: 'Mom' });
  agentSays(d, 'hi');
  assert.deepEqual(said(d), ['h: hi']);
});

scenario('a long chat keeps the newest 60 and never reuses a row file in use', d => {
  for (let i = 0; i < 75; i++) { const q = iType(d, `question ${i}`); agentSays(d, `answer ${i}`); }
  const recs = chat(d);
  assert.equal(recs.length, 60);
  assert.equal(recs[recs.length - 1].text, 'answer 74');
});

scenario('a reply with paragraphs stays one bubble, blank line and all, as in Messages', d => {
  const q = iType(d, 'flight?'); agentReacts(d, q);
  agentSays(d, '**UA 1149** is on time.\n\nLeave by 6:45.');
  assert.deepEqual(said(d), ['me: flight? [👍]', 'h: UA 1149 is on time.\n\nLeave by 6:45.']);
  d.advance(31000); d.run('Hermes Lock Screen');
  assert.deepEqual(said(d), ['me: flight? [👍]', 'h: UA 1149 is on time.\n\nLeave by 6:45.']);
  assert(chat(d).every(r => r.key.startsWith('m')), 'confirmed');
  const words = screen(d).find(x => x.text.includes('UA 1149'));
  assert.equal(words.text, 'UA 1149 is on time.\n\nLeave by 6:45.', 'drawn as one block with its blank line');
});

scenario('a reaction to a voice note that never reached the chat doesn’t move another one', d => {
  const lost = d.message({ from: d.me, attach: 'Audio Recording 1.mp4' });   // Talk to Hermes never ran for it
  d.advance(20000);
  agentReacts(d, lost, 'Like', { run: false });
  agentSays(d, 'Got it.');
  d.advance(110000);
  const v = voiceNote(d, 'Second one.');
  agentReacts(d, v);
  agentSays(d, 'Got the second.');
  d.advance(40000);
  d.run('Hermes Chat Renderer');   // reads both reactions
  assert.deepEqual(said(d), ['h: Got it.', 'me: 🎤 Second one. [👍]', 'h: Got the second.']);
});

scenario('iOS 26: a new install doesn’t guess whose earlier messages are whose; notifications fill it in', d => {
  d.message({ from: AGENT, body: 'earlier answer', at: d.clock - 600000 });
  d.message({ from: d.me, body: 'earlier question', at: d.clock - 660000 });
  agentSays(d, 'a new reply');
  assert.deepEqual(said(d), ['h: a new reply'], 'nothing in Messages says who sent the earlier two');
  const q = iType(d, 'thanks!'); agentReacts(d, q, 'Love');
  assert.deepEqual(said(d), ['h: a new reply', 'me: thanks! [❤️]'], 'your words are yours once the chat has a start');
});

scenario('a new install starts from what is already in Messages', d => {
  const q = d.message({ from: d.me, body: 'earlier question', at: d.clock - 3 * 3600 * 1000 });
  d.message({ from: AGENT, body: 'earlier answer', at: d.clock - 3 * 3600 * 1000 + 5000 });
  d.run('Hermes Lock Screen');
  assert.deepEqual(said(d), ['me: earlier question', 'h: earlier answer']);
}, { senderNames: true });   // needs to know who sent each message (iOS 26 doesn't say)

// The message classifier's cases (ported from the earlier parser tests): one input through the renderer.
const render = (d, input) => d.run('Hermes Chat Renderer', typeof input === 'string' ? input : d.trigger(input));
const fromAgent = (d, body) => render(d, d.message({ from: AGENT, body, indexedAfter: 1e12 }));
for (const text of ['4', '4.', '0', '42', '1000', '1.5', '-1', '+1', 'yes', '👍', '1\n2\n3']) {
  scenario(`classifier: the reply ${JSON.stringify(text)} is kept as it is`, d => {
    fromAgent(d, text);
    assert.deepEqual(said(d), [`h: ${text}`]);
  });
}
scenario('classifier: your words and blank transcriptions', d => {
  render(d, 'me: hello');
  render(d, 'me: \t\n');
  render(d, 'me: hello');
  assert.deepEqual(said(d), ['me: hello', 'me: hello']);
  assert.equal(status(d), '');
});
for (const raw of ['Reacted 👀 to “Can you hear me?”', 'Reacted 👀 to "Can you hear me?"', 'Hermes reacted 👀 to “Can you hear me?”',
                   'Hermes: Reacted 👀 to “Can you hear me?”', 'Liked “Can you hear me?”']) {
  scenario(`classifier: ${raw} adds what you typed, read`, d => {
    fromAgent(d, raw);
    assert.deepEqual(said(d).map(x => x.replace(/ \[.*\]$/, '')), ['me: Can you hear me?']);
    assert.equal(status(d), 'thinking');
  });
}
scenario('classifier: a second tapback on the same words badges it instead of repeating it', d => {
  render(d, 'me: repeat');
  fromAgent(d, 'Reacted 👍 to “repeat”');
  fromAgent(d, 'Loved “repeat”');
  assert.deepEqual(said(d), ['me: repeat [❤️]']);
});
scenario('classifier: tapbacks on attachments with nothing to badge change nothing', d => {
  fromAgent(d, 'Liked an attachment');
  fromAgent(d, 'Reacted 👀 to an attachment');
  assert.deepEqual(said(d), []);
});
for (const raw of ['me: /reset', 'Reacted 👀 to “/new”']) {
  scenario(`classifier: ${raw} clears the chat`, d => {
    fromAgent(d, 'old'); render(d, raw.startsWith('me:') ? raw : d.message({ from: AGENT, body: raw, indexedAfter: 1e12 }));
    assert.deepEqual(said(d), []);
  });
}
scenario('classifier: status lines and ordinary replies', d => {
  fromAgent(d, '⏳ Working — 1 min');
  assert.deepEqual(said(d), []);
  fromAgent(d, 'I reacted to your suggestion.');
  fromAgent(d, 'sync complete — me: done');
  assert.deepEqual(said(d), ['h: I reacted to your suggestion.', 'h: sync complete — me: done']);
});

// What is drawn.
const opened = (d, since) => d.log.slice(since).filter(e => e[0] === 'open').map(e => e[1]);
scenario('screen: Delivered, then Read with the typing bubble, then the reply with no receipt', d => {
  const q = voiceNote(d, 'yo');
  assert(screenText(d).includes('Delivered'));
  agentReacts(d, q);
  const t = screenText(d);
  assert(t.includes('Read') && !t.includes('Delivered'));
  assert(flatten(d.wallpapers.at(-1).img).some(x => x.image === 'typing-turn.png'), 'typing bubble after your message');
  agentSays(d, 'hey');
  assert(!screenText(d).includes('Read') && !screenText(d).includes('Delivered'));
  assert(!flatten(d.wallpapers.at(-1).img).some(x => x.image && x.image.startsWith('typing')));
});
scenario('screen: tails end each run; a quiet spell opens with a timestamp', d => {
  iType(d, 'a'); iType(d, 'b');
  agentSays(d, 'c');
  const items = flatten(d.wallpapers.at(-1).img), y = t => items.find(x => x.text === t).y;
  const tails = items.filter(x => x.image && x.image.startsWith('tail-')).map(x => [x.image, x.y]);
  assert.equal(tails.filter(([n, ty]) => n === 'tail-right.png' && ty > y('a') && ty < y('b')).length, 0, '"a" runs on into "b": no tail');
  assert.equal(tails.filter(([n, ty]) => n === 'tail-right.png' && ty > y('b') && ty < y('c')).length, 1, '"b" ends your run');
  assert.equal(tails.filter(([n, ty]) => n === 'tail-left.png' && ty > y('c')).length, 1, 'the newest has its tail');
  d.advance(20 * 60 * 1000);
  agentSays(d, 'later');
  const texts = screenText(d);
  const day = new Date(d.clock + d.tz * 60000).toLocaleDateString('en-US', { weekday: 'long', timeZone: 'UTC' });
  assert(texts.filter(x => x === day).length >= 2, 'a timestamp for the first message and for "later"');
});
scenario('screen: a long chat fills to the clock and fades into the wall under it', d => {
  for (let i = 0; i < 14; i++) { iType(d, `question number ${i} with a few more words`); agentSays(d, `answer number ${i}, which is also a little longer`); }
  const img = d.wallpapers.at(-1).img;
  assert.equal(img.op, 'overlay', `drawn as ${img.op}`);
  assert.equal(img.over.op, 'mask', `the stack fades into the wall (got ${img.over.op})`);
  const texts = screen(d).filter(x => x.size === T.type.body.size);
  assert(Math.max(...texts.map(x => x.y)) < T.zones.chatBottom, 'nothing below the flashlight row');
  assert(texts.some(x => x.y < T.zones.fadeClear), 'older bubbles reach up into the fade');
  assert.equal(texts.at(-1).text.replace(/\n/g, ' '), 'answer number 13, which is also a little longer');
});
scenario('screen: a tapback badge sits on the top corner of the bubble, toward the middle', d => {
  const q = iType(d, 'ship it'); agentReacts(d, q, 'Love');
  const items = flatten(d.wallpapers.at(-1).img);
  const badge = items.find(x => x.image === 'tapback-them.png'), heart = items.find(x => x.text === '❤️');
  const words = items.find(x => x.text === 'ship it');
  assert(badge && heart && words);
  assert(badge.x < words.x && badge.y < words.y, 'badge at the top-left of your bubble');
  assert(Math.abs(heart.x + 24 - (badge.x + M.tapback.anchorX)) <= 2, 'emoji centred on the badge');
});

scenario('the wall follows the hour, and falls back to the night wall', d => {
  for (const name of ['wall-dawn.png', 'wall-day.png', 'wall-dusk.png']) d.files.set(`Hermes/${name}`, new Img(W, T.canvas.height, { name }));
  const wallAt = hour => {
    const local = new Date(d.clock + d.tz * 60000);
    d.clock += (((hour - local.getUTCHours()) + 24) % 24) * 3600000;
    d.run('Hermes Chat Renderer');
    return flatten(d.wallpapers.length ? null : null) && null || (() => { const r = d.run('Hermes Chat Renderer'); return flatten(r).find(x => x.image && x.image.startsWith('wall')).image; })();
  };
  assert.equal(wallAt(6), 'wall-dawn.png');
  assert.equal(wallAt(12), 'wall-day.png');
  assert.equal(wallAt(18), 'wall-dusk.png');
  assert.equal(wallAt(23), 'wall.png');
  assert.equal(wallAt(3), 'wall.png');
  d.files.delete('Hermes/wall-day.png');
  assert.equal(wallAt(12), 'wall.png');
});

scenario('a burst of replies: each shows from its notification; Messages is read once', d => {
  const q = iType(d, 'plan my day'); agentReacts(d, q);
  const finds = () => d.log.filter(e => e[0] === 'open' && e[1] === 'Hermes/chat.json').length;
  const sizes = [];
  for (const text of ['Morning: gym at 7.', 'Then standup at 10.', 'Lunch with Maya at 12:30.']) {
    const before = d.messages.length;
    agentSays(d, text);
    sizes.push(said(d).length);
  }
  assert.deepEqual(said(d), ['me: plan my day [👀]'.replace('👀', '👍'), 'h: Morning: gym at 7.', 'h: Then standup at 10.', 'h: Lunch with Maya at 12:30.']);
  const st = JSON.parse(d.files.get('Hermes/update-status.json').data);
  assert(st.stage.endsWith('not due'), `the last reply didn't read Messages (${st.stage})`);
});
scenario('a notification that arrives after Messages already had the message leaves no copy', d => {
  const m = d.message({ from: AGENT, body: 'late automation' });
  d.advance(1000);
  const q = iType(d, 'hm?'); agentReacts(d, q);       // this update reads Messages and finds both
  automation(d, m);                                   // the late automation for "late automation"
  assert.deepEqual(said(d), ['h: late automation', 'me: hm? [👍]']);
  d.advance(40000);
  automation(d, agentSays(d, 'ok', { run: false }));
  assert.deepEqual(said(d), ['h: late automation', 'me: hm? [👍]', 'h: ok']);
});

scenario('screen: a long reply keeps every line, unsqueezed, as it rises into the fade', d => {
  for (let i = 0; i < 6; i++) { iType(d, `question ${i}`); agentSays(d, `answer ${i}`); }
  const long = Array.from({ length: 14 }, (_, k) => `Line ${k + 1} of a long reply that keeps going`).join(' ');
  agentSays(d, long);
  const block = () => screen(d).filter(x => (x.partOf ?? x.text).includes('Line 1 of'));
  const first = block();
  const pitch = T.type.body.size * 61.5 / 51;
  for (let i = 0; i < 8; i++) {
    iType(d, `more ${i}`); agentSays(d, `reply ${i}`);
    const lines = block().flatMap(x => x.partOf ? [x] : x.text.split('\n').map((t, k) => ({ text: t, y: x.y + k * pitch })));
    for (let k = 1; k < lines.length; k++) assert(Math.abs(lines[k].y - lines[k - 1].y - pitch) < 0.01, 'lines keep their spacing');
  }
  assert(first.length, 'the long reply was drawn');
});

scenario('a long reply with wide letters stays as wide as a bubble can be, not tall and narrow', d => {
  const trip = 'Your train leaves Friday, December 12 at 9:10 a.m. from Penn Station, changing in Boston 🇺🇸\n\n' +
    '• Amtrak 171: New York 9:10 a.m. → Boston 1:25 p.m.\n• Downeaster 683: Boston 2:40 p.m. → Portland 5:10 p.m. on Friday, December 12.\n\n' +
    'All times are local to each station. Confirmed from your Amtrak booking email.';
  agentSays(d, trip);
  const rec = chat(d).at(-1);
  const maxBubble = T.bubble.maxText + 2 * T.bubble.padX;
  assert(Number(rec.bw) <= maxBubble, `no wider than a bubble may be (${rec.bw})`);
  assert(Number(rec.bw) >= maxBubble - 90, `as wide as it can be (${rec.bw} of ${maxBubble})`);
  const words = screen(d).find(x => x.text.startsWith('Your train'));
  const longest = Math.max(...words.text.split('\n').map(l => l.length));
  assert(longest >= 29, `lines run close to full width (${longest} characters)`);
  console.log(`      long reply: ${rec.bw} px wide, ${words.text.split('\n').length} lines`);
});

scenario('the kept stack draws exactly what drawing every bubble again draws', d => {
  const visible = img => flatten(img).flatMap(x => x.text !== undefined
    ? (x.partOf ? [{ t: x.text, x: x.x, y: Math.round(x.y) }] : x.text.split('\n').map((t, k) => ({ t, x: x.x, y: Math.round(x.y + k * x.size * 61.5 / 51) })))
    : [{ i: x.image, x: x.x, y: Math.round(x.y), h: x.h }])
    .filter(x => x.y >= T.zones.fadeOpaque - 10).map(x => JSON.stringify(x)).sort();
  const steps = [
    () => { const q = iType(d, 'what’s the plan?'); agentReacts(d, q, 'emoji:👀'); },
    () => agentSays(d, 'Morning: gym at 7.'),
    () => agentSays(d, 'Then standup at 10.'),
    () => { d.advance(20 * 60 * 1000); agentSays(d, 'Lunch with Maya at 12:30.'); },
    () => voiceNote(d, 'Can you move standup?'),
    () => agentReacts(d, d.messages.filter(m => m.attach).at(-1), 'Like'),
    () => agentSays(d, '👍'),
    () => { const q = iType(d, 'thanks'); agentReacts(d, q, 'Love'); },
    () => agentReacts(d, d.messages.find(m => m.body === 'Morning: gym at 7.'), 'Laugh'),   // an older bubble changes
    () => { for (let i = 0; i < 9; i++) agentSays(d, `note ${i}, a little longer so the chat fills the screen`); },
    () => { d.advance(31000); d.run('Hermes Lock Screen'); },
  ];
  for (const [i, step] of steps.entries()) {
    step();
    const kept = visible(d.wallpapers.at(-1).img);
    d.files.delete('Hermes/rows/col.png');
    const again = visible(d.run('Hermes Chat Renderer', new Date(d.clock)));   // a date only redraws
    assert.deepEqual(kept, again, `step ${i}: the kept stack differs from drawing everything again`);
  }
});

scenario('a row taller than its record says (two updates overlapped) is drawn at its real size, never squeezed', d => {
  const q = iType(d, 'hello?'); agentReacts(d, q, 'Like'); agentSays(d, 'hi there');
  const rec = chat(d).find(r => r.text === 'hello?');
  const f = d.files.get(`Hermes/rows/${rec.id}.png`);
  d.files.set(`Hermes/rows/${rec.id}.png`, new Img(f.w, f.h + 76, { op: 'combine', parts: [new Img(f.w, 76, {}), f] }));
  d.files.delete('Hermes/rows/col.png');
  agentSays(d, 'next');   // the simulator refuses any Overlay Image that would resize what it lays down
  const items = screen(d), y = t => items.find(x => x.text === t).y;
  assert(y('hello?') < y('hi there') && y('hi there') < y('next'));
});

scenario('voice notes and a burst of replies don’t read Messages again', d => {
  agentSays(d, 'hi');
  d.findFails = true;   // any read of Messages would fail here
  voiceNote(d, 'And tomorrow?');
  for (const text of ['Great.', 'Tomorrow is free.', 'Want me to book it?']) agentSays(d, text);
  assert.deepEqual(said(d), ['h: hi', 'me: 🎤 And tomorrow?', 'h: Great.', 'h: Tomorrow is free.', 'h: Want me to book it?']);
});

scenario('messages sent in a row: the next ones show as soon as the agent reacts to the first; a changed reaction follows', d => {
  agentSays(d, 'hi');
  d.advance(5000);
  const q = iType(d, 'When does my train leave?');
  iType(d, '?');
  agentReacts(d, q, 'emoji:👀');
  assert.deepEqual(said(d), ['h: hi', 'me: When does my train leave? [👀]', 'me: ?']);
  agentSays(d, 'Friday at 9:10 a.m.');
  agentReacts(d, q, 'Like');
  assert.deepEqual(said(d), ['h: hi', 'me: When does my train leave? [👍]', 'me: ?', 'h: Friday at 9:10 a.m.']);
});

scenario('a read of Messages skips what an earlier read handled', d => {
  for (let i = 0; i < 6; i++) { const q = iType(d, `q${i}`); agentReacts(d, q); agentSays(d, `a${i}`); d.advance(31000); }
  d.run('Hermes Lock Screen');
  const before = d.actionCount;
  d.advance(31000);
  d.run('Hermes Chat Renderer', 'sync');   // nothing new in Messages
  const cost = d.actionCount - before;
  assert(cost < 420, `a read with nothing new stays light (${cost} steps)`);
  assert(JSON.parse(d.files.get('Hermes/chat.json').data).known.split('\n').length > 10, 'what was read is remembered');
});

scenario('a Sun automation sets the light, which holds until the next one', d => {
  agentSays(d, 'hi');
  d.files.set('Hermes/wall-dusk.png', new Img(W, T.canvas.height, { name: 'wall-dusk.png' }));
  d.files.set('Hermes/wall-day.png', new Img(W, T.canvas.height, { name: 'wall-day.png' }));
  const wall = () => flatten(d.wallpapers.at(-1).img).find(x => x.image && x.image.startsWith('wall')).image;
  atLocal(d, 9, 0);
  d.findFails = true;   // a change of light never reads Messages
  d.run('Hermes Lock Screen', 'dusk');
  assert.equal(wall(), 'wall-dusk.png', 'the light passed in, not the hour');
  assert(statusOf(d).stage.endsWith('wall'), statusOf(d).stage);
  assert.deepEqual(said(d), ['h: hi'], 'the word adds no bubble');
  d.findFails = false;
  d.advance(2 * 3600 * 1000);
  agentSays(d, 'still dusk');
  assert.equal(wall(), 'wall-dusk.png', 'later messages keep it');
  d.advance(3 * 3600 * 1000);
  agentSays(d, 'much later');
  assert.equal(wall(), 'wall-day.png', 'a missed change falls back to the hour');
});

scenario('a badge cuts a thin gap into the bubble under it', d => {
  const q = iType(d, 'ship it'); agentReacts(d, q, 'Love');
  const rec = chat(d).find(r => r.text === 'ship it');
  const row = d.files.get(`Hermes/rows/${rec.id}.png`);
  const masks = []; (function walk(x) { if (!x || typeof x !== 'object') return; if (x.op === 'mask') masks.push(x.mask); for (const k of ['src', 'base', 'over']) walk(x[k]); for (const part of x.parts ?? []) walk(part); })(row);
  assert(masks.includes('Custom Image'), 'the row is cut where the badge sits');
});

scenario('rows drawn in an older look are redrawn once: badges lose their dark ring, long messages widen', d => {
  const q = iType(d, 'ship it'); agentReacts(d, q, 'Love'); agentSays(d, 'shipped');
  const long = Array.from({ length: 6 }, (_, k) => `Line ${k + 1} of a reply that is long enough to wrap`).join(' ');
  agentSays(d, long);
  const longId = chat(d).at(-1).id;
  d.files.set(`Hermes/rows/${longId}.png`, new Img(W, 10, { name: 'narrow-look' }));
  const f = d.files.get('Hermes/chat.json'), st = JSON.parse(f.data);
  delete st.look;
  d.files.set('Hermes/chat.json', { ...f, data: JSON.stringify(st) });
  const id = chat(d).find(r => r.text === 'ship it').id;
  d.files.set(`Hermes/rows/${id}.png`, new Img(W, 10, { name: 'old-look' }));
  d.run('Hermes Chat Renderer');
  assert.notEqual(d.files.get(`Hermes/rows/${id}.png`).name, 'old-look', 'the badge row was redrawn');
  assert.notEqual(d.files.get(`Hermes/rows/${longId}.png`).name, 'narrow-look', 'the long message was redrawn');
  assert.equal(JSON.parse(d.files.get('Hermes/chat.json').data).look, '3');
  const plain = chat(d).find(r => r.text === 'shipped').id, before = d.files.get(`Hermes/rows/${plain}.png`);
  d.run('Hermes Chat Renderer');
  assert.equal(d.files.get(`Hermes/rows/${plain}.png`), before, 'only once, and only rows that need it');
});

scenario('steps per update stay within budget', d => {
  for (let i = 0; i < 6; i++) { const q = iType(d, `question ${i} about tomorrow`); agentReacts(d, q); agentSays(d, `Answer ${i}, long enough to wrap onto a second line.`); d.advance(40000); }
  const cost = fn => { const c = d.actionCount; fn(); return d.actionCount - c; };
  d.advance(40000);
  const synced = cost(() => agentSays(d, 'A reply when Messages is due to be read.'));
  const reply = cost(() => agentSays(d, 'A reply right after.'));
  const tapback = cost(() => { const q = iType(d, 'ok sounds good'); agentReacts(d, q); });
  const voice = cost(() => voiceNote(d, 'And one more thing.'));
  const budget = { reply: 1260, tapback: 2450, voice: 1230, synced: 2190 };
  const got = { reply, tapback, voice, synced };
  for (const k of Object.keys(budget)) assert(got[k] <= budget[k], `${k}: ${got[k]} steps (budget ${budget[k]})`);
  console.log(`      steps: ${JSON.stringify(got)}`);
});

const statusOf = d => JSON.parse(d.files.get('Hermes/update-status.json').data);
function atLocal(d, h, m) {
  const local = new Date(d.clock + d.tz * 60000);
  let target = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), h, m) - d.tz * 60000;
  while (target <= d.clock) target += 86400000;
  d.clock = target;
}
function secondsOfYear(d) {
  const local = new Date(d.clock + d.tz * 60000);
  const doy = Math.floor((Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()) - Date.UTC(local.getUTCFullYear(), 0, 1)) / 86400000) + 1;
  return doy * 86400 + local.getUTCHours() * 3600 + local.getUTCMinutes() * 60 + local.getUTCSeconds();
}

let passed = 0, failed = 0;
const only = process.env.ONLY;
for (const { name, fn, opts } of scenarios) {
  if (only && !name.includes(only)) continue;
  const d = phone(opts);
  try {
    fn(d);
    if (d.files.has('Hermes/chat.json')) checkInvariants(d, name);
    passed++;
    console.log(`ok    ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL  ${name}\n      ${e.stack.split('\n').slice(0, 3).join('\n      ')}`);
    try { console.log('      chat:', JSON.stringify(said(d))); } catch {}
  }
}
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
