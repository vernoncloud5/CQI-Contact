#!/usr/bin/env python3
"""Attach local files to an existing Gmail draft through Vernon's CQI Attach Helper web app.

Usage:
  python3 .claude/tools/attach-to-draft.py <draftId> <file> [<file> ...]
  python3 .claude/tools/attach-to-draft.py --list <draftId>

Needs env vars CQI_ATTACH_URL (the web app /exec URL) and CQI_ATTACH_KEY.
Keeps the draft's body, signature, recipients and subject. Skips files already attached.
Prints one JSON line with the draft's attachment names afterwards.
"""
import base64, json, mimetypes, os, subprocess, sys

url = os.environ.get('CQI_ATTACH_URL')
key = os.environ.get('CQI_ATTACH_KEY')
if not url or not key:
    print(json.dumps({'ok': False, 'error': 'set CQI_ATTACH_URL and CQI_ATTACH_KEY'}))
    sys.exit(2)

args = sys.argv[1:]
if not args:
    print(__doc__)
    sys.exit(2)
if args[0] == '--list':
    payload = {'key': key, 'action': 'list', 'draftId': args[1]}
else:
    files = []
    for p in args[1:]:
        with open(p, 'rb') as fh:
            files.append({'name': os.path.basename(p),
                          'mimeType': mimetypes.guess_type(p)[0] or 'application/octet-stream',
                          'b64': base64.b64encode(fh.read()).decode()})
    payload = {'key': key, 'action': 'attach', 'draftId': args[0], 'files': files}

# Apps Script answers a POST with a redirect; curl -L follows it to fetch the result.
res = subprocess.run(['curl', '-sS', '-L', '--max-time', '300', '-H', 'Content-Type: application/json',
                      '--data-binary', '@-', url], input=json.dumps(payload).encode(), capture_output=True)
print(res.stdout.decode().strip() or json.dumps({'ok': False, 'error': res.stderr.decode()[:300]}))
