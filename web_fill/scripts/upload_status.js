async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const frame = pictureSpaceFrame() || sucaiFrame();
  const pacing = await readUploadPacingState();
  const observedAtMs = Date.now();
  return JSON.stringify({
    observedAtMs,
    href: page.url().split('?')[0],
    hasPicker: !!frame,
    securityChallenge: await securityChallengeReason(),
    status: await collectUploadStatus(frame, PAYLOAD.names || []),
    pacing,
    cooldownRemainingMs: Math.max(0, (Number(pacing.nextAllowedAt) || 0) - observedAtMs),
  });
}
