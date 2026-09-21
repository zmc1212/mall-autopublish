export default function cn(
  ...parts: Array<string | false | null | undefined | Record<string, boolean>>
): string {
  const classes: string[] = [];
  for (const part of parts) {
    if (!part) continue;
    if (typeof part === "string") {
      classes.push(part);
      continue;
    }
    for (const [key, on] of Object.entries(part)) {
      if (on) classes.push(key);
    }
  }
  return classes.join(" ");
}
