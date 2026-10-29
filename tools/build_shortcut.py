#!/usr/bin/env python3
"""Builds the three unsigned shortcuts into <out-dir>; tools/build.sh signs them and copies them to iCloud.

    python3 build_shortcut.py <out-dir> [--explain] [--qa <folder>]

Hermes Chat Renderer keeps the chat (iCloud Drive › Shortcuts › Hermes/chat.json) and outputs the Lock Screen image,
but only when the chat changed (or when run with nothing). Its input:
  a Messages message           anything your agent sends: the Message automation's input; plain text works too
  "me-audio[<name>]: <words>"  you just sent the voice note <name> (from Talk to Hermes); the words are optional
  "me: <words>"                you said something (for testing, or your own shortcuts)
  "sync"                       read the newest messages in Messages and add whatever the chat is missing
  nothing, or a date           redraw (a time trigger may pass its date)
Hermes Lock Screen runs the renderer twice through one Set Wallpaper action: first with whatever started it, then with
"sync" when due. Overlapping runs take turns, and a read of Messages that never finished pauses reading from
automations for a while instead of failing every update. Talk to Hermes records a voice note, sends it, then
transcribes it.

Why sync: iOS only runs automations for messages you receive. Messages you send, from this iPhone or any other
device, reach the chat when your agent's next message arrives, and the same read repairs any update iOS skipped or
delivered late. Messages read this way are matched by the moment they were sent, so nothing is added twice and late
arrivals land in order; records added straight from a notification are confirmed (or corrected) the same way.

Speed: each message is drawn once, as row images saved in Hermes/rows, when it arrives. A redraw loads the rows on
screen, stacks them with one Combine Images, fades their top and lays them on the wall, so the full-screen work is a
single Overlay Image however long the chat is. Layout numbers come from design/tokens.json and assets/manifest.json
(made by tools/render_assets.swift).
"""
import json
import plistlib
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
T = json.loads((ROOT / 'design/tokens.json').read_text())
M = json.loads((ROOT / 'assets/manifest.json').read_text())
Z, B, TY, SYNC, TB, J, AU = T['zones'], T['bubble'], T['type'], T['sync'], T['tapback'], T['jumbo'], T['audio']

W = T['canvas']['width']
TOP, BOTTOM = Z['chatTop'], Z['chatBottom']
FADE_SPAN = Z['chatBottom'] - Z['fadeOpaque']   # how far up from Bottom rows can still show through the fade
TEXT_CUT = Z['textCut']                          # rows centred above this show their bubble without words
RIGHT = W - B['side']                            # your bubbles' right edge
CHARS, NARROWEST = B['chars'], 15                # wrap widths: normal, and the narrowest a retry goes
GAP_SAME, GAP_TURN = B['sameGap'] - B['tailRoom'], B['turnGap'] - B['tailRoom']
STAMP_ABOVE, STAMP_BELOW, STAMP_GAP = T['stamp']['above'], T['stamp']['below'], T['stamp']['gapMinutes']
STAMP_H = STAMP_ABOVE + TY['time']['pitch'] + STAMP_BELOW
RECEIPT_H = T['receipt']['gap'] + T['receipt']['height']
TAIL = M['tailBox']
KEEP, IDS = T['log']['keep'], T['log']['ids']
LINE_H = int(-(-TY['body']['pitch'] // 1)) + B['padTop'] + B['padBottom']   # a one-line bubble
AUDIO_TEXT_TOP = LINE_H - 18                     # a transcript starts just under the waveform
MAX_ROWS = 16                                    # more than ever fit between the clock and the flashlight row
FOLD_AT = 3                                      # older bubbles left outside the stack before they're folded into it
COL_MAX = FADE_SPAN + 320                        # the cached stack keeps this much: more than ever shows above a reply
HOLE_X, HOLE_Y = W, 100                          # the badge cutout's centre in tapback-hole.png
LIGHT_RE = r'(?i)^\s*(dawn|day|dusk|night)\s*$'
INSERT_LOOKBACK = 6                              # an out-of-order message is looked for among the newest records first
STATE_VERSION, RELEASE = '3', '2026-10-29d'
LOOK = '3'   # older rows are redrawn once: badges with a dark ring (before 2), long messages wrapped narrow (before 3)

RENDERER_NAME, WALLPAPER_NAME, SENDER_NAME = 'Hermes Chat Renderer', 'Hermes Lock Screen', 'Talk to Hermes'
DEFAULT_AGENT, HINT = 'Hermes', 'Hold the Action button to talk.'
DIR = 'Hermes'
QA = False


def configure(qa_dir=None, agent=None):
    """Production by default. A QA build (for testing on a Mac) reads and writes only `qa_dir`, ends every name in
    " QA", has the agent's name built in, and saves each Lock Screen image to the folder instead of setting it."""
    global RENDERER_NAME, WALLPAPER_NAME, SENDER_NAME, DIR, QA, DEFAULT_AGENT
    if qa_dir:
        RENDERER_NAME, WALLPAPER_NAME, SENDER_NAME = (f'{n} QA' for n in (RENDERER_NAME, WALLPAPER_NAME, SENDER_NAME))
        DIR, QA = qa_dir, True
        DEFAULT_AGENT = agent or DEFAULT_AGENT


ASSETS = {'Blank': 'fade-mask.png', 'Clear': 'clear.png', 'GapSame': 'gap-same.png', 'GapTurn': 'gap-turn.png',
          'ReceiptCanvas': 'receipt-canvas.png', 'StampCanvas': 'stamp-canvas.png', 'Veil': 'veil.png', 'Blue': 'blue.png',
          'TailLeft': 'tail-left.png', 'TailRight': 'tail-right.png', 'AudioMe': 'audio-me.png', 'AudioThem': 'audio-them.png',
          'TapbackMe': 'tapback-me.png', 'TapbackThem': 'tapback-them.png', 'Hole': 'tapback-hole.png'}
RS, FS = '␞', '␟'   # record and field separators
MARK = '␚'          # what if_matches turns a matching text into
# One record per bubble. ms orders the chat on one clock for every time zone; key names the message it came from
# ("m…" read from Messages, "p…" added from a notification and not yet confirmed); text is last, it may hold newlines.
FIELDS = ('role', 'id', 'key', 'ms', 'kind', 'src', 'fp', 'react', 'by', 'rowH', 'bx', 'bw', 'bh', 'day', 'time',
          'timeW', 'text')
# One message to add: key is "m" when it was read from Messages (its key becomes m + its time) or "p<now>" from a
# notification; ref is the time (WHEN) of the message a tapback is on.
LINE = ('key', 'when', 'day', 'time', 'peer', 'kind', 'ref', 'attach', 'body')
WHEN = 'yyyy D A xx'   # year, day of the year, milliseconds into the day, offset from UTC: pieces Calculate can read

# Hermes busy acks (⚡ ⏳ ⏩), "⏳ Working — N min" heartbeats and tool-progress lines like "💻 `ls`...".
STATUS_RE = r'^(?:⏳|⚡|⏩)|^[^\p{L}\p{N}\s]{1,4}\s[^\n]{0,120}(?:\.\.\.|…)$'
# Tapbacks reach the Message trigger as text, e.g. "Liked an attachment" or 'Reacted 👀 to “…”'.
TAPBACK_RE = (r'(?i)^(?:[^\n]{1,80}?\s+)?(?:Liked|Loved|Disliked|Laughed at|Emphasized|Questioned|Reacted \S{1,8} to|Removed an? \S{1,12} from) '
              r'(?:an? (?:attachment|image|photo|video|audio message|sticker|message)|“[\s\S]*”|"[\s\S]*")$')
TAPBACK_VERB_RE = (r'^(?:[^\n]{1,80}?\s+)?(Liked|Loved|Disliked|Laughed at|Emphasized|Questioned|Reacted|Removed)\b'
                   r'[\s\S]*$')
TAPBACK_EMOJI = {'Liked': '👍', 'Loved': '❤️', 'Disliked': '👎', 'Laughed at': '😂', 'Emphasized': '‼️',
                 'Questioned': '❓', 'Like': '👍', 'Love': '❤️', 'Dislike': '👎', 'Laugh': '😂',
                 'Emphasize': '‼️', 'Emphasis': '‼️', 'Question': '❓'}
NEW_CHAT_RE = r'^/(?:new|reset)$'
EMOJI_RE = r'\p{Extended_Pictographic}(?:\x{FE0F}|\x{200D}\p{Extended_Pictographic}\x{FE0F}?|[\x{1F3FB}-\x{1F3FF}])*'
JUMBO_RE = rf'^\s*(?:{EMOJI_RE}\s*){{1,{J["max"]}}}$'
AUDIO_RE = r'(?i)^Audio Recording|\.(?:m4a|caf|aac|amr|mp3|wav|opus)$'
IMAGE_RE = r'(?i)\.(?:jpe?g|heic|heif|png|gif|webp|tiff?)$'
VIDEO_RE = r'(?i)\.(?:mov|mp4|m4v)$'
CLEANUPS = [
    (r'\r\n?', '\n'),
    (r'\*\*|__|`', ''),                    # markdown emphasis and code
    (r'(?m)^#{1,6}[ \t]+', ''),            # headings
    (r'(?m)^[ \t]*[-*][ \t]+', '• '),      # list bullets
    (r'\n{3,}', '\n\n'),                   # at most one blank line
    (r'\.\.\.', '…'),
    (r'(^|[\s(\[{])"', '$1“'), (r'"', '”'),
    (r"(^|[\s(\[{])'", '$1‘'), (r"'", '’'),
]
MESSAGES_APP = {'TeamIdentifier': '0000000000', 'BundleIdentifier': 'com.apple.MobileSMS', 'Name': 'Messages',
                'AppIntentIdentifier': 'MessageEntity', 'ActionRequiresAppInstallation': True}

IS, BEGINS_WITH, CONTAINS, GREATER_THAN, LESS_THAN, HAS_VALUE, NO_VALUE = 4, 8, 99, 2, 0, 100, 101


def font(face):
    f = TY[face]
    return {'WFFontDescriptorName': f['font'], 'WFFontDescriptorFamily': f['family'], 'WFFontDescriptorFace': f['face'],
            'WFFontDescriptorVisibleName': f['family'] if f['face'] == 'Regular' else f"{f['family']} {f['face']}"}


def color(hex_rgb):
    r, g, b = (int(hex_rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return {'WFColorRepresentationType': 'WFColorRepresentationTypeCGColor',
            'redComponent': r, 'greenComponent': g, 'blueComponent': b, 'alphaComponent': 1.0}


INK, SENT_INK, STAMP = color(T['color']['ink']), color(T['color']['sentInk']), color(T['color']['stamp'])


def new_uuid():
    return str(uuid.uuid4()).upper()


def attachment(value):
    return {'Value': value, 'WFSerializationType': 'WFTextTokenAttachment'}


def token_string(*parts):
    """Text with inline variables; attachment ranges are UTF-16 offsets."""
    text, ranges = '', {}
    for part in parts:
        if isinstance(part, str):
            text += part
        else:
            ranges[f'{{{len(text.encode("utf-16-le")) // 2}, 1}}'] = part
            text += '￼'
    value = {'string': text}
    if ranges:
        value['attachmentsByRange'] = ranges
    return {'Value': value, 'WFSerializationType': 'WFTextTokenString'}


def variable(name, key=None):
    ref = {'Type': 'Variable', 'VariableName': name}
    if key:
        ref['Aggrandizements'] = [{'Type': 'WFDictionaryValueVariableAggrandizement', 'DictionaryKey': key}]
    return ref


def prop(ref, title, ident=None):
    """A property of a variable. Shortcuts resolves it by the name its editor shows (e.g. "Sender", not "author")."""
    agg = {'Type': 'WFPropertyVariableAggrandizement', 'PropertyName': title}
    if ident:
        agg['PropertyUserInfo'] = {'WFLinkEntityContentPropertyUserInfoPropertyIdentifier': ident}
    return {**ref, 'Aggrandizements': [agg]}


def shortcut_input(prop_name=None):
    ref = {'Type': 'ExtensionInput'}
    if prop_name:
        ref['Aggrandizements'] = [{'Type': 'WFPropertyVariableAggrandizement', 'PropertyName': prop_name}]
    return ref


def operand(value):
    return attachment(value) if isinstance(value, dict) else value


def as_text(value):
    """Text fields (image positions and sizes, file paths): a token string passes through, a variable is wrapped."""
    if isinstance(value, dict):
        return value if value.get('WFSerializationType') == 'WFTextTokenString' else token_string(value)
    return str(value)


class Shortcut:
    def __init__(self):
        self.actions = []
        self.quiet = False   # True: comments stay in this source only (each is an action Shortcuts steps through)

    def act(self, ident, params=None, output=None):
        """Appends an action and returns a reference to its output if `output` names it."""
        params = dict(params or {})
        ref = None
        if output:
            params['UUID'] = new_uuid()
            ref = {'Type': 'ActionOutput', 'OutputUUID': params['UUID'], 'OutputName': output}
        if not ident.startswith('com.'):
            ident = f'is.workflow.actions.{ident}'
        self.actions.append({'WFWorkflowActionIdentifier': ident, 'WFWorkflowActionParameters': params})
        return ref

    def comment(self, text):
        if not self.quiet:
            self.act('comment', {'WFCommentActionText': text})

    def set(self, name, value):
        self.act('setvariable', {'WFVariableName': name, 'WFInput': attachment(value)})

    def append(self, name, value):
        self.act('appendvariable', {'WFVariableName': name, 'WFInput': attachment(value)})

    def text(self, *parts):
        return self.act('gettext', {'WFTextActionText': token_string(*parts)}, 'Text')

    def set_text(self, name, *parts):
        self.set(name, self.text(*parts))

    def number(self, n):
        return self.act('number', {'WFNumberActionNumber': n}, 'Number')

    def set_number(self, name, n):
        self.set(name, self.number(n))

    def math(self, a, op, b):
        return self.act('math', {'WFInput': operand(a), 'WFMathOperation': op, 'WFMathOperand': operand(b)},
                        'Calculation Result')

    def round_up(self, value):
        return self.act('round', {'WFInput': operand(value), 'WFRoundMode': 'Always Round Up'}, 'Rounded Number')

    def round_(self, value):
        return self.act('round', {'WFInput': operand(value), 'WFRoundMode': 'Normal'}, 'Rounded Number')

    def replace(self, subject, pattern, replacement='', case_sensitive=False):
        """Regex replace; `pattern` and `replacement` may hold variables."""
        return self.act('text.replace', {'WFInput': token_string(subject), 'WFReplaceTextFind': as_text(pattern),
                                         'WFReplaceTextReplace': as_text(replacement),
                                         'WFReplaceTextRegularExpression': True,
                                         'WFReplaceTextCaseSensitive': case_sensitive}, 'Updated Text')

    def replace_literal(self, subject, find, replacement=''):
        """Plain replace (every occurrence); `find` and `replacement` may hold variables."""
        return self.act('text.replace', {'WFInput': token_string(subject), 'WFReplaceTextFind': as_text(find),
                                         'WFReplaceTextReplace': as_text(replacement),
                                         'WFReplaceTextRegularExpression': False,
                                         'WFReplaceTextCaseSensitive': True}, 'Updated Text')

    def cleanup(self, subject):
        for pattern, replacement in CLEANUPS:
            subject = self.replace(subject, pattern, replacement)
        return self.act('text.trimwhitespace', {'WFInput': token_string(subject)}, 'Updated Text')

    def lower(self, subject):
        return self.act('text.changecase', {'text': token_string(subject), 'WFCaseType': 'lowercase'}, 'Updated Text')

    def match(self, subject, pattern):
        return self.act('text.match', {'text': token_string(subject), 'WFMatchTextPattern': pattern,
                                       'WFMatchTextCaseSensitive': True}, 'Matches')

    def item(self, items, specifier, index=None):
        params = {'WFInput': attachment(items), 'WFItemSpecifier': specifier}
        if index is not None:
            params['WFItemIndex'] = operand(index)
        return self.act('getitemfromlist', params, 'Item from List')

    def count(self, value, kind='Characters'):
        return self.act('count', {'Input': attachment(value), 'WFCountType': kind}, 'Count')

    def dictionary(self, items):
        text = lambda v: v if isinstance(v, dict) and v.get('WFSerializationType') == 'WFTextTokenString' else token_string(v)
        fields = [{'WFItemType': 0, 'WFKey': token_string(k), 'WFValue': text(v)} for k, v in items]
        return self.act('dictionary', {'WFItems': {'Value': {'WFDictionaryFieldValueItems': fields},
                                                   'WFSerializationType': 'WFDictionaryFieldValue'}}, 'Dictionary')

    def value_for(self, dictionary, key):
        return self.act('getvalueforkey', {'WFInput': attachment(dictionary), 'WFGetDictionaryValueType': 'Value',
                                           'WFDictionaryKey': token_string(key)}, 'Dictionary Value')

    def file(self, path, required):
        return self.act('documentpicker.open', {'WFGetFilePath': as_text(path), 'WFFileErrorIfNotFound': required,
                                                'WFShowFilePicker': False}, 'File')

    def save(self, content, path):
        self.act('documentpicker.save', {'WFInput': attachment(content), 'WFAskWhereToSave': False,
                                         'WFFileDestinationPath': as_text(path), 'WFSaveFileOverwrite': True},
                 'Saved File')

    def now(self):
        return self.act('date', {'WFDateActionMode': 'Current Date'}, 'Date')

    def fmt(self, date, pattern):
        return self.act('format.date', {'WFDate': token_string(date), 'WFDateFormatStyle': 'Custom',
                                        'WFDateFormat': pattern}, 'Formatted Date')

    def short_time(self, date):
        t = self.act('format.date', {'WFDate': token_string(date), 'WFDateFormatStyle': 'None',
                                     'WFTimeFormatStyle': 'Short'}, 'Formatted Date')
        return self.replace(t, '[  ]', ' ')

    def if_(self, subject, condition, string=None, number=None):
        group = new_uuid()
        params = {'GroupingIdentifier': group, 'WFControlFlowMode': 0, 'WFCondition': condition,
                  'WFInput': {'Type': 'Variable', 'Variable': attachment(subject)}}
        if string is not None:
            params['WFConditionalActionString'] = string
        if number is not None:
            params['WFNumberValue'] = number
        self.act('conditional', params)
        return group

    def if_positive(self, value):
        return self.if_(value, GREATER_THAN, number=0)

    def if_nonempty(self, value, kind='Characters'):
        """Branches on length, since "has any value" treats an empty string as a value."""
        return self.if_positive(self.count(value, kind))

    def if_matches(self, subject, pattern):
        """Branches on whether `pattern` matches anywhere in `subject`. One Replace Text turns any text it matches
        into a marker, quicker than Match Text, whose matches would also need counting. A leading flag group
        stays in front."""
        flags = re.match(r'\(\?[imsx]+\)', pattern)
        head = flags.group(0) if flags else ''
        marked = self.replace(subject, f'{head}^[\\s\\S]*?(?:{pattern[len(head):]})[\\s\\S]*$', MARK, case_sensitive=True)
        return self.if_(marked, IS, string=MARK)

    def if_same(self, a, b):
        return self.if_(a, IS, string=token_string(b))

    def otherwise(self, group):
        self.act('conditional', {'GroupingIdentifier': group, 'WFControlFlowMode': 1})

    def end(self, group):
        self.act('conditional', {'GroupingIdentifier': group, 'WFControlFlowMode': 2, 'UUID': new_uuid()})

    def repeat(self, count):
        group = new_uuid()
        self.act('repeat.count', {'GroupingIdentifier': group, 'WFControlFlowMode': 0, 'WFRepeatCount': operand(count)})
        return group

    def end_repeat(self, group):
        self.act('repeat.count', {'GroupingIdentifier': group, 'WFControlFlowMode': 2, 'UUID': new_uuid()})

    def repeat_each(self, items):
        group = new_uuid()
        self.act('repeat.each', {'GroupingIdentifier': group, 'WFControlFlowMode': 0, 'WFInput': attachment(items)})
        return group

    def end_repeat_each(self, group):
        self.act('repeat.each', {'GroupingIdentifier': group, 'WFControlFlowMode': 2, 'UUID': new_uuid()})

    # Images. Every position and size is in pixels from the top-left.

    def crop(self, image, x, y, w, h):
        return self.act('image.crop', {'WFInput': attachment(image), 'WFImageCropPosition': 'Custom',
                                       'WFImageCropX': as_text(x), 'WFImageCropY': as_text(y),
                                       'WFImageCropWidth': as_text(w), 'WFImageCropHeight': as_text(h)}, 'Cropped Image')

    def mask_rounded(self, image, radius):
        return self.act('image.mask', {'WFInput': attachment(image), 'WFMaskType': 'Rounded Rectangle',
                                       'WFMaskCornerRadius': as_text(radius)}, 'Masked Image')

    def mask_ellipse(self, image):
        return self.act('image.mask', {'WFInput': attachment(image), 'WFMaskType': 'Ellipse'}, 'Masked Image')

    def mask_with(self, image, mask):
        return self.act('image.mask', {'WFInput': attachment(image), 'WFMaskType': 'Custom Image',
                                       'WFCustomMaskImage': attachment(mask)}, 'Masked Image')

    def combine(self, images):
        return self.act('image.combine', {'WFInput': attachment(images), 'WFImageCombineMode': 'Vertically',
                                          'WFImageCombineSpacing': 0}, 'Combined Image')

    def overlay(self, onto, image, x, y, w, h):
        """Overlay Image at its own size; returns the new image."""
        return self.act('overlayimageonimage', {
            'WFInput': attachment(onto), 'WFImage': attachment(image), 'WFShouldShowImageEditor': False,
            'WFImagePosition': 'Custom', 'WFImageX': as_text(x), 'WFImageY': as_text(y), 'WFImageWidth': as_text(w),
            'WFImageHeight': as_text(h), 'WFRotation': '0', 'WFOverlayImageOpacity': '100'}, 'Overlaid Image')

    def overlay_text(self, onto, text, x, y, face, color_, width=W, align='Left', size=None):
        """Overlay Text with its top-left at (x, y) in a box `width` wide; returns the new image."""
        return self.act('overlaytext', {
            'WFImage': attachment(onto), 'WFText': token_string(text),
            'WFSizingMethod': 'Absolute', 'WFTextPosition': 'Custom Position', 'WFTextX': operand(x),
            'WFTextY': operand(y), 'WFFont': font(face), 'WFFontSize': size or TY[face]['size'],
            'WFTextAlignment': align, 'WFTextColor': color_, 'WFTextOutlineEnabled': False,
            'WFTextBoxWidth': operand(width)}, 'Image with Text')


def field(s, record, name, fields=FIELDS):
    """One field of a record (or line); the last field may hold newlines."""
    index = fields.index(name)
    if index == len(fields) - 1:
        return s.replace(record, rf'^(?:[^{FS}]*{FS}){{{index}}}')
    return s.replace(record, rf'^(?:[^{FS}]*{FS}){{{index}}}([^{FS}]*){FS}[\s\S]*$', '$1')


def loop_var(name, depth):
    """Shortcuts names a loop's Repeat Item / Repeat Index by how deeply the loop is nested: 1 → plain, 2 → "… 2"."""
    return name if depth == 1 else f'{name} {depth}'


def regex_escape(s, value):
    return s.replace(value, r'([\\^$.|?*+()\[\]{}])', r'\\$1', case_sensitive=True)


def rec_pattern(**fixed):
    """A regex matching one whole record (with the separator before it); `fixed` pins fields to token parts."""
    parts = [f'(?:^|{RS})']
    for i, name in enumerate(FIELDS):
        if i:
            parts.append(FS)
        if name in fixed:
            value = fixed[name]
            parts.extend(value if isinstance(value, (list, tuple)) else [value])
        else:
            parts.append(f'[^{RS}]*' if name == 'text' else f'[^{FS}]*')
    return token_string(*parts)


def near_record(s, ms_name, before, after, depth, **fixed):
    """Near: the newest record matching `fixed` whose time is at most `before` ms earlier or `after` ms later than the
    variable `ms_name`, or empty text. For the few records a lookup like this sees (your voice notes). `depth` is how
    deeply its loop is nested."""
    s.set_text('Near', '')
    loop = s.repeat_each(s.match(variable('Log'), rec_pattern(**fixed)))
    s.set('NearRec', s.replace(s.text(variable(loop_var('Repeat Item', depth))), f'^{RS}'))
    s.set('NearGap', s.math(field(s, variable('NearRec'), 'ms'), '-', variable(ms_name)))
    g = s.if_(variable('NearGap'), LESS_THAN, number=after)
    g2 = s.if_(variable('NearGap'), GREATER_THAN, number=-before)
    s.set('Near', variable('NearRec'))
    s.end(g2)
    s.end(g)
    s.end_repeat_each(loop)


def find_record(s, which, **fixed):
    """The first or last record with the given fields, without its separator, or empty text."""
    found = s.item(s.match(variable('Log'), rec_pattern(**fixed)), which)
    return s.replace(s.text(found), f'^{RS}')


def fingerprint(s, text):
    """Lower case, no spaces, first 48 characters: the same words give the same print however they were wrapped."""
    return s.replace(s.replace(s.lower(text), r'\s+'), r'^(.{48}).+$', '$1')


def name_key(s, text):
    """Letters and digits only, lower case: "Hermes Jr." and "hermes jr" are the same name."""
    return s.replace(s.lower(text), r'[^\p{L}\p{N}]+')


def abs_ms(s, when, name):
    """Milliseconds on one clock for every time zone, from WHEN text ("2026 301 53913543 -0400": year, day of the
    year, milliseconds into the day, UTC offset), counted from 2020 with 366-day years (a year's end leaves a
    harmless gap). One Calculate Expression does the arithmetic; the offset's digits go in one by one, so no number
    has a leading zero."""
    expr = s.replace(when, r'^(\d+) (\d+) (\d+) ([+-])(\d)(\d)(\d)(\d)$',
                     r'((($1-2020)*366+$2)*86400000+$3-(0$41)*(($5*10+$6)*3600000+($7*10+$8)*60000))')
    s.set(name, s.act('calculateexpression', {'Input': token_string(expr)}, 'Calculation Result'))


def measure(s, subject, depth, keep=False):
    """Measures text the way the renderer can: each character becomes its width in marks (1/100 em of Helvetica
    Neue), then each line's marks are counted. Sets Units to the widest line's count, and with `keep` collects every
    line's count in Lens. `depth` is how deeply this measuring loop is nested (1 when not inside another loop)."""
    marks = lambda n: M['mark'] * n
    u = s.replace(subject, M['widePattern'], marks(M['wideUnits']), case_sensitive=True)
    for c in M['widthClasses']:
        u = s.replace(u, c['pattern'], marks(c['units']), case_sensitive=True)
    u = s.replace(u, f"[^{M['mark']}\\n]", marks(M['otherUnits']), case_sensitive=True)
    s.set_number('Units', 0)
    if keep:
        s.set('Lens', s.act('nothing', {}, 'Nothing'))
    loop = s.repeat_each(s.match(u, f"{M['mark']}+"))
    n = s.count(variable(loop_var('Repeat Item', depth)))
    if keep:
        s.append('Lens', n)
    g = s.if_positive(s.math(n, '-', variable('Units')))
    s.set('Units', n)
    s.end(g)
    s.end_repeat_each(loop)


def wrap(s, source, chars_var):
    """Wraps `source` at the width held in `chars_var` into Wrapped, and its line count into Lines."""
    c = variable(chars_var)
    pattern = token_string('([^\\n]{1,', c, '})(?:[ \\t]*(?:\\n|$)|[ \\t]+)|(\\S{', c, '})')
    s.set('Wrapped', s.replace(s.replace(source, pattern, '$1$2\n'), r'\n+$'))
    s.set('Lines', s.math(s.count(s.match(variable('Wrapped'), r'\n'), 'Items'), '+', 1))


def wrap_paragraph(s, source):
    """Wrap at Chars, re-wrap narrower if the last line is a lone short word, and cap the lines with an ellipsis."""
    wrap(s, source, 'Chars')
    s.comment('A single short word on the last line reads as a mistake: re-wrap narrower if that keeps the line count.')
    g = s.if_positive(s.math(variable('Lines'), '-', 1))
    short = s.count(s.item(s.match(variable('Wrapped'), r'[^\n]*$'), 'First Item'))
    g2 = s.if_positive(s.math(B['widowChars'], '-', short))
    s.set('Before', variable('Wrapped'))
    s.set('BeforeLines', variable('Lines'))
    s.set('Narrower', s.math(variable('Chars'), '-', B['widowStep']))
    wrap(s, source, 'Narrower')
    g3 = s.if_positive(s.math(variable('Lines'), '-', variable('BeforeLines')))
    s.set('Wrapped', variable('Before'))
    s.set('Lines', variable('BeforeLines'))
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_(variable('Lines'), GREATER_THAN, number=B['maxLines'])
    head = s.item(s.match(variable('Wrapped'), rf"^(?:[^\n]*\n){{{B['maxLines'] - 1}}}[^\n]*"), 'First Item')
    s.set_text('Wrapped', s.replace(head, r'[\s,.;:—-]+$'), '…')
    s.set_number('Lines', B['maxLines'])
    s.end(g)


def fit_text(s, source, depth):
    """Wraps and measures `source` into Wrapped, Lines and TextW. When wide letters overfill a line, it wraps again
    narrower by just the share the widest line overflowed, so a long message stays as wide as a bubble can be.
    `depth` is the depth of the retry loop."""
    s.set_number('Chars', CHARS)
    s.set_number('Fits', 0)
    loop = s.repeat(4)
    g = s.if_positive(variable('Fits'))
    s.otherwise(g)
    wrap_paragraph(s, source)
    measure(s, variable('Wrapped'), depth=depth + 1)
    s.set('TextPx', s.math(variable('Units'), '×', M['pxPerUnit']))
    g2 = s.if_positive(s.math(variable('TextPx'), '-', B['maxText']))
    s.set('Chars', s.act('round', {'WFInput': operand(s.math(s.math(variable('Chars'), '×', B['maxText']), '÷',
                                                              variable('TextPx'))),
                                   'WFRoundMode': 'Always Round Down'}, 'Rounded Number'))
    g3 = s.if_(variable('Chars'), LESS_THAN, number=NARROWEST)
    s.set_number('Chars', NARROWEST)
    s.end(g3)
    s.otherwise(g2)
    s.set_number('Fits', 1)
    s.end(g2)
    s.end(g)
    s.end_repeat(loop)
    s.set('TextW', s.round_up(variable('TextPx')))
    s.set('TextH', s.round_up(s.math(variable('Lines'), '×', TY['body']['pitch'])))


def by_role(s, mine, theirs):
    """Runs `mine()` when the record being drawn is yours, `theirs()` otherwise."""
    g = s.if_(variable('Role'), IS, string='me')
    mine()
    s.otherwise(g)
    theirs()
    s.end(g)


def row_path(*parts):
    return token_string(f'{DIR}/rows/', *parts, '.png')


def need(s, name):
    """Loads one image from the folder into its variable, the first time this run needs it."""
    g = s.if_(variable(name), HAS_VALUE)
    s.otherwise(g)
    s.set(name, s.file(f'{DIR}/{ASSETS[name]}', True))
    s.end(g)


def height(s, image):
    """An image's height in pixels, as a number."""
    return s.math(s.act('properties.images', {'WFInput': attachment(image), 'WFContentItemPropertyName': 'Height'},
                        'Height'), '+', 0)


def render_row(s, depth):
    """Draws the bubble for Role, Kind, Text and React into rows/<Id>.png (its tail is added when it is stacked). A
    text bubble wraps its words; an audio bubble shows the waveform with any transcript under it; up to three emoji alone are drawn
    large with no bubble; a tapback badge sits on the top corner. Sets BY, BX, BW, BH and RowH. `depth` is the depth
    of this function's retry loop."""
    s.set('TR0', ms_now(s))
    need(s, 'Clear')
    s.set_number('BY', 0)
    g = s.if_nonempty(variable('React'))
    s.set_number('BY', TB['room'])
    s.end(g)
    s.set_number('Jumbo', 0)
    g = s.if_(variable('Kind'), IS, string='t')
    g2 = s.if_matches(variable('Text'), JUMBO_RE)
    s.set_number('Jumbo', 1)
    s.end(g2)
    s.end(g)

    s.comment('Wrap and measure the words once: a text bubble’s, or a voice note’s transcript.')
    s.set_number('Words', 0)
    g = s.if_nonempty(variable('Text'))
    s.set_number('Words', 1)
    s.end(g)
    g = s.if_positive(variable('Jumbo'))
    s.set_number('Words', 0)
    s.end(g)
    g = s.if_positive(variable('Words'))
    fit_text(s, variable('Text'), depth)
    s.end(g)
    s.set('TR1', ms_now(s))

    g_a = s.if_(variable('Kind'), IS, string='a')
    s.comment('A voice note: the waveform, then any transcript under it in the same bubble.')
    s.set_number('BW', AU['width'])
    s.set_number('BH', LINE_H)
    g = s.if_positive(variable('Words'))
    s.set('BH', s.math(s.math(variable('TextH'), '+', AUDIO_TEXT_TOP), '+', B['padBottom']))
    g2 = s.if_positive(s.math(s.math(variable('TextW'), '+', 2 * B['padX']), '-', AU['width']))
    s.set('BW', s.math(variable('TextW'), '+', 2 * B['padX']))
    s.end(g2)
    s.end(g)
    s.otherwise(g_a)
    g_j = s.if_positive(variable('Jumbo'))
    s.comment('Up to three emoji alone are drawn large, with no bubble, as Messages does.')
    s.set('BW', s.math(s.count(s.match(variable('Text'), EMOJI_RE), 'Items'), '×', M['jumboPxPerEmoji']))
    s.set_number('BH', J['pitch'] + J['padTop'] + J['padBottom'])
    s.otherwise(g_j)
    s.set('BW', s.math(variable('TextW'), '+', 2 * B['padX']))
    s.set('BH', s.math(variable('TextH'), '+', B['padTop'] + B['padBottom']))
    s.end(g_j)
    s.end(g_a)
    by_role(s, lambda: s.set('BX', s.math(RIGHT, '-', variable('BW'))), lambda: s.set_number('BX', B['side']))
    s.set('RowH', s.math(s.math(variable('BY'), '+', variable('BH')), '+', B['tailRoom']))
    s.set('Row', s.crop(variable('Clear'), 0, 0, W, variable('RowH')))

    g_j = s.if_positive(variable('Jumbo'))
    s.set('Row', s.overlay_text(variable('Row'), variable('Text'), variable('BX'),
                                s.math(variable('BY'), '+', J['padTop']), 'body', INK, size=J['size']))
    s.otherwise(g_j)

    def bubble(plate, glyphs, ink):
        need(s, plate)
        shape = s.mask_rounded(s.crop(variable(plate), 0, 0, variable('BW'), variable('BH')), B['radius'])
        s.set('Row', s.overlay(variable('Row'), shape, variable('BX'), variable('BY'), variable('BW'), variable('BH')))
        g = s.if_(variable('Kind'), IS, string='a')
        need(s, glyphs)
        s.set('Row', s.overlay(variable('Row'), variable(glyphs), variable('BX'), variable('BY'), AU['width'], LINE_H))
        g2 = s.if_positive(variable('Words'))
        s.set('Row', s.overlay_text(variable('Row'), variable('Wrapped'), s.math(variable('BX'), '+', B['padX']),
                                    s.math(variable('BY'), '+', AUDIO_TEXT_TOP), 'body', ink))
        s.end(g2)
        s.otherwise(g)
        s.set('Row', s.overlay_text(variable('Row'), variable('Wrapped'), s.math(variable('BX'), '+', B['padX']),
                                    s.math(variable('BY'), '+', B['padTop']), 'body', ink))
        s.end(g)
    by_role(s, lambda: bubble('Blue', 'AudioMe', SENT_INK), lambda: bubble('Veil', 'AudioThem', INK))
    s.end(g_j)

    s.comment('A tapback sits on the bubble’s top corner toward the middle of the screen: their reactions on your '
              'bubbles in grey, yours on theirs in blue. Where it overlaps the bubble a thin gap is cut, so the wall '
              'shows between them, as the chat background does in Messages.')
    g = s.if_nonempty(variable('React'))
    tb = M['tapback']

    def place(centre_x, badge, anchor_x):
        need(s, badge)
        s.set('BadgeCX', centre_x)
        s.set('BadgeX', s.math(variable('BadgeCX'), '-', anchor_x))
        s.set('Badge', variable(badge))
    by_role(s, lambda: place(s.math(variable('BX'), '+', TB['inset']), 'TapbackThem', tb['anchorX']),
            lambda: place(s.math(s.math(variable('BX'), '+', variable('BW')), '-', TB['inset']), 'TapbackMe',
                          tb['w'] - tb['anchorX']))
    s.set('BadgeCY', s.math(variable('BY'), '+', TB['drop']))
    need(s, 'Hole')
    s.set('Row', s.mask_with(variable('Row'), s.crop(variable('Hole'), s.math(HOLE_X, '-', variable('BadgeCX')),
                                                     s.math(HOLE_Y, '-', variable('BadgeCY')), W, variable('RowH'))))
    s.set('Row', s.overlay(variable('Row'), variable('Badge'), variable('BadgeX'),
                           s.math(variable('BadgeCY'), '-', tb['anchorY']), tb['w'], tb['h']))
    s.set('Row', s.overlay_text(variable('Row'), variable('React'), s.round_(s.math(variable('BadgeCX'), '+', tb['emojiDX'])),
                                s.round_(s.math(variable('BadgeCY'), '+', tb['emojiDY'])), 'body', INK,
                                size=TB['emoji']))
    s.end(g)
    s.set('TR2', ms_now(s))
    s.save(variable('Row'), row_path(variable('Id')))
    s.set_text('RowPerf', ' (fit ', s.math(variable('TR1'), '-', variable('TR0')), ', draw ',
               s.math(variable('TR2'), '-', variable('TR1')), ', save ', s.math(ms_now(s), '-', variable('TR2')), ')')
    s.comment('Kept in memory too: the redraw that follows uses it without reading the file back.')
    s.set('LastRow', variable('Row'))
    s.set('LastRowId', variable('Id'))


def render_stamp(s, depth):
    """The timestamp that opens a message after a quiet spell (weekday in medium, time in regular, centred), saved
    as rows/<Id>-s.png and kept in StampImg. Drawn the first time it shows. `depth` is the depth of the measuring
    loop."""
    need(s, 'StampCanvas')
    measure(s, s.text(variable('Day'), '\n', variable('Time')), depth=depth, keep=True)
    s.set('DayW', s.math(s.math(s.item(variable('Lens'), 'First Item'), '×', M['smallPxPerUnit']), '×', M['mediumScale']))
    s.set('TimeW', s.math(s.item(variable('Lens'), 'Last Item'), '×', M['smallPxPerUnit']))
    s.set('DayX', s.round_(s.math(s.math(s.math(s.math(W, '-', variable('DayW')), '-', M['smallSpace']), '-',
                                         variable('TimeW')), '÷', 2)))
    stamp = variable('StampCanvas')
    stamp = s.overlay_text(stamp, variable('Day'), variable('DayX'), STAMP_ABOVE, 'day', STAMP)
    stamp = s.overlay_text(stamp, variable('Time'),
                           s.math(s.math(variable('DayX'), '+', variable('DayW')), '+', M['smallSpace']),
                           STAMP_ABOVE, 'time', STAMP)
    s.set('StampImg', stamp)
    s.save(variable('StampImg'), row_path(variable('Id'), '-s'))


# The chat as a log of records.

def record_text(s, **override):
    """A record from the variables of the same names (Role, Id, Key, …), with some fields given directly."""
    names = {'role': 'Role', 'id': 'Id', 'key': 'Key', 'ms': 'Ms', 'kind': 'Kind', 'src': 'Src', 'fp': 'Fp',
             'react': 'React', 'by': 'BY', 'rowH': 'RowH', 'bx': 'BX', 'bw': 'BW', 'bh': 'BH', 'day': 'Day',
             'time': 'Time', 'timeW': 'TimeW', 'text': 'Text'}
    parts = []
    for i, name in enumerate(FIELDS):
        if i:
            parts.append(FS)
        parts.append(override.get(name, variable(names[name])))
    return s.text(*parts)


def read_record(s, record):
    """Loads a record's fields into the variables of the same names."""
    names = {'role': 'Role', 'id': 'Id', 'key': 'Key', 'ms': 'Ms', 'kind': 'Kind', 'src': 'Src', 'fp': 'Fp',
             'react': 'React', 'by': 'BY', 'rowH': 'RowH', 'bx': 'BX', 'bw': 'BW', 'bh': 'BH', 'day': 'Day',
             'time': 'Time', 'timeW': 'TimeW', 'text': 'Text'}
    for name in FIELDS:
        s.set(names[name], field(s, record, name))


def queue(s, flag):
    """Asks for Key's rows to be drawn before the redraw: n = a new record (with its timestamp), r = redraw it."""
    g = s.if_nonempty(s.match(variable('Jobs'), token_string(FS, variable('Key'), RS)), 'Items')
    s.otherwise(g)
    s.set_text('Jobs', variable('Jobs'), flag, FS, variable('Key'), RS)
    s.end(g)
    changed(s)


def trace(s, *label, keep=False):
    """QA builds only: note how far the run got and when (seconds.milliseconds), kept in memory and saved to
    qa-trace-<mode>.txt at the end, so timing isn't skewed by iCloud writes. A debug build also saves it at each
    `keep` milestone, so a run that iOS ends still shows how far it got."""
    if QA:
        s.set_text('Trace', variable('Trace'), s.fmt(s.now(), 'mm:ss.SSS'), ' ', *label, '\n')
    if keep and QA == 'debug':
        s.save(variable('Trace'), token_string(f'{DIR}/qa-trace-', variable('Mode'), '.txt'))


def save_trace(s):
    if QA:
        s.save(s.text(variable('Trace'), s.fmt(s.now(), 'mm:ss.SSS'), ' end'), token_string(f'{DIR}/qa-trace-', variable('Mode'), '.txt'))


def changed(s):
    """The chat looks different: save it and redraw."""
    s.set_number('Changed', 1)
    s.set_number('Dirty', 1)


def has_key(s, key):
    return s.count(s.match(variable('Log'), token_string(FS, key, FS)), 'Items')


def preceding(s, record):
    """The record just before `record` in Log (empty text when it is the first)."""
    pattern = token_string(f'^[\\s\\S]*?([^{RS}]*){RS}', regex_escape(s, record), f'(?:{RS}[\\s\\S]*)?$')
    return s.replace(s.text(RS, variable('Log')), pattern, '$1', case_sensitive=True)


def following(s, record):
    """The record just after `record` in Log (empty text when it is the last)."""
    pattern = token_string(f'^(?:[\\s\\S]*?{RS})?', regex_escape(s, record), f'{RS}([^{RS}]*)[\\s\\S]*$')
    found = s.replace(s.text(variable('Log'), RS), pattern, '$1', case_sensitive=True)
    return s.replace(found, f'^[\\s\\S]*{RS}$')


def remove_record(s, record):
    s.set('Log', s.replace(s.replace_literal(s.text(RS, variable('Log'), RS), token_string(RS, record, RS), RS),
                           f'^{RS}+|{RS}+$'))


def insert_record(s, record, depth):
    """Puts `record` (its ms in Ms) in time order: after the last record when it is newest, as almost always;
    otherwise just after the newest of the last few that are older; failing that, by walking the whole log."""
    g = s.if_nonempty(variable('Log'))
    last = s.item(s.match(variable('Log'), f'[^{RS}]+'), 'Last Item')
    g2 = s.if_positive(s.math(field(s, last, 'ms'), '-', variable('Ms')))
    s.set('Recs0', s.match(variable('Log'), f'[^{RS}]+'))
    s.set('K0', s.count(variable('Recs0'), 'Items'))
    s.set_number('Placed', 0)
    loop = s.repeat(INSERT_LOOKBACK)
    g3 = s.if_positive(variable('Placed'))
    s.otherwise(g3)
    s.set('K0', s.math(variable('K0'), '-', 1))
    g4 = s.if_positive(variable('K0'))
    anchor = s.text(s.item(variable('Recs0'), 'Item At Index', variable('K0')))
    s.set('Anchor', anchor)
    g5 = s.if_positive(s.math(field(s, variable('Anchor'), 'ms'), '-', variable('Ms')))
    s.otherwise(g5)
    s.set('Log', s.replace_literal(variable('Log'), s.text(variable('Anchor'), RS),
                                   s.text(variable('Anchor'), RS, record, RS)))
    s.set_number('Placed', 1)
    s.end(g5)
    s.end(g4)
    s.end(g3)
    s.end_repeat(loop)
    g3 = s.if_positive(variable('Placed'))
    s.otherwise(g3)
    s.set_text('Rebuilt', '')
    loop = s.repeat_each(s.match(variable('Log'), f'[^{RS}]+'))
    each = variable(loop_var('Repeat Item', depth))
    g4 = s.if_positive(variable('Placed'))
    s.otherwise(g4)
    g5 = s.if_positive(s.math(field(s, each, 'ms'), '-', variable('Ms')))
    s.set_text('Rebuilt', variable('Rebuilt'), record, RS)
    s.set_number('Placed', 1)
    s.end(g5)
    s.end(g4)
    s.set_text('Rebuilt', variable('Rebuilt'), each, RS)
    s.end_repeat_each(loop)
    s.set('Log', s.replace(variable('Rebuilt'), f'{RS}+$'))
    s.end(g3)
    s.otherwise(g2)
    s.set_text('Log', variable('Log'), RS, record)
    s.end(g2)
    s.otherwise(g)
    s.set_text('Log', record)
    s.end(g)


def alloc_id(s, depth):
    """A row-file number no record uses (there are more numbers than records, so one is always free)."""
    s.set('Cand', variable('NextId'))
    s.set_number('Free', 1)
    used = s.match(variable('Log'), token_string(f'(?:^|{RS})[^{FS}]*{FS}', variable('Cand'), FS))
    g = s.if_nonempty(used, 'Items')
    s.set_number('Free', 0)
    s.end(g)
    g0 = s.if_positive(variable('Free'))
    s.otherwise(g0)
    loop = s.repeat(8)   # ids run in a cycle, so the next is almost always free; a few tries cover the rest
    g = s.if_positive(variable('Free'))
    s.otherwise(g)
    used = s.match(variable('Log'), token_string(f'(?:^|{RS})[^{FS}]*{FS}', variable('Cand'), FS))
    g2 = s.if_nonempty(used, 'Items')
    s.set('Cand', s.math(variable('Cand'), '+', 1))
    g3 = s.if_(variable('Cand'), GREATER_THAN, number=IDS - 1)
    s.set_number('Cand', 0)
    s.end(g3)
    s.otherwise(g2)
    s.set_number('Free', 1)
    s.end(g2)
    s.end(g)
    s.end_repeat(loop)
    s.end(g0)
    s.set('Id', variable('Cand'))
    s.set('NextId', s.math(variable('Cand'), '+', 1))
    g = s.if_(variable('NextId'), GREATER_THAN, number=IDS - 1)
    s.set_number('NextId', 0)
    s.end(g)


def clear_chat(s, since):
    s.set_text('Log', '')
    s.set_text('Status', '')
    s.set('Since', since)
    s.set_number('ColDirty', 1)
    changed(s)


# Adding messages.

def tapback_emoji(s, body, kind):
    """The emoji a reaction shows: from its text ("Liked “…”", "Reacted 🔥 to “…”"), else from its Reaction name.
    "Removed …" gives no emoji (the badge goes)."""
    s.set_text('Emoji', '')
    table = s.dictionary(list(TAPBACK_EMOJI.items()))
    verb = s.replace(body, TAPBACK_VERB_RE, '$1')
    s.set('Emoji', s.text(s.value_for(table, verb)))
    g = s.if_(verb, IS, string='Reacted')
    s.set('Emoji', s.replace(body, r'^(?:[^\n]{1,80}?\s+)?Reacted\s+(\S+)\s+to[\s\S]*$', '$1'))
    s.end(g)
    g = s.if_(verb, IS, string='Removed')
    s.set_text('Emoji', '')
    s.otherwise(g)
    g2 = s.if_nonempty(variable('Emoji'))
    s.otherwise(g2)
    s.set('Emoji', s.text(s.value_for(table, s.replace(kind, r'^[^/]*/'))))
    s.end(g2)
    s.end(g)


def set_react(s, record):
    """Gives `record` the badge in Emoji (none when empty) and redraws it if that changed it."""
    g = s.if_same(field(s, record, 'react'), variable('Emoji'))
    s.otherwise(g)
    read_record(s, record)
    s.set('React', variable('Emoji'))
    s.set('Log', s.replace_literal(variable('Log'), record, record_text(s)))
    queue(s, 'r')
    s.end(g)


def add_message(s, depth):
    """Adds Body as one bubble (key KeyBase-1) for Role and Kind at Ms; blank lines stay inside it, as in Messages.
    When the message was read from Messages (Confirmed), a record added from a notification moments ago with the
    same words, or the same voice note, takes the confirmed key and time instead; it is redrawn only if Messages has
    its words differently or its place in the chat moved. `depth` is the depth of the loops this adds."""
    s.set('Text', s.act('text.trimwhitespace', {'WFInput': token_string(variable('Body'))}, 'Updated Text'))
    s.set_text('Key', variable('KeyBase'), '-1')
    s.set('React', variable('FirstReact'))
    s.set('Fp', variable('FpOverride'))
    g = s.if_nonempty(variable('Fp'))
    s.otherwise(g)
    s.set('Fp', fingerprint(s, variable('Text')))
    s.end(g)
    s.set_text('Prov', '')
    g = s.if_positive(variable('Confirmed'))
    g2 = s.if_nonempty(variable('Src'))
    s.set('Prov', find_record(s, 'First Item', role=variable('Role'), key=f'p[^{FS}]*',
                              src=regex_escape(s, variable('Src'))))
    s.end(g2)
    g2 = s.if_nonempty(variable('Prov'))
    s.otherwise(g2)
    s.set('Prov', find_record(s, 'First Item', role=variable('Role'), key=f'p[^{FS}]*',
                              fp=regex_escape(s, variable('Fp'))))
    s.end(g2)
    s.end(g)
    g = s.if_nonempty(variable('Prov'))
    s.comment('Confirm the record added from the notification: same row, the confirmed key and time.')
    for name in ('Key', 'Ms', 'Kind', 'Text', 'Src'):
        s.set(f'New{name}', variable(name))
    read_record(s, variable('Prov'))
    s.comment('A redraw already asked for (a new look, say) follows the new key too.')
    s.set('Jobs', s.replace_literal(variable('Jobs'), token_string(FS, variable('Key'), RS),
                                    token_string(FS, variable('NewKey'), RS)))
    g2 = s.if_same(variable('Key'), variable('ColKey'))
    s.comment('The stack of older bubbles ends with this one: it follows the new key.')
    s.set('ColKey', variable('NewKey'))
    s.set('ColMs', s.math(variable('NewMs'), '+', 0))
    s.end(g2)
    s.set('Key', variable('NewKey'))
    s.set('Ms', variable('NewMs'))
    g2 = s.if_same(variable('Kind'), variable('NewKind'))
    g3 = s.if_(variable('Kind'), IS, string='a')
    s.comment('A voice note keeps the transcript the notification brought; Messages has none.')
    s.otherwise(g3)
    g4 = s.if_same(variable('Text'), variable('NewText'))
    s.otherwise(g4)
    s.set('Text', variable('NewText'))
    queue(s, 'r')
    s.end(g4)
    s.end(g3)
    s.otherwise(g2)
    s.set('Kind', variable('NewKind'))
    s.set('Text', variable('NewText'))
    s.set('Src', variable('NewSrc'))
    queue(s, 'r')
    s.end(g2)
    s.set('Rec', record_text(s))
    s.set('Adopted', s.math(variable('Adopted'), '+', 1))
    s.set_number('Dirty', 1)
    s.comment('Its confirmed time almost always keeps it between the same neighbours: then it changes in place. '
              'Otherwise it moves, and the chat is redrawn.')
    s.set_number('InPlace', 1)
    s.set('Before', preceding(s, variable('Prov')))
    g2 = s.if_nonempty(variable('Before'))
    g3 = s.if_positive(s.math(field(s, variable('Before'), 'ms'), '-', variable('Ms')))
    s.set_number('InPlace', 0)
    s.end(g3)
    s.end(g2)
    s.set('After', following(s, variable('Prov')))
    g2 = s.if_nonempty(variable('After'))
    g3 = s.if_positive(s.math(variable('Ms'), '-', field(s, variable('After'), 'ms')))
    s.set_number('InPlace', 0)
    s.end(g3)
    s.end(g2)
    g2 = s.if_positive(variable('InPlace'))
    s.set('Log', s.replace_literal(variable('Log'), variable('Prov'), variable('Rec')))
    s.otherwise(g2)
    remove_record(s, variable('Prov'))
    insert_record(s, variable('Rec'), depth)
    changed(s)
    s.set_number('ColDirty', 1)
    s.end(g2)
    s.otherwise(g)
    alloc_id(s, depth)
    s.set('Rec', record_text(s, by='0', rowH='0', bx='0', bw='0', bh='0', timeW='0'))
    queue(s, 'n')
    s.set('Added', s.math(variable('Added'), '+', 1))
    insert_record(s, variable('Rec'), depth)
    s.end(g)


def add_line(s, depth):
    """Adds one message (Line, in LINE fields): a reaction gives its bubble a badge, a status line keeps the typing
    bubble, anything else becomes bubbles. Messages already in the chat, or older than Since, are skipped."""
    for name, var in (('key', 'KeyBase'), ('when', 'When'), ('day', 'Day'), ('time', 'Time'), ('kind', 'Type'),
                      ('ref', 'Ref'), ('attach', 'Attach'), ('body', 'Raw')):
        s.set(var, field(s, variable('Line'), name, LINE))
    s.set('Peer', s.math(field(s, variable('Line'), 'peer', LINE), '+', 0))   # a number, so If can compare it
    abs_ms(s, variable('When'), 'Ms')
    s.set_number('Unsure', 0)
    g = s.if_(variable('Peer'), LESS_THAN, number=0)
    s.comment('Read from Messages without a sender (iOS 26). Your agent’s words reach the chat first, from their '
              'notifications, and its status lines are its own; other words are yours. Words from before the chat '
              'began have no notification to go by, so they are left out. A reaction is settled by the bubble it is '
              'on.')
    g2 = s.if_matches(variable('Type'), r'Reaction|^[^/]*/.+$')
    s.otherwise(g2)
    s.set_number('Peer', 0)
    g3 = s.if_matches(variable('Raw'), STATUS_RE)
    s.set_number('Peer', 1)
    s.otherwise(g3)
    g4 = s.if_nonempty(find_record(s, 'First Item', role='h',
                                   fp=regex_escape(s, fingerprint(s, s.cleanup(variable('Raw'))))))
    s.set_number('Peer', 1)
    s.otherwise(g4)
    g5 = s.if_(s.math(variable('Ms'), '-', variable('ChatStart')), LESS_THAN, number=0)
    s.set_number('Unsure', 1)
    s.end(g5)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)
    s.set_number('Confirmed', 1)
    g = s.if_(variable('KeyBase'), BEGINS_WITH, string='p')
    s.set_number('Confirmed', 0)
    s.otherwise(g)
    s.comment('A message read from Messages is known by the moment it was sent: unique, the same in every time '
              'zone, and unchanged if it is edited.')
    s.set_text('KeyBase', 'm', variable('Ms'))
    s.end(g)
    s.set_number('Fresh', 1)
    g = s.if_positive(variable('Confirmed'))
    g2 = s.if_positive(s.math(variable('Ms'), '-', variable('Since')))
    s.otherwise(g2)
    s.set_number('Fresh', 0)
    s.end(g2)
    g2 = s.if_positive(variable('Unsure'))
    s.set_number('Fresh', 0)
    s.end(g2)
    g2 = s.if_positive(has_key(s, s.text(variable('KeyBase'), '-1')))
    s.set_number('Fresh', 0)
    s.comment('Already in the chat. If a notification added it again (its automation ran late), drop that copy.')
    g3 = s.if_matches(variable('Log'), f'{FS}p[0-9]')
    g4 = s.if_matches(variable('Type'), r'Reaction|^[^/]*/.+$')
    s.otherwise(g4)
    s.set_text('LineRole', 'me')
    g5 = s.if_positive(variable('Peer'))
    s.set_text('LineRole', 'h')
    s.end(g5)
    s.set('Twin', find_record(s, 'First Item', role=variable('LineRole'), key=f'p[^{FS}]*',
                              fp=regex_escape(s, fingerprint(s, s.cleanup(variable('Raw'))))))
    g5 = s.if_nonempty(variable('Twin'))
    s.set('Gap', s.math(field(s, variable('Twin'), 'ms'), '-', variable('Ms')))
    g6 = s.if_(variable('Gap'), LESS_THAN, number=120000)
    g7 = s.if_(variable('Gap'), GREATER_THAN, number=-120000)
    remove_record(s, variable('Twin'))
    changed(s)
    s.set_number('ColDirty', 1)
    s.end(g7)
    s.end(g6)
    s.end(g5)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)
    s.set_number('Reaction', 0)
    g = s.if_matches(variable('Type'), r'Reaction|^[^/]*/.+$')
    s.set_number('Reaction', 1)
    s.end(g)
    g = s.if_matches(variable('Raw'), TAPBACK_RE)
    s.set_number('Reaction', 1)
    s.end(g)
    s.set_number('DoAdd', 0)

    g_react = s.if_positive(variable('Reaction'))
    tapback_emoji(s, variable('Raw'), variable('Type'))
    s.set_text('Target', '')
    s.set_text('Quote', '')
    g = s.if_nonempty(variable('Ref'))
    abs_ms(s, variable('Ref'), 'RefMs')
    s.set('Target', find_record(s, 'First Item', key=s.text('m', variable('RefMs'), '-1')))
    s.end(g)
    g = s.if_nonempty(variable('Target'))
    s.otherwise(g)
    g2 = s.if_matches(variable('Raw'), r'[“"][\s\S]*[”"]$')
    s.set('Quote', s.cleanup(s.replace(s.replace(variable('Raw'), r'^[^“"]*[“"]'), r'[”"]$')))
    s.set('Target', find_record(s, 'Last Item', fp=regex_escape(s, fingerprint(s, variable('Quote')))))
    s.otherwise(g2)
    g3 = s.if_nonempty(variable('Ref'))
    s.comment('Read from Messages: a voice note isn’t confirmed by reading (its attachment can’t be read), so it is '
              'found by when it was sent. Talk to Hermes adds it seconds after sending it, and a reaction adds it '
              'when the reaction comes: within 90 seconds after, 15 before. Voice notes further apart are '
              'different ones.')
    near_record(s, 'RefMs', 15000, 90000, depth + 1, role='me', kind='a')
    s.set('Target', variable('Near'))
    g4 = s.if_(field(s, variable('Target'), 'key'), BEGINS_WITH, string='p')
    s.comment('The reaction says when the voice note was sent: it takes that time and its place in the chat.')
    s.set('LineMs', variable('Ms'))
    read_record(s, variable('Target'))
    s.set_text('Key', 'm', variable('RefMs'), '-1')
    s.set('Ms', variable('RefMs'))
    s.set('NearNew', record_text(s))
    remove_record(s, variable('Target'))
    insert_record(s, variable('NearNew'), depth + 1)
    s.set_number('ColDirty', 1)
    changed(s)
    s.set('Target', variable('NearNew'))
    s.set('Ms', variable('LineMs'))
    s.end(g4)
    s.otherwise(g3)
    s.comment('"Liked an attachment": your newest voice note or attachment.')
    s.set('Target', find_record(s, 'Last Item', role='me', fp='@attachment'))
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_(variable('Peer'), LESS_THAN, number=0)
    s.set_number('Peer', 0)
    g2 = s.if_(field(s, variable('Target'), 'role'), IS, string='me')
    s.set_number('Peer', 1)
    s.end(g2)
    s.end(g)
    s.comment('A tapback. From your agent it also means "read": the typing bubble shows until the reply.')
    g = s.if_positive(variable('Peer'))
    g2 = s.if_positive(s.math(variable('Ms'), '-', variable('AckMs')))
    s.set('AckMs', variable('Ms'))
    s.end(g2)
    s.end(g)
    g = s.if_nonempty(variable('Target'))
    set_react(s, variable('Target'))
    s.otherwise(g)
    g2 = s.if_nonempty(variable('Quote'))
    g3 = s.if_positive(variable('Confirmed'))
    s.otherwise(g3)
    s.comment('Your agent reacted to words that are not in the chat yet: a message you typed. Add it now; reading '
              'Messages confirms it.')
    g4 = s.if_matches(variable('Quote'), NEW_CHAT_RE)
    clear_chat(s, variable('Ms'))
    s.otherwise(g4)
    s.set_text('Role', 'me')
    s.set_text('Kind', 't')
    s.set_text('Src', '')
    s.set_text('FpOverride', '')
    s.set('Body', variable('Quote'))
    s.set('FirstReact', variable('Emoji'))
    s.set_text('KeyBase', variable('KeyBase'), 'q')
    s.set_number('DoAdd', 1)
    s.end(g4)
    s.end(g3)
    s.otherwise(g2)
    g3 = s.if_positive(variable('Confirmed'))
    s.otherwise(g3)
    g4 = s.if_matches(variable('Raw'), r'(?i)\ban audio message$')
    s.comment('Your agent reacted to a voice note that is not in the chat yet (sent from Messages, or Talk to Hermes '
              'is still transcribing): add it now. Its transcript joins it when it arrives.')
    s.set_text('Role', 'me')
    s.set_text('Kind', 'a')
    s.set_text('Src', '')
    s.set_text('FpOverride', '@attachment')
    s.set_text('Body', '')
    s.set('FirstReact', variable('Emoji'))
    s.set_text('KeyBase', variable('KeyBase'), 'q')
    s.set_number('DoAdd', 1)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)
    s.otherwise(g_react)

    g_fresh = s.if_positive(variable('Fresh'))
    s.set('Body', s.cleanup(variable('Raw')))
    s.set_text('Role', 'me')
    s.set_number('Busy', 0)
    g = s.if_positive(variable('Peer'))
    s.set_text('Role', 'h')
    g2 = s.if_matches(variable('Body'), STATUS_RE)
    s.set_number('Busy', 1)
    s.end(g2)
    s.end(g)
    g_busy = s.if_positive(variable('Busy'))
    s.comment('A status line from your agent ("⏳ Working — 2 min"): it is still on it.')
    g = s.if_positive(s.math(variable('Ms'), '-', variable('WorkMs')))
    s.set('WorkMs', variable('Ms'))
    s.end(g)
    s.set('Working', s.replace(variable('Body'), r'^[^\p{L}\p{N}]+'))
    s.otherwise(g_busy)
    s.set_text('Kind', 't')
    s.set_text('Src', '')
    s.set_text('FpOverride', '')
    s.set_text('FirstReact', '')
    g = s.if_matches(variable('Type'), '^Audio')
    s.set_text('Kind', 'a')
    s.set_text('FpOverride', '@attachment')
    s.set('Src', s.replace(variable('Attach'), r'\.[A-Za-z0-9]{2,4}$'))
    s.end(g)
    g = s.if_nonempty(variable('Body'))
    s.otherwise(g)
    s.comment('No words: a voice note, a photo or another attachment.')
    s.set_text('FpOverride', '@attachment')
    s.set('Src', s.replace(variable('Attach'), r'\.[A-Za-z0-9]{2,4}$'))
    g2 = s.if_matches(variable('Attach'), AUDIO_RE)
    s.set_text('Kind', 'a')
    s.otherwise(g2)
    g3 = s.if_matches(variable('Attach'), IMAGE_RE)
    s.set_text('Body', '📷 Photo')
    s.otherwise(g3)
    g4 = s.if_matches(variable('Attach'), VIDEO_RE)
    s.set_text('Body', '🎬 Video')
    s.otherwise(g4)
    s.set_text('Body', '📎 Attachment')
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)

    s.set_number('Reset', 0)
    g = s.if_(variable('Role'), IS, string='me')
    g2 = s.if_matches(variable('Body'), NEW_CHAT_RE)
    s.set_number('Reset', 1)
    s.end(g2)
    s.end(g)
    g_reset = s.if_positive(variable('Reset'))
    clear_chat(s, variable('Ms'))
    s.otherwise(g_reset)
    g_conf = s.if_positive(variable('Confirmed'))
    s.set_number('DoAdd', 1)
    s.otherwise(g_conf)
    s.comment('From a notification. A voice note you just sent may already be in the chat (Messages was read '
              'first): give it the transcript. Your agent’s message may already have been read from Messages by an '
              'update that finished first: then it is here.')
    s.set_text('Existing', '')
    g = s.if_(variable('Kind'), IS, string='a')
    g2 = s.if_nonempty(variable('Src'))
    s.set('Existing', find_record(s, 'Last Item', role='me', kind='a', src=regex_escape(s, variable('Src'))))
    s.end(g2)
    g2 = s.if_nonempty(variable('Existing'))
    s.otherwise(g2)
    s.set('Newest', find_record(s, 'Last Item', role='me', kind='a'))
    g3 = s.if_nonempty(variable('Newest'))
    g4 = s.if_(s.math(s.math(variable('Ms'), '-', field(s, variable('Newest'), 'ms')), '-', 180000), LESS_THAN,
               number=0)
    g5 = s.if_nonempty(field(s, variable('Newest'), 'text'))
    s.otherwise(g5)
    s.set('Existing', variable('Newest'))
    s.end(g5)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    g2 = s.if_nonempty(variable('Existing'))
    s.set('Transcript', variable('Body'))
    g3 = s.if_nonempty(variable('Transcript'))
    read_record(s, variable('Existing'))
    s.set('Text', variable('Transcript'))
    s.set('Log', s.replace_literal(variable('Log'), variable('Existing'), record_text(s)))
    queue(s, 'r')
    s.end(g3)
    s.end(g2)
    s.otherwise(g)
    g2 = s.if_(variable('Role'), IS, string='h')
    s.comment('Read from Messages less than 30 seconds before this notification: the same message. Read without a '
              'sender (iOS 26), it was taken for yours: it moves to your agent’s side.')
    s.set('Twin', find_record(s, 'Last Item', key=f'm[^{FS}]*', fp=regex_escape(s, fingerprint(s, variable('Body')))))
    g3 = s.if_nonempty(variable('Twin'))
    g4 = s.if_positive(s.math(s.math(field(s, variable('Twin'), 'ms'), '-', variable('Ms')), '+', 30000))
    s.set_text('Existing', 'seen')
    g5 = s.if_(field(s, variable('Twin'), 'role'), IS, string='me')
    read_record(s, variable('Twin'))
    s.set_text('Role', 'h')
    s.set('Log', s.replace_literal(variable('Log'), variable('Twin'), record_text(s)))
    queue(s, 'r')
    s.end(g5)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_nonempty(variable('Existing'))
    s.otherwise(g)
    s.set_number('DoAdd', 1)
    s.end(g)
    s.end(g_conf)
    s.end(g_reset)
    s.end(g_busy)
    s.end(g_fresh)
    s.end(g_react)
    g = s.if_positive(variable('DoAdd'))
    add_message(s, depth + 1)
    s.end(g)


# The renderer.

def load_state(s):
    s.set('SavedState', s.file(f'{DIR}/chat.json', False))
    g = s.if_(variable('SavedState'), HAS_VALUE)
    s.set('State', s.act('detect.dictionary', {'WFInput': attachment(variable('SavedState'))}, 'Dictionary'))
    s.otherwise(g)
    s.set('State', s.dictionary([]))
    s.end(g)
    s.comment('A chat saved by an older version starts fresh: reading Messages fills it back in.')
    g = s.if_(s.text(variable('State', 'version')), IS, string=STATE_VERSION)
    s.set_text('Log', variable('State', 'log'))
    s.set_text('Status', variable('State', 'status'))
    s.set('NextId', s.math(s.text(variable('State', 'next_id')), '+', 0))
    s.set('Since', s.math(s.text(variable('State', 'since')), '+', 0))
    s.set_text('Known', '\n', variable('State', 'known'))
    s.set_text('Light', variable('State', 'light'))
    s.set_text('ColKey', variable('State', 'col'))
    s.otherwise(g)
    for name in ('Log', 'Status', 'Light', 'ColKey'):
        s.set_text(name, '')
    s.set_number('NextId', 0)
    s.set_number('Since', 0)
    s.set_text('Known', '\n')
    s.end(g)
    s.set('LightAt', variable('Zero'))
    g = s.if_nonempty(variable('Light'))
    s.set('LightAt', s.math(s.text(variable('State', 'light_at')), '+', 0))
    s.end(g)
    for name in ('ColN', 'ColMs', 'ColH'):
        s.set(name, variable('Zero'))
    s.set_text('ColRole', '')
    s.comment('Where the stack of older bubbles ends: its record, how many records it holds, and its height.')
    g = s.if_nonempty(variable('ColKey'))
    for name, key in (('ColN', 'col_n'), ('ColMs', 'col_ms'), ('ColH', 'col_h')):
        s.set(name, s.math(s.text(variable('State', key)), '+', 0))
    s.set_text('ColRole', variable('State', 'col_role'))
    s.end(g)


def find_messages(s, hours, limit):
    """Find Messages: every conversation's messages from the last `hours`, newest first, at most `limit`."""
    return s.act('com.apple.MobileSMS.MessageEntity', {
        'AppIntentDescriptor': MESSAGES_APP,
        'WFContentItemFilter': {'Value': {'WFContentPredicateBoundedDate': False, 'WFActionParameterFilterPrefix': 1,
                                          'WFActionParameterFilterTemplates': [
                                              {'Property': 'date', 'Operator': 1001, 'Bounded': True,
                                               'Removable': True, 'Values': {'Number': str(hours), 'Unit': 32}}]},
                                'WFSerializationType': 'WFContentPredicateTableTemplate'},
        'WFContentItemSortProperty': 'date', 'WFContentItemSortOrder': 'Latest First',
        'WFContentItemLimitEnabled': True, 'WFContentItemLimitNumber': limit}, 'Messages')


def read_messages(s):
    """The newest messages in Messages, kept to your agent's conversation, oldest first, as LINE text in Batch."""
    s.set('PeerKey', name_key(s, variable('Agent')))
    g = s.if_nonempty(variable('PeerKey'))
    s.otherwise(g)
    s.set_number('Abort', 1)
    s.end(g)

    find = lambda hours, limit: find_messages(s, hours, limit)
    s.comment(f'Messages from the last {SYNC["hours"]} hours, newest first. Only your agent’s conversation is kept; '
              'nothing else is saved.')
    trace(s, 'finding, peer ', variable('PeerKey'))
    g = s.if_nonempty(variable('Log'))
    s.set('Found', find(SYNC['hours'], SYNC['limit']))
    s.set_number('KeepN', SYNC['keep'])
    s.otherwise(g)
    s.comment(f'An empty chat looks further back once, to start from what is already in Messages: the newest '
              f'{SYNC["backfillKeep"]}, which fill the screen. The chat then starts there.')
    s.set('Found', find(SYNC['backfillHours'], SYNC['backfillLimit']))
    s.set_number('KeepN', SYNC['backfillKeep'])
    s.set_number('Backfill', 1)
    s.end(g)
    trace(s, 'found ', s.count(variable('Found'), 'Items'), keep=True)
    g = s.if_(variable('Raw'), IS, string='sync by hand')
    s.comment('Run by hand: note that Find Messages answered, so a stop after this is in the reading, not the finding.')
    s.save(s.dictionary([('release', RELEASE), ('stage', 'found'), ('found', s.count(variable('Found'), 'Items')),
                         ('at', variable('NowMs'))]), f'{DIR}/sync-status.json')
    s.end(g)
    s.set_text('Batch', '')
    s.set_text('NewKnown', '')
    s.set_number('Kept', 0)
    trace(s, 'reading')
    loop = s.repeat_each(variable('Found'))
    it = {'Type': 'Variable', 'VariableName': 'Repeat Item'}
    s.comment(f'Newest first: after {SYNC["knownStop"]} messages an earlier read handled, the rest are older still, '
              'and were handled too.')
    g_done = s.if_(variable('KnownHits'), GREATER_THAN, number=SYNC['knownStop'] - 1)
    s.otherwise(g_done)
    s.set('MDate', prop(it, 'Date', 'date'))
    s.comment('A message without a date can’t be placed: skip it rather than guess.')
    g_date = s.if_nonempty(s.text(variable('MDate')))
    s.set('MWhen', s.fmt(variable('MDate'), WHEN))
    s.comment('Handled by an earlier read (it is known by when it was sent): skip it without looking further.')
    g_known = s.if_(variable('Known'), CONTAINS, string=token_string('\n', variable('MWhen'), '\n'))
    s.set('KnownHits', s.math(variable('KnownHits'), '+', 1))
    s.otherwise(g_known)
    s.comment(f'Handle at most the newest {SYNC["keep"]} of your agent’s messages each read: more than ever arrive '
              'between two reads, and a first read stays quick.')
    s.set_text('InChat', '')
    g0 = s.if_positive(s.math(variable('KeepN'), '-', variable('Kept')))
    s.set('InChat', name_key(s, s.text(prop(it, 'Conversation', 'conversation'))))
    s.end(g0)
    g = s.if_same(variable('InChat'), variable('PeerKey'))
    s.set('Kept', s.math(variable('Kept'), '+', 1))
    s.set_text('NewKnown', variable('NewKnown'), variable('MWhen'), '\n')
    s.set('MBody', s.text(prop(it, 'Body', 'body')))
    s.set('MType', s.text(prop(it, 'Type', 'messageType'), '/', prop(it, 'Reaction', 'reaction')))
    s.set_text('MRef', '')
    s.set_number('MSkip', 0)
    g3 = s.if_matches(variable('MType'), r'Reaction|^[^/]*/.+$')
    s.set('RefMsg', prop(it, 'Reference', 'referencedMessage'))
    s.set('RefDate', prop({'Type': 'Variable', 'VariableName': 'RefMsg'}, 'Date', 'date'))
    g4 = s.if_nonempty(s.text(variable('RefDate')))
    s.set('MRef', s.fmt(variable('RefDate'), WHEN))
    s.end(g4)
    s.otherwise(g3)
    s.comment('No words and no reaction: a voice note, photo or other attachment. Its attachments are never read '
              '(on iOS 26 reading a voice note’s stops the shortcut), and your voice notes come straight from Talk to '
              'Hermes, so it is skipped.')
    g4 = s.if_nonempty(variable('MBody'))
    s.otherwise(g4)
    s.set_number('MSkip', 1)
    s.end(g4)
    s.end(g3)
    g3 = s.if_positive(variable('MSkip'))
    s.otherwise(g3)
    s.comment('Who sent it: 1 your agent, 0 you, -1 unknown (iOS 26 leaves Sender empty; the chat then works it out '
              'from the notifications it already has).')
    s.set_number('Peer', -1)
    s.set('Sender', s.text(prop(it, 'Sender', 'author')))
    g4 = s.if_nonempty(variable('Sender'))
    s.set_number('Peer', 0)
    g5 = s.if_same(name_key(s, variable('Sender')), variable('PeerKey'))
    s.set_number('Peer', 1)
    s.end(g5)
    s.end(g4)
    line = s.text('m', FS, variable('MWhen'), FS, s.fmt(variable('MDate'), 'EEEE'), FS,
                  s.short_time(variable('MDate')), FS, variable('Peer'), FS, variable('MType'), FS, variable('MRef'),
                  FS, FS, variable('MBody'))
    s.set_text('Batch', line, RS, variable('Batch'))
    s.end(g3)
    s.end(g)
    s.end(g_known)
    s.end(g_date)
    s.end(g_done)
    s.end_repeat_each(loop)
    trace(s, 'read, kept ', variable('Kept'), keep=True)


def follow_status(s):
    """Once the newest record is confirmed: typing (with "Read") while your newest message has a reaction or a status
    line after it, or your agent posted a status line after its own last message; otherwise none."""
    g = s.if_nonempty(variable('Log'))
    newest = s.item(s.match(variable('Log'), f'[^{RS}]+'), 'Last Item')
    g2 = s.if_(field(s, newest, 'key'), BEGINS_WITH, string='m')
    for role, name in (('me', 'LastMe'), ('h', 'LastH')):
        s.set_number(name, 0)
        s.set('Found', find_record(s, 'Last Item', role=role))
        g3 = s.if_nonempty(variable('Found'))
        s.set(name, s.math(field(s, variable('Found'), 'ms'), '+', 0))
        s.end(g3)
    s.set_number('Want', 0)
    g3 = s.if_positive(s.math(variable('LastMe'), '-', variable('LastH')))
    g4 = s.if_positive(s.math(variable('AckMs'), '-', variable('LastMe')))
    s.set_number('Want', 1)
    s.end(g4)
    g4 = s.if_positive(s.math(variable('WorkMs'), '-', variable('LastMe')))
    s.set_number('Want', 1)
    s.end(g4)
    s.otherwise(g3)
    g4 = s.if_positive(s.math(variable('WorkMs'), '-', variable('LastH')))
    s.set_number('Want', 1)
    s.end(g4)
    s.end(g3)
    g3 = s.if_positive(variable('Want'))
    g4 = s.if_nonempty(variable('Status'))
    s.otherwise(g4)
    s.set_text('Status', 'thinking')
    changed(s)
    s.end(g4)
    s.otherwise(g3)
    g4 = s.if_nonempty(variable('Status'))
    s.set_text('Status', '')
    changed(s)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)


def event_line(s):
    """A message as it arrives, as one LINE in Batch: your voice note or words, or your agent's message."""
    s.set_text('LinePeer', '0')
    s.set_text('Type', '')
    s.set_text('Attach', '')
    s.set('Body', variable('Raw'))
    s.set_text('Command', 'agent')
    g = s.if_positive(variable('FromAutomation'))
    s.otherwise(g)
    g2 = s.if_(variable('Raw'), BEGINS_WITH, string='me-audio')
    s.set_text('Command', 'audio')
    s.otherwise(g2)
    g3 = s.if_(variable('Raw'), BEGINS_WITH, string='me:')
    s.set_text('Command', 'me')
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_(variable('Command'), IS, string='audio')
    s.set_text('Type', 'Audio/')
    s.set('Attach', s.replace(variable('Raw'), r'^me-audio(?:\[([^\]\n]*)\])?[\s\S]*$', '$1'))
    s.set('Body', s.replace(variable('Raw'), r'^me-audio(?:\[[^\]\n]*\])?:?\s*'))
    s.otherwise(g)
    g2 = s.if_(variable('Command'), IS, string='me')
    s.set('Body', s.replace(variable('Raw'), r'^me:\s*'))
    g3 = s.if_nonempty(s.act('text.trimwhitespace', {'WFInput': token_string(variable('Body'))}, 'Updated Text'))
    s.otherwise(g3)
    s.comment('Nothing was said (an empty transcription): there is nothing to add.')
    s.set_number('Skip', 1)
    s.end(g3)
    s.otherwise(g2)
    s.set_text('LinePeer', '1')
    s.set('Body', s.replace(variable('Raw'), r'^hermes:\s*'))
    s.end(g2)
    s.end(g)
    s.set_text('Batch', '')
    g = s.if_positive(variable('Skip'))
    s.otherwise(g)
    s.set_text('Batch', 'p', variable('NowMs'), FS, variable('NowWhen'), FS, variable('NowDay'), FS,
               variable('NowTime'), FS, variable('LinePeer'), FS, variable('Type'), FS, FS, variable('Attach'), FS,
               variable('Body'))
    s.end(g)


def event_status(s):
    """Typing follows the moment: your agent's reply ends it; a reaction to your newest message, or a status line,
    starts it."""
    g = s.if_positive(variable('Reaction'))
    g2 = s.if_positive(variable('Peer'))
    g3 = s.if_nonempty(variable('Log'))
    newest = s.item(s.match(variable('Log'), f'[^{RS}]+'), 'Last Item')
    g4 = s.if_(field(s, newest, 'role'), IS, string='me')
    g5 = s.if_nonempty(variable('Status'))
    s.otherwise(g5)
    s.set_text('Status', 'thinking')
    changed(s)
    s.end(g5)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.otherwise(g)
    g2 = s.if_positive(variable('Busy'))
    s.set('Status', variable('Working'))
    changed(s)
    s.otherwise(g2)
    g3 = s.if_positive(variable('Added'))
    g4 = s.if_nonempty(variable('Status'))
    s.set_text('Status', '')
    changed(s)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)


def draw_jobs(s):
    """Draws the rows the changes asked for (each once), then fills their sizes into the log. A change to a bubble
    already in the cached stack has the stack rebuilt."""
    s.comment('Draw the new and changed rows. A record removed since it was queued is skipped.')
    loop = s.repeat_each(s.match(variable('Jobs'), f'[^{RS}]+'))
    s.set('Job', s.text(variable('Repeat Item')))   # text, so If can test it (a match item can't be)
    s.set('JKey', s.replace(variable('Job'), f'^[^{FS}]*{FS}'))
    s.set('Old', find_record(s, 'First Item', key=variable('JKey')))
    trace(s, 'draw row ', variable('JKey'), keep=True)
    g = s.if_nonempty(variable('Old'))
    s.comment('The message just added still has its fields in variables: no need to read them back.')
    s.set_number('Live', 0)
    g2 = s.if_(variable('Job'), BEGINS_WITH, string='n')
    g3 = s.if_same(variable('JKey'), variable('Key'))
    s.set_number('Live', 1)
    s.end(g3)
    s.end(g2)
    g2 = s.if_positive(variable('Live'))
    s.otherwise(g2)
    read_record(s, variable('Old'))
    s.end(g2)
    g2 = s.if_(s.math(variable('ColMs'), '-', variable('Ms')), GREATER_THAN, number=-1)
    s.set_number('ColDirty', 1)
    s.end(g2)
    render_row(s, 2)
    s.set('Log', s.replace_literal(variable('Log'), variable('Old'), record_text(s)))
    s.end(g)
    s.end_repeat_each(loop)


def build_renderer():
    s = Shortcut()
    s.comment(f'{RENDERER_NAME} keeps your chat and draws it for {WALLPAPER_NAME}. You don’t need to open it; a new '
              'design replaces this shortcut and nothing else.\n\n'
              'Input: a message from your agent, "me-audio[<name>]: <words>" or "me: <words>" for yours, "sync" to read '
              'Messages, dawn, day, dusk or night (from a Sun automation) to change the wall, or nothing to redraw.\n'
              f'Files: iCloud Drive › Shortcuts › {DIR} (images, chat.json, and rows/ with images for each message '
              'and the stack of older ones).')
    s.set('TStart', ms_now(s))
    agent_index = len(s.actions)
    s.set('Agent', s.text(DEFAULT_AGENT))
    s.comment('Your agent’s name exactly as its contact is named in Messages: it finds the conversation, and shows when '
              'a chat is new. Put a square photo at Hermes/avatar-photo.png to give it a face.')
    s.set('Hint', s.text(HINT))
    s.comment('Where the chat may sit, in pixels (3 px = 1 pt): Top is under the clock, Bottom is just above the '
              'flashlight row. If you keep widgets under the clock, raise Top by their height (about 240).')
    s.set_number('Top', TOP)
    s.set_number('Bottom', BOTTOM)
    s.comment('1 reads the newest messages in Messages to add the ones you sent and any iOS skipped; 0 draws only what '
              'notifications bring (lighter, but your typed messages then show only through your agent’s tapbacks).')
    s.set_number('ReadMessages', 1)
    s.quiet = True   # nobody opens the rest: its notes live in build_shortcut.py
    zero = s.number(0)
    for name in ('Zero', 'Changed', 'Dirty', 'Added', 'Adopted', 'AckMs', 'WorkMs', 'Seen', 'Skip', 'Busy',
                 'Reaction', 'DoAdd', 'FromAutomation', 'Backfill', 'ColDirty', 'KnownHits', 'ByHand', 'Unsure'):
        s.set(name, zero)
    if QA:
        s.set_text('Trace', '')
    s.set_text('Jobs', '')
    s.set_text('Mode', 'redraw')
    load_state(s)
    s.set('TState', ms_now(s))
    s.comment('Rows drawn in an older look are redrawn once: badges with a dark ring, and long messages wrapped '
              'narrower than they needed.')
    s.set('Look', s.text(variable('State', 'look')))
    g = s.if_(variable('Look'), IS, string=LOOK)
    s.otherwise(g)
    g2 = s.if_(variable('Look'), IS, string='2')
    s.otherwise(g2)
    loop = s.repeat_each(s.match(variable('Log'), rec_pattern(react=f'[^{FS}]+')))
    s.set('Key', field(s, s.replace(s.text(variable('Repeat Item')), f'^{RS}'), 'key'))
    queue(s, 'r')
    s.end_repeat_each(loop)
    s.end(g2)
    loop = s.repeat_each(s.match(variable('Log'), rec_pattern(kind='t', rowH=r'(?:[3-9]\d\d|\d{4,})')))
    s.set('Key', field(s, s.replace(s.text(variable('Repeat Item')), f'^{RS}'), 'key'))
    queue(s, 'r')
    s.end_repeat_each(loop)
    s.set_number('ColDirty', 1)
    s.set_number('Dirty', 1)
    s.end(g)
    s.set('Now', s.now())
    s.set('NowWhen', s.fmt(variable('Now'), WHEN))
    abs_ms(s, variable('NowWhen'), 'NowMs')
    s.set('NowDay', s.fmt(variable('Now'), 'EEEE'))
    s.set('NowTime', s.short_time(variable('Now')))

    s.set_text('Batch', '')
    s.set_text('NewKnown', '')
    s.set_number('Abort', 0)
    trace(s, 'start')
    g_input = s.if_(shortcut_input(), HAS_VALUE)
    s.set('InputType', s.act('getitemtype', {'WFInput': attachment(shortcut_input())}, 'Type'))
    trace(s, 'input ', variable('InputType'))
    s.comment('A time trigger may pass its date: that only redraws.')
    g_date = s.if_(variable('InputType'), IS, string='Date')
    s.otherwise(g_date)
    s.set_number('FromAutomation', 1)
    s.set_text('Raw', shortcut_input())
    g = s.if_(variable('InputType'), IS, string='Text')
    s.set_number('FromAutomation', 0)
    s.end(g)
    g = s.if_(variable('InputType'), IS, string='File')
    s.set_number('FromAutomation', 0)
    s.end(g)
    g = s.if_positive(variable('FromAutomation'))
    s.comment('A message from the Message automation is always your agent’s, whatever it says.')
    s.set_text('Raw', shortcut_input('Content'))
    g2 = s.if_nonempty(variable('Raw'))
    s.otherwise(g2)
    s.set_text('Raw', shortcut_input())
    s.end(g2)
    s.end(g)
    trace(s, 'raw ', variable('Raw'))
    s.set_text('Mode', 'event')
    g = s.if_positive(variable('FromAutomation'))
    s.otherwise(g)
    g2 = s.if_matches(variable('Raw'), r'^sync(?:$| by hand$|-fixture:)')
    s.set_text('Mode', 'sync')
    s.end(g2)
    g2 = s.if_matches(variable('Raw'), LIGHT_RE)
    s.set_text('Mode', 'light')
    s.end(g2)
    s.end(g)
    s.end(g_date)
    s.otherwise(g_input)
    hours = '|'.join(f'{h:02d}' for h in T['hours'].values())
    s.comment('Run with nothing, as when you tap it: read Messages too. iOS asks for access to Messages only when '
              'this shortcut is run by itself, never while Hermes Lock Screen runs it, so this is how it gets access. '
              f'A Time of Day automation (minutes 0–4 of {", ".join(f"{h}:00" for h in T["hours"].values())}) only '
              'redraws.')
    g = s.if_matches(s.fmt(variable('Now'), 'HH:mm'), rf'^(?:{hours}):0[0-4]$')
    s.otherwise(g)
    s.set_text('Mode', 'sync')
    s.set_text('Raw', 'sync by hand')
    s.set_number('ByHand', 1)
    s.end(g)
    s.end(g_input)
    g = s.if_(variable('Mode'), IS, string='sync')
    g2 = s.if_(variable('Raw'), BEGINS_WITH, string='sync-fixture:')
    s.comment('Tests pass messages in directly.')
    s.set('Batch', s.replace(variable('Raw'), r'^sync-fixture:\n?'))
    s.otherwise(g2)
    g3 = s.if_positive(variable('ReadMessages'))
    read_messages(s)
    s.end(g3)
    s.end(g2)
    s.otherwise(g)
    g2 = s.if_(variable('Mode'), IS, string='light')
    s.comment('From a Sun automation: the wall keeps this light until the next one.')
    s.set('Light', s.lower(s.act('text.trimwhitespace', {'WFInput': token_string(variable('Raw'))}, 'Updated Text')))
    s.set('LightAt', variable('NowMs'))
    s.set_number('Dirty', 1)
    s.otherwise(g2)
    g3 = s.if_(variable('Mode'), IS, string='event')
    event_line(s)
    s.end(g3)
    s.end(g2)
    s.end(g)

    s.comment('Add each message: one from a notification, or the newest from Messages, oldest first.')
    s.set('Items', s.match(variable('Batch'), f'[^{RS}]+'))
    g = s.if_(variable('Mode'), IS, string='sync')
    s.comment('Where the chat began, less 5 minutes: who sent a message read from before then can’t be told on iOS 26.')
    s.set('ChatStart', variable('NowMs'))
    g2 = s.if_nonempty(variable('Log'))
    s.set('ChatStart', s.math(field(s, s.text(s.item(s.match(variable('Log'), f'[^{RS}]+'), 'First Item')), 'ms'), '-',
                              300000))
    s.end(g2)
    s.end(g)
    s.set('Seen', s.count(variable('Items'), 'Items'))
    g = s.if_positive(variable('Abort'))
    s.otherwise(g)
    loop = s.repeat(variable('Seen'))
    s.set('Line', s.item(variable('Items'), 'Item At Index', variable('Repeat Index')))
    trace(s, 'line ', variable('Repeat Index'))
    add_line(s, 1)
    s.end_repeat(loop)
    trace(s, 'lines done', keep=True)
    g2 = s.if_nonempty(variable('NewKnown'))
    s.comment('Remember the messages this read handled (by when they were sent), so the next read skips them.')
    s.set('Known', s.replace(s.text('\n', variable('NewKnown'), s.replace(variable('Known'), '^\n')),
                             rf'^(\n(?:[^\n]*\n){{{SYNC["known"]}}})[\s\S]*$', '$1'))
    s.set_number('Dirty', 1)
    s.end(g2)
    g2 = s.if_positive(variable('Backfill'))
    s.comment('The chat starts at the oldest message the first read kept: later reads don’t reach further back.')
    g3 = s.if_nonempty(variable('Log'))
    first = s.text(s.item(s.match(variable('Log'), f'[^{RS}]+'), 'First Item'))
    s.set('Since', s.math(field(s, first, 'ms'), '-', 1))
    s.end(g3)
    s.end(g2)
    g2 = s.if_(variable('Mode'), IS, string='sync')
    follow_status(s)
    s.otherwise(g2)
    g3 = s.if_(variable('Mode'), IS, string='event')
    event_status(s)
    s.end(g3)
    s.end(g2)
    s.end(g)
    s.comment('When reading Messages found nothing of your agent’s, or couldn’t tell who wrote a message, say so in '
              'sync-status.json (written only then, to keep updates light).')
    g = s.if_(variable('Mode'), IS, string='sync')
    s.set_number('Report', 0)
    s.set('Report', s.math(variable('ReadMessages'), '×', 0))
    g2 = s.if_(s.math(variable('Seen'), '+', variable('KnownHits')), LESS_THAN, number=1)
    s.set('Report', variable('ReadMessages'))
    s.end(g2)
    g2 = s.if_positive(variable('Abort'))
    s.set_number('Report', 1)
    s.end(g2)
    g2 = s.if_positive(variable('Report'))
    s.save(s.dictionary([('release', RELEASE), ('at', variable('NowMs')), ('seen', variable('Seen')),
                         ('abort', variable('Abort'))]), f'{DIR}/sync-status.json')
    s.end(g2)
    s.end(g)

    s.set('TLines', ms_now(s))
    g = s.if_positive(variable('Dirty'))
    s.comment(f'Keep the newest {KEEP} bubbles. Row files are reused, so the folder never grows.')
    total = s.count(s.match(variable('Log'), f'[^{RS}]+'), 'Items')
    g2 = s.if_(total, GREATER_THAN, number=KEEP)
    s.set('Log', s.replace(variable('Log'), token_string(f'^(?:[^{RS}]*{RS}){{', s.math(total, '-', KEEP), '}')))
    s.set('ColN', s.math(variable('ColN'), '-', s.math(total, '-', KEEP)))
    s.end(g2)
    draw_jobs(s)
    s.end(g)
    s.set('TJobs', ms_now(s))
    for name in ('TWall', 'TStack', 'TCompose', 'TDraw'):
        s.set(name, variable('TJobs'))

    trace(s, 'rows', keep=True)
    s.comment('Draw only when the chat changed, or when run with nothing; otherwise output nothing.')
    s.set('Draw', variable('Changed'))
    for mode in ('redraw', 'light'):
        g = s.if_(variable('Mode'), IS, string=mode)
        s.set_number('Draw', 1)
        s.end(g)
    g = s.if_positive(variable('ByHand'))
    s.set_number('Draw', 1)
    s.end(g)
    g = s.if_positive(variable('Draw'))
    draw(s)
    s.set('TDraw', ms_now(s))
    s.end(g)
    trace(s, 'drawn', keep=True)
    g = s.if_positive(variable('Dirty'))
    s.comment('Saved after drawing: where the stack of older bubbles ends is part of the chat. Also how long this '
              'update took, in milliseconds, for tuning.')
    marks = (('state', 'TStart', 'TState'), ('lines', 'TState', 'TLines'), ('rows', 'TLines', 'TJobs'),
             ('wall', 'TJobs', 'TWall'), ('stack', 'TWall', 'TStack'), ('compose', 'TStack', 'TCompose'),
             ('overlay', 'TCompose', 'TDraw'))
    parts = []
    for label, a, b in marks:
        parts += [f'{label} ', s.math(variable(b), '-', variable(a)),
                  *([variable('RowPerf')] if label == 'rows' else [variable('ColPerf')] if label == 'stack' else []), ' · ']
    perf = s.text(*parts, 'total ', s.math(ms_now(s), '-', variable('TStart')), ' · ', variable('Mode'))
    s.save(s.dictionary([('version', STATE_VERSION), ('log', variable('Log')), ('status', variable('Status')),
                         ('next_id', variable('NextId')), ('since', variable('Since')),
                         ('known', s.replace(variable('Known'), '^\n')), ('col', variable('ColKey')),
                         ('col_n', variable('ColN')), ('col_ms', variable('ColMs')), ('col_h', variable('ColH')),
                         ('col_role', variable('ColRole')), ('light', variable('Light')),
                         ('light_at', variable('LightAt')), ('look', LOOK), ('perf', perf)]), f'{DIR}/chat.json')
    s.end(g)
    trace(s, 'saved')
    save_trace(s)
    g = s.if_positive(variable('Draw'))
    s.act('output', {'WFOutput': token_string(variable('Img'))})
    s.end(g)
    question = {'ActionIndex': agent_index, 'Category': 'Parameter', 'ParameterKey': 'WFTextActionText',
                'Text': 'What’s your agent’s contact called in Messages? It finds the conversation and shows when a '
                        'chat is new.',
                'DefaultValue': DEFAULT_AGENT}
    return workflow(s, glyph=59414, color=255, accepts_input=True, questions=[] if QA else [question])


def stamp_piece(s, depth):
    """The timestamp above CRec into StampImg, drawn the first time it shows. Above the first record in the chat
    (First) it has no space above it. `depth` is the depth of the measuring loop."""
    s.set('StampImg', s.file(row_path(variable('CId'), '-s'), False))
    g = s.if_(variable('StampImg'), HAS_VALUE)
    s.otherwise(g)
    s.set('Day', field(s, variable('CRec'), 'day'))
    s.set('Time', field(s, variable('CRec'), 'time'))
    s.set('Id', variable('CId'))
    render_stamp(s, depth)
    s.end(g)
    g = s.if_positive(variable('First'))
    s.set('StampImg', s.crop(variable('StampImg'), 0, STAMP_ABOVE, W, STAMP_H - STAMP_ABOVE))
    s.end(g)


def append_pieces(s, parts, first, last):
    """Adds to the list `parts` the pieces of records `first`…`last` of Recs, oldest first: the gap above each (none
    above the first in the chat), its timestamp after a quiet spell, then its row, with its tail when it ends one
    sender's run. The newest has its tail unless the typing bubble continues your agent's side. PRole and PMs hold
    the record before `first`."""
    s.set('J', first)
    s.set('JEnd', last)
    loop = s.repeat(s.math(s.math(variable('JEnd'), '-', variable('J')), '+', 1))
    s.set('CRec', s.text(s.item(variable('Recs'), 'Item At Index', variable('J'))))
    s.set('CId', field(s, variable('CRec'), 'id'))
    s.set('CRole', field(s, variable('CRec'), 'role'))
    s.set('CMs', field(s, variable('CRec'), 'ms'))
    s.set_number('Stamped', 1)
    s.set_number('First', 1)
    g = s.if_(variable('J'), GREATER_THAN, number=1)
    s.set_number('First', 0)
    g2 = s.if_same(variable('CRole'), variable('PRole'))
    need(s, 'GapSame')
    s.append(parts, variable('GapSame'))
    s.otherwise(g2)
    need(s, 'GapTurn')
    s.append(parts, variable('GapTurn'))
    s.end(g2)
    s.set('Quiet', s.math(s.math(variable('CMs'), '-', variable('PMs')), '÷', 60000))
    g2 = s.if_(variable('Quiet'), LESS_THAN, number=STAMP_GAP)
    g3 = s.if_(variable('Quiet'), LESS_THAN, number=0)
    s.otherwise(g3)
    s.set_number('Stamped', 0)
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_positive(variable('Stamped'))
    stamp_piece(s, 2)
    s.append(parts, variable('StampImg'))
    s.end(g)
    s.set_number('Tail', 1)
    g = s.if_positive(s.math(variable('N'), '-', variable('J')))
    nxt = s.text(s.item(variable('Recs'), 'Item At Index', s.math(variable('J'), '+', 1)))
    g2 = s.if_same(field(s, nxt, 'role'), variable('CRole'))
    s.set_number('Tail', 0)
    s.end(g2)
    s.otherwise(g)
    g2 = s.if_positive(variable('Waiting'))
    g3 = s.if_(variable('CRole'), IS, string='h')
    s.set_number('Tail', 0)
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_same(variable('CId'), variable('LastRowId'))
    s.set('Piece', variable('LastRow'))
    s.otherwise(g)
    s.set('Piece', s.file(row_path(variable('CId')), True))
    s.end(g)
    g = s.if_positive(variable('Tail'))
    g2 = s.if_(field(s, variable('CRec'), 'kind'), IS, string='t')
    g3 = s.if_matches(field(s, variable('CRec'), 'text'), JUMBO_RE)
    s.set_number('Tail', 0)   # emoji drawn large have no bubble, so no tail
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_positive(variable('Tail'))
    for name in ('bx', 'by', 'bw', 'bh'):
        s.set(f'T{name}', field(s, variable('CRec'), name))
    y = s.math(s.math(variable('Tby'), '+', variable('Tbh')), '-', TAIL['inset'])
    g2 = s.if_(variable('CRole'), IS, string='me')
    need(s, 'TailRight')
    s.set('Piece', s.overlay(variable('Piece'), variable('TailRight'),
                             s.math(s.math(variable('Tbx'), '+', variable('Tbw')), '-', TAIL['inset']), y, TAIL['w'],
                             TAIL['h']))
    s.otherwise(g2)
    need(s, 'TailLeft')
    s.set('Piece', s.overlay(variable('Piece'), variable('TailLeft'), s.math(variable('Tbx'), '-', TAIL['w'] - TAIL['inset']),
                             y, TAIL['w'], TAIL['h']))
    s.end(g2)
    s.end(g)
    s.append(parts, variable('Piece'))
    s.set('PRole', variable('CRole'))
    s.set('PMs', variable('CMs'))
    s.set('J', s.math(variable('J'), '+', 1))
    s.end_repeat(loop)


def draw(s):
    s.comment('Draw: the older bubbles are kept stacked as one image (rows/col.png), so a new message adds one row '
              'to it and lays the stack on the wall. The stack is rebuilt only when an older bubble changes. When '
              'everything fits it hangs from Top; otherwise it ends at Bottom and fades into the wall under the '
              'clock.')
    s.comment('The wall follows the light: the last dawn, day, dusk or night a Sun automation passed (for up to 4 '
              'hours at dawn and dusk, 18 otherwise), else the hour.')
    hours = T['hours']

    def wall_at(h):
        for name, start, stop in (('dawn', hours['dawn'], hours['day']), ('day', hours['day'], hours['dusk']),
                                  ('dusk', hours['dusk'], hours['night'])):
            if start <= h < stop:
                return f'wall-{name}'
        return 'wall'
    s.set('WallName', s.text(s.value_for(s.dictionary([(str(h), wall_at(h)) for h in range(24)]),
                                         s.fmt(variable('Now'), 'H'))))
    g = s.if_nonempty(variable('Light'))
    s.set('LightAge', s.math(variable('NowMs'), '-', variable('LightAt')))
    s.set_number('LightFor', 18 * 3600000)
    g2 = s.if_matches(variable('Light'), '^(?:dawn|dusk)$')
    s.set_number('LightFor', 4 * 3600000)
    s.end(g2)
    g2 = s.if_(variable('LightAge'), GREATER_THAN, number=-1)
    g3 = s.if_positive(s.math(variable('LightFor'), '-', variable('LightAge')))
    s.set_text('WallName', 'wall-', variable('Light'))
    g4 = s.if_(variable('Light'), IS, string='night')
    s.set_text('WallName', 'wall')
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)
    s.set('Wall', s.file(token_string(f'{DIR}/', variable('WallName'), '.png'), False))
    g = s.if_(variable('Wall'), HAS_VALUE)
    s.otherwise(g)
    s.set('Wall', s.file(f'{DIR}/wall.png', True))
    s.end(g)
    s.set('TWall', ms_now(s))
    s.set('Img', variable('Wall'))
    s.set('Recs', s.match(variable('Log'), f'[^{RS}]+'))
    s.set('N', s.count(variable('Recs'), 'Items'))
    s.set('Shift', s.math(variable('Top'), '-', TOP))   # moving Top moves the fade with it

    g_any = s.if_positive(variable('N'))
    newest = s.item(variable('Recs'), 'Last Item')
    s.set('Newest', newest)
    s.set('NewestRole', field(s, variable('Newest'), 'role'))
    s.set_number('Waiting', 0)
    g = s.if_nonempty(variable('Status'))
    s.set_number('Waiting', 1)
    s.end(g)
    s.comment('Below the newest bubble: your receipt, then the typing bubble while your agent works.')
    s.set_number('Below', B['tailRoom'])
    g = s.if_(variable('NewestRole'), IS, string='me')
    s.set_number('Below', B['tailRoom'] + RECEIPT_H)
    s.end(g)
    g = s.if_positive(variable('Waiting'))
    s.set_number('Below', M['typing']['below'])
    s.end(g)

    s.comment('The stack of older bubbles: reuse it, or rebuild it after a bubble in it changed (or if it doesn’t '
              f'match the chat). The newest bubbles stay outside it, drawn from their own rows, until {FOLD_AT} older '
              'ones have gathered: then they are folded in, so the stack is saved one update in three.')
    s.set('CacheImg', s.act('nothing', {}, 'Nothing'))
    s.set_number('FoldFrom', 0)
    g = s.if_(variable('N'), GREATER_THAN, number=1)
    s.set('Rebuild', variable('ColDirty'))
    g2 = s.if_positive(variable('Rebuild'))
    s.otherwise(g2)
    s.set_number('Rebuild', 1)
    g3 = s.if_(variable('ColN'), GREATER_THAN, number=0)
    g4 = s.if_positive(s.math(variable('N'), '-', variable('ColN')))
    g5 = s.if_same(field(s, s.text(s.item(variable('Recs'), 'Item At Index', variable('ColN'))), 'key'),
                   variable('ColKey'))
    s.set('CacheImg', s.file(f'{DIR}/rows/col.png', False))
    g6 = s.if_(variable('CacheImg'), HAS_VALUE)
    s.set('Diff', s.math(height(s, variable('CacheImg')), '-', variable('ColH')))
    g7 = s.if_(variable('Diff'), LESS_THAN, number=1)
    g8 = s.if_(variable('Diff'), GREATER_THAN, number=-1)
    s.set_number('Rebuild', 0)
    for group in (g8, g7, g6, g5, g4, g3, g2):
        s.end(group)
    g2 = s.if_positive(variable('Rebuild'))
    s.set('CacheImg', s.act('nothing', {}, 'Nothing'))
    s.set('FoldFrom', s.math(variable('N'), '-', MAX_ROWS))
    s.set_text('PRole', '')
    s.set('PMs', variable('Zero'))
    g3 = s.if_(variable('FoldFrom'), GREATER_THAN, number=1)
    prev = s.text(s.item(variable('Recs'), 'Item At Index', s.math(variable('FoldFrom'), '-', 1)))
    s.set('PRole', field(s, prev, 'role'))
    s.set('PMs', field(s, prev, 'ms'))
    s.otherwise(g3)
    s.set_number('FoldFrom', 1)
    s.end(g3)
    s.otherwise(g2)
    s.set('PRole', variable('ColRole'))
    s.set('PMs', variable('ColMs'))
    g3 = s.if_(s.math(s.math(variable('N'), '-', 1), '-', variable('ColN')), GREATER_THAN, number=FOLD_AT - 1)
    s.set('FoldFrom', s.math(variable('ColN'), '+', 1))
    s.end(g3)
    s.end(g2)
    g2 = s.if_positive(variable('FoldFrom'))
    s.set('Parts', variable('CacheImg'))
    append_pieces(s, 'Parts', variable('FoldFrom'), s.math(variable('N'), '-', 1))
    s.set('CacheImg', s.combine(variable('Parts')))
    s.set('ColH', height(s, variable('CacheImg')))
    g3 = s.if_(variable('ColH'), GREATER_THAN, number=COL_MAX)
    s.set('CacheImg', s.crop(variable('CacheImg'), 0, s.math(variable('ColH'), '-', COL_MAX), W, COL_MAX))
    s.set_number('ColH', COL_MAX)
    s.end(g3)
    s.set('TC0', ms_now(s))
    s.save(variable('CacheImg'), f'{DIR}/rows/col.png')
    s.set_text('ColPerf', ' (save ', s.math(ms_now(s), '-', variable('TC0')), ')')
    s.set('ColN', s.math(variable('N'), '-', 1))
    s.set('ColKey', field(s, variable('CRec'), 'key'))
    s.set('ColMs', s.math(variable('CMs'), '+', 0))
    s.set('ColRole', variable('CRole'))
    s.set_number('Dirty', 1)
    s.end(g2)
    s.otherwise(g)
    s.set_text('ColKey', '')
    s.set_text('ColRole', '')
    for name in ('ColN', 'ColMs', 'ColH'):
        s.set(name, variable('Zero'))
    s.end(g)

    s.set('TStack', ms_now(s))
    s.comment('Then the bubbles after the stack, newest last, your receipt and the typing bubble.')
    s.set('Parts', variable('CacheImg'))
    s.set('PRole', variable('ColRole'))
    s.set('PMs', variable('ColMs'))
    append_pieces(s, 'Parts', s.math(variable('ColN'), '+', 1), variable('N'))
    g = s.if_(variable('NewestRole'), IS, string='me')
    s.comment('Messages’ receipt: "Delivered", then "Read <time>" once your agent is on it.')
    need(s, 'ReceiptCanvas')
    s.set('Receipt', variable('ReceiptCanvas'))
    s.comment('Overlay Text ignores alignment, so the receipt is placed from measured widths to end at your bubble’s edge.')
    g2 = s.if_positive(variable('Waiting'))
    s.set('ReadTime', field(s, variable('Newest'), 'time'))
    measure(s, variable('ReadTime'), depth=1)
    s.set('TimeX', s.round_(s.math(RIGHT, '-', s.math(variable('Units'), '×', M['smallPxPerUnit']))))
    s.set('Receipt', s.overlay_text(variable('Receipt'), variable('ReadTime'), variable('TimeX'),
                                    T['receipt']['gap'], 'time', STAMP))
    s.set('Receipt', s.overlay_text(variable('Receipt'), 'Read',
                                    s.round_(s.math(s.math(variable('TimeX'), '-', M['smallSpace']), '-', M['readW'])),
                                    T['receipt']['gap'], 'day', STAMP))
    s.otherwise(g2)
    s.set('Receipt', s.overlay_text(variable('Receipt'), 'Delivered', round(RIGHT - M['deliveredW']),
                                    T['receipt']['gap'], 'day', STAMP))
    s.end(g2)
    s.append('Parts', variable('Receipt'))
    s.end(g)
    g = s.if_positive(variable('Waiting'))
    g2 = s.if_(variable('NewestRole'), IS, string='me')
    s.append('Parts', s.file(f'{DIR}/typing-turn.png', True))
    s.otherwise(g2)
    s.append('Parts', s.file(f'{DIR}/typing-same.png', True))
    s.end(g2)
    s.end(g)

    s.comment('Placed from the stack’s real height, so nothing is ever squeezed to fit.')
    s.set('Column', s.combine(variable('Parts')))
    s.set('ColumnH', height(s, variable('Column')))
    s.set('Content', s.math(variable('ColumnH'), '-', variable('Below')))
    s.set_number('Overflow', 0)
    s.set('ColY', variable('Top'))
    g = s.if_positive(s.math(variable('Content'), '-', s.math(variable('Bottom'), '-', variable('Top'))))
    s.set_number('Overflow', 1)
    s.set('ColY', s.math(variable('Bottom'), '-', variable('Content')))
    s.end(g)
    g = s.if_positive(s.math(0, '-', variable('ColY')))
    s.comment('The oldest rows start above the screen: trim them off.')
    s.set('Column', s.crop(variable('Column'), 0, s.math(0, '-', variable('ColY')), W,
                           s.math(variable('ColumnH'), '+', variable('ColY'))))
    s.set('ColumnH', s.math(variable('ColumnH'), '+', variable('ColY')))
    s.set_number('ColY', 0)
    s.end(g)
    g = s.if_positive(variable('Overflow'))
    s.comment('Fade the stack into the wall under the clock (the mask’s row r is screen row r − 1000).')
    need(s, 'Blank')
    mask = s.crop(variable('Blank'), 0, s.math(s.math(variable('ColY'), '+', 1000), '-', variable('Shift')), W,
                  variable('ColumnH'))
    s.set('Column', s.mask_with(variable('Column'), mask))
    s.end(g)
    s.set('TCompose', ms_now(s))
    s.set('Img', s.overlay(variable('Wall'), variable('Column'), 0, variable('ColY'), W, variable('ColumnH')))

    s.otherwise(g_any)
    s.comment('A new chat: your agent, quietly, where the first message will land.')
    d = T['empty']['avatar']
    ax = (W - d) // 2
    need(s, 'Clear')
    s.set('Row', s.crop(variable('Clear'), 0, 0, W, 400))
    s.set_text('Initials', '')
    photo = s.file(f'{DIR}/avatar-photo.png', False)
    s.set('Photo', photo)
    g = s.if_(variable('Photo'), HAS_VALUE)
    face = s.mask_ellipse(s.act('image.resize', {'WFImage': attachment(variable('Photo')), 'WFImageResizeWidth': str(d),
                                                 'WFImageResizeHeight': str(d)}, 'Resized Image'))
    s.set('Row', s.overlay(variable('Row'), face, ax, T['empty']['top'], d, d))
    s.otherwise(g)
    s.set('Row', s.overlay(variable('Row'), s.file(f'{DIR}/avatar.png', True), ax, T['empty']['top'], d, d))
    initials = s.item(s.match(variable('Agent'), r'\b\p{L}'), 'First Item')
    s.set('Initials', initials)
    words = s.match(variable('Agent'), r'\b\p{L}')
    g2 = s.if_(s.count(words, 'Items'), GREATER_THAN, number=1)
    s.set_text('Initials', variable('Initials'), s.item(words, 'Last Item'))
    s.end(g2)
    s.set('Initials', s.act('text.changecase', {'text': token_string(variable('Initials')),
                                                'WFCaseType': 'UPPERCASE'}, 'Updated Text'))
    s.end(g)
    s.comment('Overlay Text ignores alignment: measure the initials, name and hint, then centre them by hand.')
    s.set_text('Initials', variable('Initials'))
    # Name and hint first: with a photo there are no initials, and an empty line would shift the counts.
    measure(s, s.text(variable('Agent'), '\n', variable('Hint'), '\n', variable('Initials')), depth=1, keep=True)
    lens = variable('Lens')

    def centred(units, per_unit, box_x, box_w):
        return s.round_(s.math(box_x, '+', s.math(s.math(box_w, '-', s.math(units, '×', per_unit)), '÷', 2)))
    g = s.if_(variable('Photo'), HAS_VALUE)
    s.otherwise(g)
    s.set('Row', s.overlay_text(variable('Row'), variable('Initials'),
                                centred(s.item(lens, 'Last Item'), M['monoPxPerUnit'], ax, d),
                                T['empty']['top'] + round((d - TY['monogram']['pitch']) / 2) + 2, 'monogram',
                                color('FFFFFF')))
    s.end(g)
    s.set('Row', s.overlay_text(variable('Row'), variable('Agent'),
                                centred(s.item(lens, 'First Item'), M['namePxPerUnit'], 0, W),
                                T['empty']['top'] + d + T['empty']['nameGap'], 'name', INK))
    s.set('Row', s.overlay_text(variable('Row'), variable('Hint'),
                                centred(s.item(lens, 'Item At Index', 2), M['hintPxPerUnit'], 0, W),
                                T['empty']['top'] + d + T['empty']['hintGap'], 'hint', STAMP))
    s.set('Img', s.overlay(variable('Wall'), variable('Row'), 0, variable('Top'), W, 400))
    s.end(g_any)


def ms_now(s):
    """Milliseconds into the day (text that Calculate reads): for the timing notes."""
    return s.fmt(s.now(), 'A')


def seconds_of_year(s):
    """Seconds since the start of the year, local time: enough to tell how old a running update is. One Format Date
    writes the sum and one Calculate Expression does it (no part has a leading zero)."""
    return s.act('calculateexpression', {'Input': token_string(s.fmt(s.now(), "D'*86400+'H'*3600+'m'*60+'s"))},
                 'Calculation Result')


def set_wallpaper(s, image, label):
    if QA:   # a QA build only notes the image it would set (a 5 MB save to iCloud would skew the timing)
        s.save(s.text(label, ' ', s.act('getitemtype', {'WFInput': attachment(image)}, 'Type')),
               token_string(f'{DIR}/qa-wallpaper-', label, '.txt'))
        return
    s.act('wallpaper.set', {'WFInput': attachment(image), 'WFWallpaperLocation': ['Lock Screen'],
                            'WFWallpaperShowPreview': False, 'WFWallpaperSmartCrop': False,
                            'WFWallpaperLegibilityBlur': False, 'WFWallpaperPerspectiveZoom': False})


def decide_sync(s):
    """SyncDue (1/0) and SyncStage (why not) for the second pass; Busy when another update is reading Messages."""
    s.comment('After the message is drawn, read Messages for anything the chat is missing (your messages from other '
              'devices, anything iOS skipped): when run by hand; after your agent reacts to something you sent (you '
              'may have sent more since); otherwise at most every 30 seconds, so a burst of replies stays quick.')
    s.set('NowSec', seconds_of_year(s))
    s.set_number('SyncDue', 1)
    g = s.if_positive(variable('Manual'))
    s.otherwise(g)
    s.set_number('Reacted', 0)
    g2 = s.if_(variable('InputType'), IS, string='Text')
    s.otherwise(g2)
    g3 = s.if_matches(s.text(shortcut_input('Content')), TAPBACK_RE)
    s.set_number('Reacted', 1)
    s.end(g3)
    s.end(g2)
    g2 = s.if_positive(variable('Reacted'))
    s.otherwise(g2)
    g2b = s.if_nonempty(variable('SyncedAt'))
    s.set('SyncAge', s.math(variable('NowSec'), '-', variable('SyncedAt')))
    g3 = s.if_(variable('SyncAge'), GREATER_THAN, number=-1)
    g4 = s.if_(variable('SyncAge'), LESS_THAN, number=SYNC['every'])
    s.set_number('SyncDue', 0)
    s.end(g4)
    s.end(g3)
    s.end(g2b)
    s.end(g2)
    s.end(g)
    hours = T['hours']
    s.comment(f'A change of light only redraws the wall: from a Sun automation (dawn, day, dusk or night), or a Time '
              f'of Day automation at {", ".join(f"{h}:00" for h in hours.values())}. It doesn’t read Messages, '
              'which may not answer while the iPhone is locked.')
    g = s.if_positive(variable('Manual'))
    g2 = s.if_matches(variable('Started'), rf'T(?:{"|".join(f"{h:02d}" for h in hours.values())}):0[0-4]:')
    s.set_number('SyncDue', 0)
    s.set_text('SyncStage', 'wall')
    s.end(g2)
    s.end(g)
    g = s.if_positive(variable('LightRun'))
    s.set_number('SyncDue', 0)
    s.set_text('SyncStage', 'wall')
    s.end(g)
    s.comment(f'A read of Messages that started and never finished: if it began under {SYNC["deadSeconds"]} seconds '
              f'ago another update is still on it; if longer, it stopped partway (iOS ended it, or Messages failed), '
              f'so automations skip reading for {SYNC["pauseHours"]} hours rather than fail each time. Running this '
              'shortcut yourself still tries.')
    g = s.if_nonempty(variable('SyncStarted'))
    s.set('SyncAge', s.math(variable('NowSec'), '-', variable('SyncStarted')))
    g2 = s.if_(variable('SyncAge'), LESS_THAN, number=SYNC['deadSeconds'])
    g3 = s.if_(variable('SyncAge'), GREATER_THAN, number=-1)
    s.set_number('Busy', 1)
    s.otherwise(g3)
    s.set_text('SyncStarted', '')   # the clock went back (a new year, travel): forget it
    s.end(g3)
    s.otherwise(g2)
    s.set('PausedUntil', s.math(variable('NowSec'), '+', SYNC['pauseHours'] * 3600))
    s.set_text('SyncStarted', '')
    s.end(g2)
    s.end(g)
    g = s.if_positive(variable('Manual'))
    s.otherwise(g)
    g2 = s.if_nonempty(variable('PausedUntil'))
    s.set('PauseLeft', s.math(variable('PausedUntil'), '-', variable('NowSec')))
    g3 = s.if_positive(variable('PauseLeft'))
    g4 = s.if_(variable('PauseLeft'), LESS_THAN, number=SYNC['pauseHours'] * 3600 + 1)
    s.set_number('SyncDue', 0)
    s.set_text('SyncStage', 'paused')
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)
    g = s.if_positive(variable('Busy'))
    s.set_number('SyncDue', 0)
    s.set_text('SyncStage', 'busy')
    s.end(g)


def set_wallpaper(s, image, label):
    if QA:   # a QA build only notes the image it would set (a 5 MB save to iCloud would skew the timing)
        s.save(s.text(label, ' ', s.act('getitemtype', {'WFInput': attachment(image)}, 'Type')),
               token_string(f'{DIR}/qa-wallpaper-', label, '.txt'))
        return
    s.act('wallpaper.set', {'WFInput': attachment(image), 'WFWallpaperLocation': ['Lock Screen'],
                            'WFWallpaperShowPreview': False, 'WFWallpaperSmartCrop': False,
                            'WFWallpaperLegibilityBlur': False, 'WFWallpaperPerspectiveZoom': False})


def build_lock_screen():
    s = Shortcut()
    s.comment(f'{WALLPAPER_NAME} puts your chat with your agent on the Lock Screen (never the Home Screen). Your '
              f'automations and Talk to Hermes run it; the drawing happens in {RENDERER_NAME}, so design updates '
              'never touch this shortcut.')
    s.comment('update-status.json holds only times and stages, never message text, plus how long each step took '
              '(milliseconds). While one update runs, the next waits for it, so two quick messages can’t overwrite '
              'each other.')
    s.set('T0', ms_now(s))
    started = s.act('format.date', {'WFDate': token_string(s.now()), 'WFDateFormatStyle': 'Custom',
                                    'WFDateFormat': "yyyy-MM-dd'T'HH:mm:ssXXX"}, 'Formatted Date')
    s.set('Started', started)
    s.set_text('InputType', 'None')
    s.set_number('Manual', 1)
    s.set_number('LightRun', 0)
    g = s.if_(shortcut_input(), HAS_VALUE)
    s.set('InputType', s.act('getitemtype', {'WFInput': attachment(shortcut_input())}, 'Type'))
    s.comment('No input: run by hand, or by a Time of Day automation (a time trigger may pass its date instead). A '
              'Sun automation passes dawn, day, dusk or night.')
    g2 = s.if_(variable('InputType'), IS, string='Date')
    s.otherwise(g2)
    s.set_number('Manual', 0)
    g3 = s.if_(variable('InputType'), IS, string='Text')
    g4 = s.if_matches(s.text(shortcut_input()), LIGHT_RE)
    s.set_number('LightRun', 1)
    s.end(g4)
    s.end(g3)
    s.end(g2)
    s.end(g)

    s.set_text('SyncedAt', '')
    s.set_text('SyncStarted', '')
    s.set_text('PausedUntil', '')

    def look():
        """Reads update-status.json: Free is 0 while another update is running (for up to lockSeconds)."""
        s.set_number('Free', 1)
        prior = s.file(f'{DIR}/update-status.json', False)
        g = s.if_(prior, HAS_VALUE)
        state = s.act('detect.dictionary', {'WFInput': attachment(prior)}, 'Dictionary')
        s.set('Prior', state)
        s.set('SyncedAt', s.text(variable('Prior', 'synced_at')))
        s.set('SyncStarted', s.text(variable('Prior', 'sync_started')))
        s.set('PausedUntil', s.text(variable('Prior', 'paused_until')))
        g2 = s.if_(s.text(variable('Prior', 'stage')), BEGINS_WITH, string='running')
        s.set('Age', s.math(seconds_of_year(s), '-', s.text(variable('Prior', 'at'))))
        g3 = s.if_(variable('Age'), GREATER_THAN, number=-1)
        g4 = s.if_(variable('Age'), LESS_THAN, number=SYNC['lockSeconds'])
        s.set_number('Free', 0)
        s.end(g4)
        s.end(g3)
        s.end(g2)
        s.end(g)
    look()
    g = s.if_positive(variable('Free'))
    s.otherwise(g)
    loop = s.repeat(SYNC['lockTries'])
    g2 = s.if_positive(variable('Free'))
    s.otherwise(g2)
    s.act('delay', {'WFDelayTime': 1})
    look()
    s.end(g2)
    s.end_repeat(loop)
    s.end(g)
    s.set('TL', ms_now(s))
    s.set_text('Timing', 'wait ', s.math(variable('TL'), '-', variable('T0')), ' · ')
    s.comment('The last update that didn’t finish (where it stopped, what started it, when), kept until the next one.')
    s.set('LastStop', s.text(variable('Prior', 'last_stop')))
    g = s.if_(s.text(variable('Prior', 'stage')), BEGINS_WITH, string='running')
    s.set_text('LastStop', variable('Prior', 'stage'), ' · ', variable('Prior', 'input_type'), ' · ',
               variable('Prior', 'started_at'))
    s.end(g)
    s.set_text('SyncIn', 'sync')
    g = s.if_positive(variable('Manual'))
    s.set_text('SyncIn', 'sync by hand')
    s.end(g)

    def checkpoint(stage):
        s.save(s.dictionary([('release', RELEASE), ('started_at', variable('Started')), ('stage', stage),
                             ('at', seconds_of_year(s)), ('synced_at', variable('SyncedAt')),
                             ('sync_started', variable('SyncStarted')), ('paused_until', variable('PausedUntil')),
                             ('input_type', variable('InputType')), ('timing', variable('Timing')),
                             ('last_stop', variable('LastStop'))]),
               f'{DIR}/update-status.json')
    checkpoint('running')
    s.set_text('Stage', 'no-change')
    s.set_text('SyncStage', 'not due')
    s.set_number('Busy', 0)
    s.comment('Two passes through one Set Wallpaper: first the message that started this update (or a redraw), '
              'then, when due, what reading Messages added. Run by hand, each step is noted in update-status.json '
              'first, so a stop shows where it happened.')
    loop = s.repeat(2)
    s.set_text('Result', '')
    s.set_text('Pass', 'event')
    s.set('TB', ms_now(s))
    g = s.if_(variable('Repeat Index'), LESS_THAN, number=2)
    s.set('Result', s.act('runworkflow', {'WFWorkflowName': RENDERER_NAME, 'WFInput': attachment(shortcut_input()),
                                          'WFShowWorkflow': False}, 'Shortcut Result'))
    s.otherwise(g)
    s.set_text('Pass', 'sync')
    decide_sync(s)
    s.set('TB', ms_now(s))
    g2 = s.if_positive(variable('SyncDue'))
    s.set('SyncStarted', seconds_of_year(s))
    checkpoint('running: reading Messages')
    s.set('Result', s.act('runworkflow', {'WFWorkflowName': RENDERER_NAME, 'WFInput': attachment(variable('SyncIn')),
                                          'WFShowWorkflow': False}, 'Shortcut Result'))
    s.set('SyncedAt', seconds_of_year(s))
    s.set_text('SyncStarted', '')
    s.set_text('PausedUntil', '')
    s.set_text('SyncStage', 'nothing new')
    s.end(g2)
    s.end(g)
    s.set('TR', ms_now(s))
    s.set_text('Timing', variable('Timing'), variable('Pass'), ' ', s.math(variable('TR'), '-', variable('TB')))
    g = s.if_(s.act('getitemtype', {'WFInput': attachment(variable('Result'))}, 'Type'), IS, string='Image')
    g2 = s.if_positive(variable('Manual'))
    checkpoint('running: setting the wallpaper')
    s.end(g2)
    s.comment('Tap "Wallpaper" below and pick the Lock Screen to draw on: a Photos one (Set Wallpaper can’t replace '
              'Photo Shuffle, Live Photo, People, Weather, Astronomy or color Lock Screens). Keep it set to Lock Screen '
              'only, and keep Show Preview, Crop to Subject, Legibility Blur and Perspective Zoom off.')
    set_wallpaper(s, variable('Result'), variable('Pass'))
    s.set_text('Timing', variable('Timing'), ' + set ', s.math(ms_now(s), '-', variable('TR')))
    g2 = s.if_(variable('Repeat Index'), LESS_THAN, number=2)
    s.set_text('Stage', 'applied')
    s.otherwise(g2)
    s.set_text('SyncStage', 'synced')
    s.end(g2)
    s.end(g)
    s.set_text('Timing', variable('Timing'), ' · ')
    s.end_repeat(loop)
    g = s.if_positive(variable('Busy'))
    s.comment('Another update was reading Messages: keep its progress as it stands now.')
    latest = s.file(f'{DIR}/update-status.json', False)
    g2 = s.if_(latest, HAS_VALUE)
    s.set('Latest', s.act('detect.dictionary', {'WFInput': attachment(latest)}, 'Dictionary'))
    s.set('SyncedAt', s.text(variable('Latest', 'synced_at')))
    s.set('SyncStarted', s.text(variable('Latest', 'sync_started')))
    s.set('PausedUntil', s.text(variable('Latest', 'paused_until')))
    s.end(g2)
    s.end(g)
    s.set_text('Timing', variable('Timing'), 'total ', s.math(ms_now(s), '-', variable('T0')))
    checkpoint(token_string(variable('Stage'), ', ', variable('SyncStage')))
    return workflow(s, glyph=59403, color=4274264319, accepts_input=True)


def build_sender():
    s = Shortcut()
    s.comment(f'{SENDER_NAME}: hold the Action button, talk, tap to stop. The voice note is sent first; then the '
              'Lock Screen shows it, with your words under the waveform once they are transcribed. If transcription '
              'fails, the voice note still shows, as Messages has it.')
    s.set('MyAudio', s.act('recordaudio', {'WFRecordingCompression': 'Normal', 'WFRecordingStart': 'Immediately',
                                           'WFRecordingEnd': 'On Tap'}, 'Recorded Audio'))
    send_index = len(s.actions)
    s.act('sendmessage', {'WFSendMessageContent': token_string(variable('MyAudio')), 'ShowWhenRun': False})
    s.set('Name', s.act('getitemname', {'WFInput': attachment(variable('MyAudio'))}, 'Name'))
    s.comment('Transcription runs on the iPhone and needs Siri or Dictation turned on.')
    words = s.act('com.apple.ShortcutsActions.TranscribeAudioAction', {'audioFile': attachment(variable('MyAudio'))},
                  'Transcribed Audio')
    s.act('runworkflow', {'WFWorkflowName': WALLPAPER_NAME,
                          'WFInput': attachment(s.text('me-audio[', variable('Name'), ']: ', words)),
                          'WFShowWorkflow': False})
    question = {'ActionIndex': send_index, 'Category': 'Parameter', 'ParameterKey': 'WFSendMessageActionRecipients',
                'Text': 'Who should voice notes go to? Pick your agent’s contact.'}
    return workflow(s, glyph=59780, color=4274264319, accepts_input=False, questions=[question])


def workflow(s, glyph, color, accepts_input, questions=()):
    return {
        'WFWorkflowActions': s.actions,
        'WFWorkflowClientVersion': '5037.0.17',
        'WFWorkflowMinimumClientVersion': 900,
        'WFWorkflowMinimumClientVersionString': '900',
        'WFWorkflowIcon': {'WFWorkflowIconGlyphNumber': glyph, 'WFWorkflowIconStartColor': color},
        'WFWorkflowImportQuestions': list(questions),
        'WFWorkflowInputContentItemClasses': [
            'WFAppContentItem', 'WFAppStoreAppContentItem', 'WFArticleContentItem', 'WFContactContentItem',
            'WFDateContentItem', 'WFEmailAddressContentItem', 'WFFolderContentItem', 'WFGenericFileContentItem',
            'WFImageContentItem', 'WFiTunesProductContentItem', 'WFLocationContentItem', 'WFDCMapsLinkContentItem',
            'WFAVAssetContentItem', 'WFPDFContentItem', 'WFPhoneNumberContentItem', 'WFRichTextContentItem',
            'WFSafariWebPageContentItem', 'WFStringContentItem', 'WFURLContentItem',
            'WFMessageContentItem'] if accepts_input else [],
        'WFWorkflowOutputContentItemClasses': [],
        'WFWorkflowTypes': [],
        'WFQuickActionSurfaces': [],
        'WFWorkflowHasShortcutInputVariables': accepts_input,
        'WFWorkflowHasOutputFallback': False,
    }


def explain(workflow):
    """Prints the actions as an indented outline for review."""
    depth = 0
    for action in workflow['WFWorkflowActions']:
        ident = action['WFWorkflowActionIdentifier'].removeprefix('is.workflow.actions.')
        params = action['WFWorkflowActionParameters']
        mode = params.get('WFControlFlowMode')
        if mode in (1, 2):
            depth -= 1
        summary = {k: v for k, v in params.items() if k not in ('UUID', 'GroupingIdentifier')}
        print('  ' * depth + ident, str(summary)[:150])
        if mode in (0, 1):
            depth += 1
    assert depth == 0, f'unbalanced control flow: depth {depth}'


def build_all():
    built = {RENDERER_NAME: build_renderer(), WALLPAPER_NAME: build_lock_screen()}
    if not QA:   # a QA build never records or sends anything
        built[SENDER_NAME] = build_sender()
    return built


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--qa' in args:
        configure(args[args.index('--qa') + 1], args[args.index('--agent') + 1] if '--agent' in args else None)
        if '--debug' in args:
            QA = 'debug'
    out_dir = args[0]
    for name, built in build_all().items():
        path = f'{out_dir}/{name}.unsigned.shortcut'
        with open(path, 'wb') as f:
            plistlib.dump(built, f, fmt=plistlib.FMT_BINARY)
        print(f'{len(built["WFWorkflowActions"])} actions -> {path}')
        if '--explain' in args:
            explain(built)
