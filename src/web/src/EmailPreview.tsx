/** Exact stored email in an isolated, non-interactive document, never the app DOM. */
export function EmailPreview({ content }: { content: string }) {
  const policy = "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'none'; font-src 'none'; connect-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
  const document = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${policy}"></head><body>${content}</body></html>`;
  return <section><h5>Email layout preview</h5><p className="iq-muted">Exact stored HTML, isolated for inspection. Links and interaction are disabled here; email-client rendering may vary.</p>
    <iframe title="Approved email layout preview" sandbox="" inert referrerPolicy="no-referrer" tabIndex={-1} srcDoc={document}
      style={{ width: '100%', height: '900px', border: '1px solid #dbe5ec', pointerEvents: 'none' }} />
  </section>;
}
