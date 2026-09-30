async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const files = PAYLOAD.files || [];
  // This fallback is also called by paths without an upload policy. Never
  // silently turn those calls into a concurrent multi-file upload.
  const policy = { ...PAYLOAD, uploadBatchSize: Number(PAYLOAD.uploadBatchSize) > 0
    ? Number(PAYLOAD.uploadBatchSize) : 1 };
  return JSON.stringify(await finishLocalUpload(sucaiFrame() || wangpuFrame(), files, files.map(fileBase), policy));
}
