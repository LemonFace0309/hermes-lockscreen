// Runs the generated shortcuts offline, action by action, on a simulated iPhone: text, numbers, lists,
// dictionaries, control flow, files (in memory), dates (a clock and time zone the test controls), images (sizes and
// what was drawn where), Find Messages over a fake Messages database (with indexing delay), Run Shortcut, Set
// Wallpaper, Record Audio, Send Message, Transcribe and Get Details of Images. Regular expressions use ICU syntax, translated to JavaScript.
// It checks the generated logic itself; it can't check how iOS draws, how fast it is, or iOS's own quirks.

const PREFIX = 'is.workflow.actions.';
const RS = '␞';

export class Img {
  constructor(w, h, info = {}) { this.w = Math.round(w); this.h = Math.round(h); Object.assign(this, info); }
}
export class Entity {
  constructor(type, props, text) { this.type = type; this.props = props; this.text = text; }
}
export class Dict { constructor(o = {}) { this.o = o; } }
/** An item of Match Text's output: text actions read it, but If can't test it until it becomes text. */
export class Match { constructor(s) { this.s = s; } }
class Stop { constructor(result) { this.result = result; } }

const segmenter = new Intl.Segmenter('en', { granularity: 'grapheme' });
const graphemes = s => [...segmenter.segment(s)].length;

export function formatNumber(n) {
  if (!Number.isFinite(n)) throw new Error(`not a number: ${n}`);
  if (Number.isInteger(n)) return String(n);
  return String(Number(n.toPrecision(15)));
}

export function asText(v) {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return formatNumber(v);
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) return v.map(asText).join('\n');
  if (v instanceof Dict) return JSON.stringify(v.o);
  if (v instanceof Match) return v.s;
  if (v instanceof Entity) return v.text;
  if (v instanceof Img) return '';
  if (v.kind === 'file') return typeof v.data === 'string' ? v.data : '';
  if (v instanceof Date) return v.toISOString();
  throw new Error(`can't make text of ${JSON.stringify(v)}`);
}

export function asNumber(v, strict = true) {
  if (typeof v === 'number') return v;
  const t = asText(v).trim();
  if (t === '' || !/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) {
    if (strict) throw new Error(`Calculate on non-number text ${JSON.stringify(t)}`);
    return 0;
  }
  return Number(t);
}

// ICU → JavaScript regular expressions.
const SYNTAX = new Set('^$\\.*+?()[]{}|/'.split(''));
export function jsRegex(pattern, { caseSensitive = true, global = false } = {}) {
  let flags = 'u' + (caseSensitive ? '' : 'i') + (global ? 'g' : '');
  let p = pattern.replace(/^\(\?([imsx]+)\)/, (_, f) => { for (const c of f) if (!flags.includes(c)) flags += c; return ''; });
  p = p.replace(/\\x\{([0-9A-Fa-f]+)\}/g, '\\u{$1}')
       .replace(/\\p\{(Han|Hiragana|Katakana|Hangul|Latin|Greek|Cyrillic)\}/g, '\\p{Script=$1}');
  // u mode refuses identity escapes of non-syntax characters ("\'", "\,"): drop the backslash.
  let out = '', inClass = false;
  for (let i = 0; i < p.length; i++) {
    const c = p[i];
    if (c === '\\' && i + 1 < p.length) {
      const n = p[i + 1];
      if (/[A-Za-z0-9]/.test(n) || SYNTAX.has(n) || (inClass && n === '-')) { out += c + n; }
      else { out += n; }
      i++; continue;
    }
    if (c === '[' && !inClass) inClass = true; else if (c === ']' && inClass) inClass = false;
    out += c;
  }
  return new RegExp(out, flags);
}
// ICU replacement text: $n is a group, a backslash makes the next character literal.
function icuReplacement(rep) {
  return (...args) => {
    const groups = args.slice(1, -2);
    let out = '';
    for (let i = 0; i < rep.length; i++) {
      const c = rep[i];
      if (c === '\\' && i + 1 < rep.length) { out += rep[++i]; continue; }
      if (c === '$' && /\d/.test(rep[i + 1] ?? '')) { out += groups[Number(rep[++i]) - 1] ?? ''; continue; }
      out += c;
    }
    return out;
  };
}

// Dates in a time zone given as minutes east of UTC (the device's, which tests can change).
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
export function formatDate(date, pattern, tz) {
  const local = new Date(date.getTime() + tz * 60000);
  const Y = local.getUTCFullYear(), Mo = local.getUTCMonth() + 1, d = local.getUTCDate(), H = local.getUTCHours();
  const mi = local.getUTCMinutes(), sec = local.getUTCSeconds(), ms = local.getUTCMilliseconds();
  const doy = Math.floor((Date.UTC(Y, Mo - 1, d) - Date.UTC(Y, 0, 1)) / 86400000) + 1;
  const pad = (n, w) => String(n).padStart(w, '0');
  const off = (sep) => { const a = Math.abs(tz); return (tz < 0 ? '-' : '+') + pad(Math.floor(a / 60), 2) + sep + pad(a % 60, 2); };
  const tokens = { yyyy: pad(Y, 4), yy: pad(Y % 100, 2), MM: pad(Mo, 2), dd: pad(d, 2), D: String(doy), HH: pad(H, 2),
    H: String(H), mm: pad(mi, 2), m: String(mi), ss: pad(sec, 2), s: String(sec), SSS: pad(ms, 3), EEEE: DAYS[local.getUTCDay()],
    xx: off(''), XXX: tz === 0 ? 'Z' : off(':'), A: String(((H * 60 + mi) * 60 + sec) * 1000 + ms) };
  let out = '';
  for (let i = 0; i < pattern.length;) {
    if (pattern[i] === "'") { const j = pattern.indexOf("'", i + 1); out += pattern.slice(i + 1, j); i = j + 1; continue; }
    const t = ['yyyy', 'EEEE', 'SSS', 'XXX', 'yy', 'MM', 'dd', 'HH', 'mm', 'ss', 'xx', 'D', 'H', 'm', 's', 'A'].find(k => pattern.startsWith(k, i));
    if (t) { out += tokens[t]; i += t.length; } else { out += pattern[i++]; }
  }
  return out;
}
export function shortTime(date, tz) {
  const local = new Date(date.getTime() + tz * 60000);
  const h = local.getUTCHours(), m = local.getUTCMinutes();
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

/** A simulated phone. `messages` are Messages' database; `files` the Shortcuts iCloud folder. */
export class Device {
  constructor({ now = Date.UTC(2026, 9, 28, 18, 0, 0), tz = -420, me = 'Sam Lee', agent = 'Hermes',
                senderNames = false } = {}) {
    this.clock = now; this.tz = tz; this.me = me; this.agent = agent;
    this.senderNames = senderNames;   // iOS 26 leaves a message's Sender empty; a later iOS may name it
    this.files = new Map(); this.shortcuts = new Map(); this.messages = []; this.wallpapers = []; this.sent = [];
    this.transcripts = new Map(); this.log = []; this.actionCount = 0; this.tick = 2;   // ms of clock per action
    this.findFails = false; this.indexLag = 0; this.limitSort = true;
  }
  now() { return new Date(this.clock); }
  advance(ms) { this.clock += ms; }
  install(name, workflow) { this.shortcuts.set(name, workflow); }
  /** Adds a message to Messages; `indexedAfter` ms from now it shows in Find Messages. */
  message({ from, body = '', attach = '', at = this.clock, type = 'Unspecified', reaction = '', ref = null,
            conversation = this.agent, indexedAfter = this.indexLag, noDate = false }) {
    const m = { from, body, attach, at, type, reaction, ref, conversation, indexedAt: this.clock + indexedAfter, noDate };
    this.messages.push(m);
    return m;
  }
  entity(m) {
    const props = { Conversation: new Entity('Conversation', {}, m.conversation), Sender: this.senderNames ? m.from : '',
      Date: m.noDate ? null : new Date(m.at),
      Body: m.body, Type: m.type, Reaction: m.reaction,
      Reference: m.ref ? this.entity(m.ref) : null };
    // On iOS 26, reading a voice note's attachments ends the shortcut (Hermes Read Probe, 2026-10-29).
    Object.defineProperty(props, 'Attachments', { enumerable: true, get() {
      if (m.attach) throw new Error('iOS 26 stops the shortcut when it reads a message’s attachments');
      return '';
    } });
    return new Entity('Message', props, m.conversation);
  }
  /** The Message automation's input for a received message (what iOS hands the shortcut). */
  trigger(m) {
    let content = m.body;
    if (m.type === 'Reaction') content = m.body;
    return new Entity('MessageInput', { Content: content, Sender: '+1 (555) 010-0000' }, content);
  }
  run(name, input = null, depth = 0) {
    const wf = this.shortcuts.get(name);
    if (!wf) throw new Error(`no shortcut named ${name}`);
    return new Runner(this, wf, input, depth).run();
  }
}

class Runner {
  constructor(device, wf, input, depth) {
    this.d = device; this.actions = wf.WFWorkflowActions; this.input = input; this.depth = depth;
    this.vars = new Map(); this.outputs = new Map(); this.loops = [];
    this.jump = new Map();
    const open = [];
    this.actions.forEach((a, i) => {
      const p = a.WFWorkflowActionParameters, mode = p.WFControlFlowMode;
      if (mode === undefined) return;
      if (mode === 0) open.push({ g: p.GroupingIdentifier, start: i, mid: null });
      else {
        const top = open[open.length - 1];
        if (!top || top.g !== p.GroupingIdentifier) throw new Error(`unbalanced control flow at ${i}`);
        if (mode === 1) top.mid = i;
        else { open.pop(); this.jump.set(top.start, top); top.end = i; if (top.mid != null) this.jump.set(top.mid, top); this.jump.set(i, top); }
      }
    });
  }
  value(v) {
    if (v == null || typeof v !== 'object') return v;
    if (v.WFSerializationType === 'WFTextTokenAttachment') return this.value(v.Value);
    if (v.WFSerializationType === 'WFTextTokenString') {
      let s = v.Value.string;
      const only = Object.values(v.Value.attachmentsByRange ?? {});
      if (s === '\uFFFC' && only.length === 1) return this.value(only[0]);   // a field holding just one variable passes it as is
      const parts = Object.entries(v.Value.attachmentsByRange ?? {}).map(([k, a]) => [Number(k.match(/\d+/)[0]), a]).sort((a, b) => b[0] - a[0]);
      // attachment ranges are UTF-16 offsets
      for (const [i, a] of parts) {
        if (!['Variable', 'ActionOutput', 'ExtensionInput', 'CurrentDate', 'Clipboard'].includes(a.Type))
          throw new Error(`a text field holds ${a.WFSerializationType ?? a.Type} inside it: Shortcuts drops that`);
        s = s.slice(0, i) + asText(this.value(a)) + s.slice(i + 1);
      }
      return s;
    }
    if (v.Type === 'Variable') return this.aggrandize(v.Variable ? this.value(v.Variable) : this.lookup(v.VariableName), v.Aggrandizements);
    if (v.Type === 'ActionOutput') {
      if (!this.outputs.has(v.OutputUUID)) throw new Error(`output used before its action ran: ${v.OutputName}`);
      return this.aggrandize(this.outputs.get(v.OutputUUID), v.Aggrandizements);
    }
    if (v.Type === 'ExtensionInput') return this.aggrandize(this.input, v.Aggrandizements);
    if (v.Value && v.WFSerializationType) return v.Value;
    return v;
  }
  lookup(name) {
    const m = name.match(/^Repeat (Item|Index)(?: (\d+))?$/);
    if (m) {
      const frame = this.loops[(m[2] ? Number(m[2]) : 1) - 1];
      if (!frame) throw new Error(`${name} used outside its loop (depth ${this.loops.length})`);
      return m[1] === 'Item' ? frame.items[frame.index] : frame.index + 1;
    }
    return this.vars.has(name) ? this.vars.get(name) : null;
  }
  aggrandize(v, aggs) {
    for (const a of aggs ?? []) {
      if (a.Type === 'WFDictionaryValueVariableAggrandizement') {
        v = v instanceof Dict ? (v.o[a.DictionaryKey] ?? null) : null;
      } else if (a.Type === 'WFPropertyVariableAggrandizement') {
        if (v instanceof Entity) v = a.PropertyName in v.props ? v.props[a.PropertyName] : (() => { throw new Error(`no property ${a.PropertyName} on ${v.type}`); })();
        else if (v == null) v = null;
        else throw new Error(`property ${a.PropertyName} of ${typeof v}`);
      } else throw new Error(`aggrandizement ${a.Type}`);
    }
    return v;
  }
  cond(p) {
    const x = this.value(p.WFInput), s = asText(this.value(p.WFConditionalActionString));
    if (x instanceof Match && [4, 8, 99].includes(p.WFCondition))
      throw new Error(`If on a Match Text item ${JSON.stringify(x.s)}: Please choose a value for each parameter in this action.`);
    switch (p.WFCondition) {
      case 4: return asText(x) === s;
      case 8: return asText(x).startsWith(s);
      case 99: return asText(x).includes(s);
      // Shortcuts offers "is greater/less than" only for numbers: on text the action has no number and won't run.
      case 2: case 0: {
        if (typeof x !== 'number') throw new Error(`If "${p.WFCondition === 2 ? 'is greater than' : 'is less than'}" on ${x === null ? 'nothing' : typeof x} ${JSON.stringify(x)}: Please choose a value for each parameter in this action.`);
        const n = asNumber(this.value(p.WFNumberValue));
        return p.WFCondition === 2 ? x > n : x < n;
      }
      case 100: return x != null && !(Array.isArray(x) && x.length === 0);
      case 101: return x == null || (Array.isArray(x) && x.length === 0);
      default: throw new Error(`condition ${p.WFCondition}`);
    }
  }
  run() {
    const A = this.actions;
    try {
      for (let pc = 0; pc < A.length; pc++) {
        if (++this.d.actionCount > 5e6) throw new Error('runaway');
        this.d.onStep?.(A, pc, this);   // profiling and debugging hook (tools/profile_steps.py)
        this.d.clock += this.d.tick;
        const a = A[pc], p = a.WFWorkflowActionParameters;
        const id = a.WFWorkflowActionIdentifier.startsWith(PREFIX) ? a.WFWorkflowActionIdentifier.slice(PREFIX.length) : a.WFWorkflowActionIdentifier;
        const mode = p.WFControlFlowMode;
        if (id === 'conditional') {
          const g = this.jump.get(pc);
          if (mode === 0) { if (!this.cond(p)) pc = g.mid ?? g.end; }
          else if (mode === 1) pc = g.end;
          continue;
        }
        if (id === 'repeat.count' || id === 'repeat.each') {
          const g = this.jump.get(pc);
          if (mode === 0) {
            const items = id === 'repeat.count'
              ? Array.from({ length: Math.max(0, Math.floor(asNumber(this.value(p.WFRepeatCount)))) }, (_, i) => i + 1)
              : (v => v == null ? [] : Array.isArray(v) ? v : [v])(this.value(p.WFInput));
            if (!items.length) { pc = g.end; continue; }
            this.loops.push({ items, index: 0, start: pc });
          } else {
            const f = this.loops[this.loops.length - 1];
            if (++f.index < f.items.length) pc = f.start; else this.loops.pop();
          }
          continue;
        }
        const out = this.exec(id, p);
        if (p.UUID) this.outputs.set(p.UUID, out);
      }
    } catch (e) {
      if (e instanceof Stop) return e.result;
      throw e;
    }
    return null;
  }
  text(v) { return asText(this.value(v)); }
  exec(id, p) {
    const d = this.d, v = x => this.value(x), t = x => this.text(x);
    switch (id) {
      case 'comment': return;
      case 'gettext': return t(p.WFTextActionText);
      case 'number': return Number(p.WFNumberActionNumber);
      case 'setvariable': this.vars.set(p.WFVariableName, v(p.WFInput)); return;
      case 'appendvariable': {
        const cur = this.vars.get(p.WFVariableName), add = v(p.WFInput);
        const list = cur == null ? [] : Array.isArray(cur) ? [...cur] : [cur];
        this.vars.set(p.WFVariableName, list.concat(Array.isArray(add) ? add : [add])); return;
      }
      case 'nothing': return null;
      case 'math': {
        const a = asNumber(v(p.WFInput)), b = asNumber(v(p.WFMathOperand));
        switch (p.WFMathOperation) { case '+': return a + b; case '-': return a - b; case '×': return a * b; case '÷': return a / b; }
        throw new Error(`math ${p.WFMathOperation}`);
      }
      case 'calculateexpression': {
        const expr = t(p.Input);
        if (!/^[0-9+\-*\/(). ]+$/.test(expr)) throw new Error(`Calculate Expression: ${expr}`);
        if (/(^|[^0-9.])0\d/.test(expr)) throw new Error(`Calculate Expression with a leading zero: ${expr}`);
        return Function(`"use strict"; return (${expr});`)();
      }
      case 'round': {
        const x = asNumber(v(p.WFInput));
        return p.WFRoundMode === 'Always Round Up' ? Math.ceil(x) : p.WFRoundMode === 'Always Round Down' ? Math.floor(x) : Math.round(x);
      }
      case 'text.replace': {
        for (const k of ['WFReplaceTextFind', 'WFReplaceTextReplace'])
          if (p[k] && typeof p[k] === 'object' && p[k].WFSerializationType !== 'WFTextTokenString')
            throw new Error(`Replace Text's ${k} holds a bare variable: Shortcuts ignores it`);
        const input = t(p.WFInput), find = t(p.WFReplaceTextFind), rep = t(p.WFReplaceTextReplace ?? '');
        if (!p.WFReplaceTextRegularExpression) return find === '' ? input : input.split(find).join(rep);
        return input.replace(jsRegex(find, { caseSensitive: p.WFReplaceTextCaseSensitive !== false, global: true }), icuReplacement(rep));
      }
      case 'text.trimwhitespace': return t(p.WFInput).trim();
      case 'text.match': {
        const s = t(p.text), re = jsRegex(t(p.WFMatchTextPattern), { caseSensitive: p.WFMatchTextCaseSensitive !== false, global: true });
        return [...s.matchAll(re)].map(m => new Match(m[0]));
      }
      case 'text.changecase': {
        const s = t(p.text);
        return p.WFCaseType === 'lowercase' ? s.toLowerCase() : p.WFCaseType === 'UPPERCASE' ? s.toUpperCase() : s;
      }
      case 'getitemfromlist': {
        const x = v(p.WFInput), list = x == null ? [] : Array.isArray(x) ? x : [x];
        if (!list.length) return null;
        if (p.WFItemSpecifier === 'First Item') return list[0];
        if (p.WFItemSpecifier === 'Last Item') return list[list.length - 1];
        const i = asNumber(v(p.WFItemIndex));
        if (i < 1 || i > list.length) throw new Error(`Get Item at index ${i} of ${list.length}`);
        return list[i - 1];
      }
      case 'count': {
        const x = v(p.Input);
        if (p.WFCountType === 'Items') return x == null ? 0 : Array.isArray(x) ? x.length : 1;
        return graphemes(asText(x));
      }
      case 'dictionary': {
        const o = {};
        for (const item of p.WFItems.Value.WFDictionaryFieldValueItems) o[t(item.WFKey)] = t(item.WFValue);
        return new Dict(o);
      }
      case 'getvalueforkey': {
        const x = v(p.WFInput), k = t(p.WFDictionaryKey);
        return x instanceof Dict ? (x.o[k] ?? null) : null;
      }
      case 'detect.dictionary': {
        const x = v(p.WFInput);
        if (x instanceof Dict) return x;
        try { return new Dict(JSON.parse(asText(x))); } catch { return new Dict({}); }
      }
      case 'documentpicker.open': {
        const path = t(p.WFGetFilePath);
        d.log.push(['open', path]);
        if (d.files.has(path)) return d.files.get(path);
        if (p.WFFileErrorIfNotFound) throw new Error(`Get File: ${path} not found`);
        return null;
      }
      case 'documentpicker.save': {
        const path = t(p.WFFileDestinationPath), x = v(p.WFInput);
        if (!path || path.endsWith('/')) throw new Error(`Save File without a name: ${path}`);
        const data = x instanceof Dict ? JSON.stringify(x.o) : x instanceof Img ? x : (x && x.kind === 'file') ? x.data : asText(x);
        d.files.set(path, data instanceof Img ? data : { kind: 'file', name: path, data });
        d.log.push(['save', path]);
        return d.files.get(path);
      }
      case 'date': return d.now();
      case 'format.date': {
        const x = v(p.WFDate), date = x instanceof Date ? x : new Date(asText(x));
        if (!(date instanceof Date) || Number.isNaN(date.getTime())) throw new Error(`Format Date of ${asText(x)}`);
        if (p.WFDateFormatStyle === 'Custom') return formatDate(date, p.WFDateFormat, d.tz);
        if (p.WFDateFormatStyle === 'None' && p.WFTimeFormatStyle === 'Short') return shortTime(date, d.tz);
        throw new Error('date style');
      }
      case 'getitemtype': {
        const x = v(p.WFInput);
        if (x == null) return null;
        if (typeof x === 'string' || x instanceof Match) return 'Text';
        if (typeof x === 'number') return 'Number';
        if (x instanceof Img) return 'Image';
        if (x instanceof Date) return 'Date';
        if (x instanceof Dict) return 'Dictionary';
        if (x instanceof Entity) return x.type === 'MessageInput' ? 'Message' : x.type;
        if (x.kind === 'file') return 'File';
        return 'Unknown';
      }
      case 'image.crop': {
        const img = v(p.WFInput), x = asNumber(t(p.WFImageCropX)), y = asNumber(t(p.WFImageCropY));
        const w = asNumber(t(p.WFImageCropWidth)), h = asNumber(t(p.WFImageCropHeight));
        if (!(img instanceof Img)) throw new Error('Crop without an image');
        if (w <= 0 || h <= 0) throw new Error(`Crop to ${w}x${h}`);
        return new Img(w, h, { op: 'crop', src: img, x, y });
      }
      case 'properties.images': {
        const img = v(p.WFInput);
        if (!(img instanceof Img)) throw new Error('Get Details of Images needs an image');
        const k = p.WFContentItemPropertyName;
        if (k === 'Height') return img.h;
        if (k === 'Width') return img.w;
        throw new Error(`image property ${k}`);
      }
      case 'image.mask': { const img = v(p.WFInput); if (!(img instanceof Img)) throw new Error('Mask without an image'); return new Img(img.w, img.h, { op: 'mask', src: img, mask: p.WFMaskType }); }
      case 'image.resize': { const img = v(p.WFImage); return new Img(asNumber(t(p.WFImageResizeWidth)), asNumber(t(p.WFImageResizeHeight)), { op: 'resize', src: img }); }
      case 'image.combine': {
        const list = (x => x == null ? [] : Array.isArray(x) ? x : [x])(v(p.WFInput));
        if (!list.length || !list.every(i => i instanceof Img)) throw new Error('Combine Images needs images');
        return new Img(Math.max(...list.map(i => i.w)), list.reduce((a, i) => a + i.h, 0), { op: 'combine', parts: list });
      }
      case 'overlayimageonimage': {
        const base = v(p.WFInput), over = v(p.WFImage);
        if (!(base instanceof Img) || !(over instanceof Img)) throw new Error('Overlay Image needs two images');
        // Overlay Image draws at the size it is given: anything else would stretch or squeeze the image.
        const ow = Math.round(asNumber(t(p.WFImageWidth))), oh = Math.round(asNumber(t(p.WFImageHeight)));
        if (ow !== over.w || oh !== over.h) throw new Error(`Overlay Image would resize ${over.w}x${over.h} to ${ow}x${oh}`);
        return new Img(base.w, base.h, { op: 'overlay', base, over, x: asNumber(t(p.WFImageX)), y: asNumber(t(p.WFImageY)) });
      }
      case 'overlaytext': {
        const base = v(p.WFImage);
        if (!(base instanceof Img)) throw new Error('Overlay Text needs an image');
        return new Img(base.w, base.h, { op: 'text', base, text: t(p.WFText), x: asNumber(v(p.WFTextX)), y: asNumber(v(p.WFTextY)), size: p.WFFontSize });
      }
      case 'output': throw new Stop(v(p.WFOutput));
      case 'exit': throw new Stop(null);
      case 'delay': d.advance(asNumber(v(p.WFDelayTime)) * 1000); return;
      case 'runworkflow': {
        const res = d.run(p.WFWorkflowName, v(p.WFInput), this.depth + 1);
        return res;
      }
      case 'wallpaper.set': {
        const img = v(p.WFInput);
        if (!(img instanceof Img)) throw new Error('Set Wallpaper needs an image');
        d.wallpapers.push({ at: d.clock, img }); return;
      }
      case 'recordaudio': {
        // Named the way iOS names recordings: "Audio Recording 2026-10-28 at 11.53.57 AM".
        const local = new Date(d.clock + d.tz * 60000), h = local.getUTCHours();
        const two = n => String(n).padStart(2, '0');
        const name = `Audio Recording ${formatDate(d.now(), 'yyyy-MM-dd', d.tz)} at ${h % 12 || 12}.${two(local.getUTCMinutes())}.${two(local.getUTCSeconds())} ${h < 12 ? 'AM' : 'PM'}.m4a`;
        return { kind: 'file', name, data: null, audio: true };
      }
      case 'sendmessage': {
        const content = v(p.WFSendMessageContent);
        d.sent.push({ at: d.clock, content });
        if (d.onSend) d.onSend(content);
        return;
      }
      case 'getitemname': { const x = v(p.WFInput); return (x && x.name ? x.name : asText(x)).replace(/\.[^.]+$/, ''); }
      case 'com.apple.ShortcutsActions.TranscribeAudioAction': {
        const x = v(p.audioFile), name = x.name.replace(/\.[^.]+$/, '');
        if (d.transcribeFails) throw new Error('Transcription failed');
        return d.transcripts.get(name) ?? '';
      }
      case 'com.apple.MobileSMS.MessageEntity': {
        if (d.findFails) throw new Error('Messages is not available right now');
        const f = p.WFContentItemFilter.Value.WFActionParameterFilterTemplates[0];
        const unit = { 16: 86400000, 32: 3600000, 64: 60000 }[f.Values.Unit];
        const since = d.clock - Number(f.Values.Number) * unit;
        let list = d.messages.filter(m => m.at >= since && m.indexedAt <= d.clock);
        if (d.limitSort) {
          list.sort((a, b) => b.at - a.at);
          if (p.WFContentItemLimitEnabled) list = list.slice(0, p.WFContentItemLimitNumber);
        }
        return list.map(m => d.entity(m));
      }
      default: throw new Error(`action ${id} is not simulated`);
    }
  }
}

/** Flattens a drawn image into what is on it: text lines and named images with their positions on the canvas,
 * clipped by crops (a text line counts as shown when its top is inside the visible area). */
export function flatten(img, x0 = 0, y0 = 0, clip = null, out = []) {
  if (!(img instanceof Img)) return out;
  const inClip = y => !clip || (y >= clip.y && y < clip.y + clip.h);
  switch (img.op) {
    case 'crop': {
      const c = { x: x0, y: y0, w: img.w, h: img.h };
      const both = clip ? { x: Math.max(c.x, clip.x), y: Math.max(c.y, clip.y), w: c.w, h: Math.min(c.y + c.h, clip.y + clip.h) - Math.max(c.y, clip.y) } : c;
      flatten(img.src, x0 - img.x, y0 - img.y, both, out); break;
    }
    case 'mask': case 'resize': flatten(img.src, x0, y0, clip, out); break;
    case 'combine': { let y = y0; for (const part of img.parts) { flatten(part, x0, y, clip, out); y += part.h; } break; }
    case 'overlay': flatten(img.base, x0, y0, clip, out); flatten(img.over, x0 + img.x, y0 + img.y, clip, out); break;
    case 'text': {
      flatten(img.base, x0, y0, clip, out);
      const pitch = img.size * 61.5 / 51;
      const lines = img.text.split('\n');
      const shown = lines.map((line, k) => ({ line, y: y0 + img.y + k * pitch })).filter(l => inClip(l.y));
      if (shown.length === lines.length) out.push({ text: img.text, x: x0 + img.x, y: y0 + img.y, size: img.size });
      else for (const l of shown) out.push({ text: l.line, x: x0 + img.x, y: l.y, size: img.size, partOf: img.text });
      break;
    }
    default: if (img.name && inClip(y0)) out.push({ image: img.name, x: x0, y: y0, w: img.w, h: img.h });
  }
  return out;
}
export { RS };
