// Plays a typical exchange on the simulated iPhone, then counts the actions (and file reads and saves) of each kind
// of update by the generator function that wrote them. Run through tools/profile_steps.py.
import { readFileSync } from 'node:fs';
import { Device, Img } from './sim.mjs';

const [, , workflowsPath, originsPath, tokensPath, manifestPath, top = '14'] = process.argv;
const workflows = JSON.parse(readFileSync(workflowsPath, 'utf8'));
const origins = JSON.parse(readFileSync(originsPath, 'utf8'));
const T = JSON.parse(readFileSync(tokensPath, 'utf8')), M = JSON.parse(readFileSync(manifestPath, 'utf8'));
const W = T.canvas.width, AGENT = 'Hermes';

const d = new Device();
const names = new Map();
for (const [name, wf] of Object.entries(workflows)) { d.install(name, wf); names.set(wf.WFWorkflowActions, name); }
const r = workflows['Hermes Chat Renderer'], q = r.WFWorkflowImportQuestions[0];
const renderer = JSON.parse(JSON.stringify(r));
renderer.WFWorkflowActions[q.ActionIndex].WFWorkflowActionParameters.WFTextActionText = { Value: { string: AGENT }, WFSerializationType: 'WFTextTokenString' };
d.install('Hermes Chat Renderer', renderer);
names.set(renderer.WFWorkflowActions, 'Hermes Chat Renderer');
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
d.onSend = content => d.message({ from: d.me, attach: content.name + '', indexedAfter: 0 });

const automation = m => d.run('Hermes Lock Screen', d.trigger(m));
const agentSays = body => { const m = d.message({ from: AGENT, body }); automation(m); d.advance(1500); return m; };
const iType = body => { const m = d.message({ from: d.me, body }); d.advance(1200); return m; };
const agentReacts = target => {
  const m = d.message({ from: AGENT, body: `Liked “${target.body}”`, type: 'Reaction', reaction: 'Like', ref: target });
  automation(m); d.advance(800); return m;
};
const voiceNote = words => {
  const send = d.onSend;
  d.onSend = content => { d.transcripts.set(content.name.replace(/\.[^.]+$/, ''), words); send(content); };
  d.run('Talk to Hermes');
  d.onSend = send; d.advance(1000);
};

for (let i = 0; i < 6; i++) {
  const m = iType(`question ${i} about tomorrow`); agentReacts(m);
  agentSays(`Answer ${i}, long enough to wrap onto a second line.`); d.advance(40000);
}

function profile(label, fn) {
  const counts = new Map(), files = d.log.length;
  const kinds = new Map();
  let total = 0;
  d.onStep = (actions, pc) => {
    const name = names.get(actions) ?? '?';
    const key = `${name.replace(/^Hermes /, '')}: ${origins[name]?.[pc] ?? '?'}`;
    counts.set(key, (counts.get(key) ?? 0) + 1); total++;
    if (name === 'Hermes Chat Renderer') {
      const id = actions[pc].WFWorkflowActionIdentifier.replace('is.workflow.actions.', '');
      kinds.set(id, (kinds.get(id) ?? 0) + 1);
    }
  };
  fn();
  d.onStep = undefined;
  const io = d.log.slice(files);
  const opens = io.filter(e => e[0] === 'open').map(e => e[1].replace('Hermes/', ''));
  const saves = io.filter(e => e[0] === 'save').map(e => e[1].replace('Hermes/', ''));
  console.log(`\n${label}: ${total} actions, ${opens.length} reads, ${saves.length} saves`);
  console.log(`  reads: ${opens.join(', ')}\n  saves: ${saves.join(', ')}`);
  for (const [key, n] of [...counts].sort((a, b) => b[1] - a[1]).slice(0, Number(top))) console.log(`  ${String(n).padStart(5)}  ${key}`);
  console.log('  renderer actions by kind: ' + [...kinds].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(', '));
}

d.advance(40000);
profile('a reply, then Messages is read (due)', () => agentSays('A reply when Messages is due to be read.'));
profile('a reply', () => agentSays('A reply right after, which wraps onto a second line here.'));
profile('a tapback on your message (reads Messages)', () => { const m = iType('ok sounds good'); agentReacts(m); });
profile('a voice note (Talk to Hermes)', () => voiceNote('And one more thing.'));
