#!/usr/bin/env python3
"""Structural contracts of the generated shortcuts, checked without running anything: balanced control flow, outputs
used only after their actions, loop variables named for their depth, the voice shortcut sending before anything can
fail, the wallpaper set on the Lock Screen only with every preview option off, nothing ever deleted, and QA builds
that can't send messages or touch a wallpaper."""
import importlib
import re

import build_shortcut


def actions(w):
    return w['WFWorkflowActions']


def ident(a):
    return a['WFWorkflowActionIdentifier'].removeprefix('is.workflow.actions.')


def check_graph(w):
    seen, stack, loops = set(), [], []

    def refs(v, depth):
        if isinstance(v, dict):
            if v.get('Type') == 'ActionOutput':
                assert v['OutputUUID'] in seen, f"{v['OutputName']} is used before its action"
            if v.get('Type') == 'Variable':
                m = re.fullmatch(r'Repeat (?:Item|Index)(?: (\d+))?', v.get('VariableName', ''))
                if m:
                    assert int(m.group(1) or 1) <= depth, f"{v['VariableName']} used at loop depth {depth}"
            for item in v.values():
                refs(item, depth)
        elif isinstance(v, list):
            for item in v:
                refs(item, depth)
    for a in actions(w):
        p = a['WFWorkflowActionParameters']
        refs(p, len(loops))
        if 'UUID' in p and p.get('WFControlFlowMode') is None:
            assert p['UUID'] not in seen, 'duplicate output ID'
            seen.add(p['UUID'])
        if 'WFControlFlowMode' in p:
            mode, group = p['WFControlFlowMode'], p['GroupingIdentifier']
            if mode == 0:
                stack.append(group)
                if ident(a).startswith('repeat'):
                    loops.append(group)
            else:
                assert stack and stack[-1] == group, 'unbalanced control flow'
                if mode == 2:
                    stack.pop()
                    if loops and loops[-1] == group:
                        loops.pop()
    assert not stack
    for question in w['WFWorkflowImportQuestions']:
        assert 0 <= question['ActionIndex'] < len(actions(w))
        params = actions(w)[question['ActionIndex']]['WFWorkflowActionParameters']
        assert question['ParameterKey'] in params or question['ParameterKey'] == 'WFSendMessageActionRecipients'


TEXT_ACTIONS = {'gettext', 'text.replace', 'text.match', 'text.changecase', 'text.trimwhitespace', 'format.date',
                'getitemfromlist', 'getvalueforkey', 'getitemtype', 'getitemname', 'documentpicker.open'}
NUMBER_ACTIONS = {'math', 'number', 'count', 'round'}


def check_number_comparisons(w):
    """Shortcuts offers "is greater/less than" only on numbers: every variable or output compared that way must only
    ever hold a number (a Calculate, Count, Number, Round, or a loop index)."""
    by_uuid = {a['WFWorkflowActionParameters'].get('UUID'): ident(a) for a in actions(w)}
    producers = {}
    for a in actions(w):
        p = a['WFWorkflowActionParameters']
        if ident(a) == 'setvariable':
            src = p['WFInput']['Value']
            kind = by_uuid.get(src.get('OutputUUID')) if src.get('Type') == 'ActionOutput' else (
                'number' if re.fullmatch(r'Repeat Index(?: \d+)?', src.get('VariableName', '')) else ('var', src.get('VariableName')))
            producers.setdefault(p['WFVariableName'], []).append(kind)

    def numeric(kind, seen=()):
        if kind in NUMBER_ACTIONS or kind == 'number':
            return True
        if isinstance(kind, tuple):
            name = kind[1]
            if name in seen:   # a copy back and forth adds nothing new
                return True
            return all(numeric(k, seen + (name,)) for k in producers.get(name, ['?']))
        return False
    for i, a in enumerate(actions(w)):
        p = a['WFWorkflowActionParameters']
        if ident(a) == 'conditional' and p.get('WFControlFlowMode') == 0 and p['WFCondition'] in (0, 2):
            subject = p['WFInput']['Variable']['Value']
            if subject.get('Type') == 'ActionOutput':
                kind = by_uuid[subject['OutputUUID']]
            elif re.fullmatch(r'Repeat Index(?: \d+)?', subject.get('VariableName', '')):
                kind = 'number'
            else:
                kind = ('var', subject.get('VariableName'))
            assert numeric(kind), f'action {i}: "is greater/less than" on {kind}, which may be text'
        if ident(a) == 'conditional' and p.get('WFControlFlowMode') == 0:
            subject = p['WFInput']['Variable']['Value']
            raw = (subject.get('Type') == 'ActionOutput' and by_uuid.get(subject['OutputUUID']) == 'getitemfromlist') or \
                re.fullmatch(r'Repeat Item(?: \d+)?', subject.get('VariableName', '')) or \
                (subject.get('Type') == 'Variable' and producers.get(subject.get('VariableName')) and
                 any(k == ('var', 'Repeat Item') or k == 'getitemfromlist' for k in producers[subject['VariableName']]))
            assert not raw, f'action {i}: If tests a list item directly; make it text first'
        if ident(a) == 'conditional' and p.get('WFControlFlowMode') == 0 and p['WFCondition'] in (4, 8, 99):
            subject = p['WFInput']['Variable']['Value']
            kind = by_uuid.get(subject.get('OutputUUID')) if subject.get('Type') == 'ActionOutput' else (
                'var', subject.get('VariableName'))
            assert not (kind in NUMBER_ACTIONS or (isinstance(kind, tuple) and producers.get(kind[1]) and
                                                   all(numeric(k) for k in producers[kind[1]]))), \
                f'action {i}: a text condition on {kind}, which is a number'


def check(built, qa):
    renderer, wallpaper = built[build_shortcut.RENDERER_NAME], built[build_shortcut.WALLPAPER_NAME]
    for w in built.values():
        check_graph(w)
        check_number_comparisons(w)
        assert not any(re.search(r'delete', ident(a), re.I) for a in actions(w)), 'nothing may be deleted'
        paths = [a['WFWorkflowActionParameters'].get('WFFileDestinationPath') for a in actions(w)
                 if ident(a) == 'documentpicker.save']
        for path in paths:
            text = path if isinstance(path, str) else path['Value']['string']
            assert text.startswith(f'{build_shortcut.DIR}/'), f'saves outside the folder: {text}'
    sets = [a['WFWorkflowActionParameters'] for a in actions(wallpaper) if ident(a) == 'wallpaper.set']
    if qa:
        assert not sets, 'a QA build must not set a wallpaper'
        assert build_shortcut.SENDER_NAME not in built, 'a QA build must not record or send'
        assert not renderer['WFWorkflowImportQuestions']
    else:
        assert len(sets) == 1, 'one Set Wallpaper action, so there is one Lock Screen to pick'
        for p in sets:
            assert p['WFWallpaperLocation'] == ['Lock Screen']
            assert not any(p[k] for k in ('WFWallpaperShowPreview', 'WFWallpaperSmartCrop', 'WFWallpaperLegibilityBlur',
                                          'WFWallpaperPerspectiveZoom'))
        sender = built[build_shortcut.SENDER_NAME]
        order = [ident(a) for a in actions(sender)]
        assert order.index('sendmessage') < order.index('com.apple.ShortcutsActions.TranscribeAudioAction') < \
            order.index('runworkflow'), 'the voice note is sent before anything that could fail'
        assert sender['WFWorkflowImportQuestions'][0]['ActionIndex'] == order.index('sendmessage')
        runs = [a['WFWorkflowActionParameters']['WFWorkflowName'] for a in actions(sender) if ident(a) == 'runworkflow']
        assert runs == [build_shortcut.WALLPAPER_NAME]
    runs = [a['WFWorkflowActionParameters']['WFWorkflowName'] for a in actions(wallpaper) if ident(a) == 'runworkflow']
    assert runs == [build_shortcut.RENDERER_NAME] * 2, 'the update runs the renderer, then reads Messages'
    finds = [a for a in actions(renderer) if a['WFWorkflowActionIdentifier'] == 'com.apple.MobileSMS.MessageEntity']
    assert finds and all(a['WFWorkflowActionParameters']['WFContentItemLimitEnabled'] for a in finds), \
        'every Messages read is limited'


check(build_shortcut.build_all(), qa=False)
build_shortcut.configure('Hermes-QA-check', 'Hermes')
check(build_shortcut.build_all(), qa=True)
importlib.reload(build_shortcut)
print('Structure, voice order, Lock Screen-only, no deletes, folder-only saves and QA safety checks passed.')
