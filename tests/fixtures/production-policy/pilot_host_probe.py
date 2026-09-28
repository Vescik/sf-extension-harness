"""Disposable host protocol experiment. Never used by production hooks or as consent."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ASK_COMMAND = 'sf data query -o unclassified --query SELECT'
LATEST_COMMAND = 'sf project deploy report --use-most-recent'
EXACT_COMMAND = 'sf project deploy report --job-id 0Af000000000001AAA --target-org prod-copy'


def main():
    # Refuse outside a deliberately generated synthetic probe. This is not a CLI runner.
    marker = json.loads((ROOT / 'pilot-mode.json').read_text())
    mode = marker.get('hostProbe')
    if mode not in ('ask', 'rewrite') or not (ROOT / 'bin/sf').is_file():
        raise ValueError('Not a disposable host protocol probe')
    event = json.load(sys.stdin)
    inputs = event.get('tool_input', {})
    command = inputs.get('command') if isinstance(inputs, dict) else None
    record = {'event': event.get('hook_event_name'), 'toolUseId': event.get('tool_use_id'),
              'eventFields': sorted(event), 'inputFields': sorted(inputs) if isinstance(inputs, dict) else [],
              'inputSha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()}
    with (ROOT / '.cache/host-probe.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record) + '\n')
    if event.get('hook_event_name') == 'PostToolUse':
        print(json.dumps({'continue': True}))
        return
    response = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': 'Synthetic probe accepts only its exact test command.'}
    if event.get('tool_use_id') and command == 'sf --version':
        response['permissionDecision'] = 'allow'
    elif event.get('tool_use_id') and mode == 'ask' and command == ASK_COMMAND:
        response.update(permissionDecision='ask', permissionDecisionReason=
            'Synthetic authenticated Org ID 00D000000000009: dev, uat, stage or prod for this exact command only? '
            'Observe whether the host provides a structured answer. An Approve button is not an environment answer.')
    elif event.get('tool_use_id') and mode == 'rewrite' and command in (LATEST_COMMAND, EXACT_COMMAND):
        response.update(permissionDecision='ask', permissionDecisionReason=
            'Synthetic probe: execution must receive concrete job 0Af000000000001AAA and org prod-copy.',
            updatedInput={**inputs, 'command': EXACT_COMMAND})
    print(json.dumps({'hookSpecificOutput': response}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'continue': False, 'hookSpecificOutput': {'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny', 'permissionDecisionReason': 'Host probe failed.'}}))
