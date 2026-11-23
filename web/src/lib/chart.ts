/** Axis maths for the price chart. Pure functions, unit-tested. */

/** A "nice" step (1, 2, 2.5 or 5 x 10^n) giving about `target` ticks. */
export function niceStep(span: number, target = 4): number {
  if (span <= 0) return 1;
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return step * mag;
}

/** Honest y-domain: always includes zero, so bar lengths are comparable and negative
 *  prices sit visibly below the baseline. */
export function yDomain(values: number[]): { min: number; max: number; ticks: number[] } {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const step = niceStep(hi - lo || 1);
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step || step;
  const ticks: number[] = [];
  for (let t = min; t <= max + step / 2; t += step) ticks.push(Math.round(t * 1000) / 1000);
  return { min, max, ticks };
}

/** Indexes of the intervals inside [startUtc, endUtc). */
export function windowIndexes(starts: string[], startUtc?: string, endUtc?: string): Set<number> {
  const out = new Set<number>();
  if (!startUtc || !endUtc) return out;
  starts.forEach((s, i) => {
    if (s >= startUtc && s < endUtc) out.add(i);
  });
  return out;
}
