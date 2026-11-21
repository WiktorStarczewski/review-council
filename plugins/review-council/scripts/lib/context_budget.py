"""Context-window arithmetic shared by the Codex launch check and evidence preparation.

A seat holds its prepared reads, the turns that delivered them and its assignment prompt in one
context before it reviews anything. The launch check measures that from the staged reads; evidence
preparation projects it from the artifacts it is about to publish, so an assignment no seat's
window can hold is split or refused before any provider launches.
"""
import json
import math
import os
import re

# The context a staged seat holds before its first review turn, fitted on completed Codex streams
# (projected over actual: median 1.10, minimum 0.85). Review turns then added a median 33K and at
# most 126K tokens, so staging may fill only 55% of the model's usable window.
CONTEXT_BASE_TOKENS = 17_000
CONTEXT_READ_TOKENS = 120
CONTEXT_STAGE_TURN_TOKENS = 300
READ_BYTES_PER_TOKEN = 2.8
PACKET_BYTES_PER_TOKEN = 2.4
PROMPT_BYTES_PER_TOKEN = 3.0
CONTEXT_SHARE_PERCENT = 55
RAISED_WINDOW_SWITCH = 'REVIEW_COUNCIL_CODEX_MAX_CONTEXT_WINDOW'
# A Claude seat has no catalog row; its window is a named constant held to the same share.
CLAUDE_CONTEXT_WINDOW = 1_000_000
# The compacted assignment prompt, fitted on completed PR 2144 prompts: a fixed part plus one
# rendered line per prepared read (projected over actual: 0.98 to 1.07).
PROMPT_BASE_TOKENS = 11_100
PROMPT_TOKENS_PER_READ = 151
PROJECTION_HEADROOM_PERCENT = 10
INDEX_READ_BYTES = 16 * 1024
HEX_RUN = re.compile(rb'[0-9a-f]{32,}')
IDENTITY_LINE = re.compile(
    rb'(?:[0-9]+\. )?(?:Required source range: |Patch-proven source range: |Required source segment '
    rb'|Assigned patch chunk |Canonical assigned patch: '
    rb'|(?:Required|Optional) post-index original-source target: )')
IDENTITY_HASH = re.compile(
    rb' (?:tree|blob) [0-9a-f]{40}(?:[0-9a-f]{24})?(?![0-9a-f])'
    rb'| (?:content )?SHA-256 [0-9a-f]{64}(?![0-9a-f])')
REASON_HASH = re.compile(rb'("[a-z-]+):[0-9a-f]{64}"')


def compact_review_prompt(raw):
    """The assignment prompt a Codex seat reads in review turn 1, without the tree, blob and
    content hashes on its evidence lines; the audit and the stage plan keep the receipted file."""
    lines = raw.split(b'\n')
    for index, line in enumerate(lines):
        if IDENTITY_LINE.match(line):
            lines[index] = REASON_HASH.sub(rb'\1"', IDENTITY_HASH.sub(b'', line))
    return b'\n'.join(lines)


def context_tokens(raw, bytes_per_token):
    """Estimated tokens for text; a hash or other long hex run costs about one token per byte."""
    hex_bytes = sum(len(run) for run in HEX_RUN.findall(raw))
    return (len(raw) - hex_bytes) / bytes_per_token + hex_bytes


def catalog_window(model):
    """((context window, effective percent, larger max_context_window or None), None) from the
    model's row in the Codex model cache that the roster reads, or (None, why it is unknown)."""
    from roster import codex_catalog_path
    path = codex_catalog_path()
    try:
        with open(path, encoding='utf-8') as source:
            models = json.load(source).get('models')
    except (OSError, UnicodeError, ValueError, AttributeError):
        return None, f'no readable Codex model cache at {path} for {model}'
    rows = [row for row in models if isinstance(row, dict) and row.get('slug') == model] \
        if isinstance(models, list) else []
    if len(rows) != 1:
        return None, f'{model} is not listed once in {path}'
    window = rows[0].get('context_window')
    percent = rows[0].get('effective_context_window_percent')
    if (type(window) is not int or window <= 0 or type(percent) not in (int, float)
            or not 0 < percent <= 100):
        return None, f'{model} has no valid context window in {path}'
    maximum = rows[0].get('max_context_window')
    return (window, percent, maximum if type(maximum) is int and maximum > window else None), None


def model_limits(model):
    """({'usable', 'limit', 'maximum', 'raised'}, None) or (None, why the window is unknown).
    'raised' is the limit at the catalog's larger window, or None when the model has none or the
    switch is set to anything but empty or 1."""
    known, unknown = catalog_window(model)
    if unknown:
        return None, unknown
    window, percent, maximum = known
    usable = math.floor(window * percent / 100)
    raised = None
    if maximum is not None and os.environ.get(RAISED_WINDOW_SWITCH, '1') in ('', '1'):
        raised = math.floor(maximum * percent / 100) * CONTEXT_SHARE_PERCENT // 100
    return {'usable': usable, 'limit': usable * CONTEXT_SHARE_PERCENT // 100,
            'maximum': maximum, 'raised': raised}, None


def seat_budget_tokens(adapter, model):
    """The context a seat may fill before review, or None when its window is unknown (the launch
    check fails open the same way, so preparation never refuses what a seat could still run)."""
    if adapter == 'codex' and isinstance(model, str):
        limits, _ = model_limits(model)
        return None if limits is None else (limits['raised'] or limits['limit'])
    if adapter == 'claude':
        return CLAUDE_CONTEXT_WINDOW * CONTEXT_SHARE_PERCENT // 100
    return None


def read_tokens(size, kind):
    """What one prepared read costs: its content plus the turn that delivered it."""
    rate = PACKET_BYTES_PER_TOKEN if kind == 'packet' else READ_BYTES_PER_TOKEN
    return size / rate + CONTEXT_READ_TOKENS + CONTEXT_STAGE_TURN_TOKENS + PROMPT_TOKENS_PER_READ


def fixed_context_tokens():
    """The cost every assignment carries: the base context, the prompt and the evidence index."""
    return (CONTEXT_BASE_TOKENS + PROMPT_BASE_TOKENS + read_tokens(INDEX_READ_BYTES, 'patch'))


def projected_context_tokens(patch_reads, packet_reads, segment_reads, headroom=True):
    """Tokens an assignment holds before review, from the byte size of each prepared read: patch
    chunks or windows, source packets and required source segments. Every read is counted as its
    own turn, an upper bound on the grouped turns the stager plans."""
    total = fixed_context_tokens()
    total += sum(read_tokens(size, 'patch') for size in patch_reads)
    total += sum(read_tokens(size, 'packet') for size in packet_reads)
    total += sum(read_tokens(size, 'segment') for size in segment_reads)
    if headroom:
        total = total * (100 + PROJECTION_HEADROOM_PERCENT) / 100
    return math.ceil(total)
