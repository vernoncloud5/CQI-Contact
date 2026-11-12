// CQI Attach Helper: a Google Apps Script web app that adds files to an existing
// Gmail draft while keeping its body, signature, recipients and subject.
// Vernon deploys it once from script.google.com (Execute as: Me, Access: Anyone).
// The agent calls it with .claude/tools/attach-to-draft.py.
// Replace PUT_KEY_HERE with the private key before deploying. Never commit the real key.

var KEY = 'PUT_KEY_HERE';

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents);
    if (req.key !== KEY) return out({ ok: false, error: 'bad key' });

    if (req.action === 'list') {
      var d0 = GmailApp.getDraft(req.draftId);
      var m0 = d0.getMessage();
      return out({ ok: true, to: m0.getTo(), subject: m0.getSubject(),
        attachments: m0.getAttachments().map(function (a) { return a.getName(); }) });
    }

    // action: attach (default)
    var draft = GmailApp.getDraft(req.draftId);
    var msg = draft.getMessage();
    var blobs = msg.getAttachments();
    var have = blobs.map(function (a) { return a.getName(); });
    (req.files || []).forEach(function (f) {
      if (have.indexOf(f.name) > -1) return; // already attached, skip
      blobs.push(Utilities.newBlob(Utilities.base64Decode(f.b64), f.mimeType || 'application/pdf', f.name));
    });
    var opts = { htmlBody: msg.getBody(), attachments: blobs };
    if (msg.getCc()) opts.cc = msg.getCc();
    if (msg.getBcc()) opts.bcc = msg.getBcc();
    draft.update(msg.getTo(), msg.getSubject(), msg.getPlainBody(), opts);

    var after = GmailApp.getDraft(draft.getId()).getMessage();
    return out({ ok: true, draftId: draft.getId(),
      attachments: after.getAttachments().map(function (a) { return a.getName(); }),
      signature: after.getBody().indexOf('gmail_signature') > -1 });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function out(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
