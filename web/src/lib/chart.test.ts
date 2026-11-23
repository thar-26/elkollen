import { describe, expect, it } from "vitest";

import { niceStep, windowIndexes, yDomain } from "./chart";

describe("yDomain", () => {
  it("always includes zero, so bar lengths are honest", () => {
    const d = yDomain([114.6, 158.4, 216.3]);
    expect(d.min).toBe(0);
    expect(d.max).toBeGreaterThanOrEqual(216.3);
    expect(d.ticks[0]).toBe(0);
  });

  it("puts negative prices below the baseline", () => {
    const d = yDomain([-104.3, -2.2, 4.4, 30]);
    expect(d.min).toBeLessThanOrEqual(-104.3);
    expect(d.max).toBeGreaterThanOrEqual(30);
    expect(d.ticks).toContain(0);
  });

  it("handles a flat day of zero prices", () => {
    const d = yDomain([0, 0, 0]);
    expect(d.max).toBeGreaterThan(d.min);
  });
});

describe("niceStep", () => {
  it.each([
    [216, 100], // 216 / 4 = 54 -> next nice step is 100 (ticks 0, 100, 200, 300)
    [1000, 250],
    [9, 2.5],
  ])("span %d gives step %d", (span, step) => {
    expect(niceStep(span)).toBe(step);
  });
});

describe("windowIndexes", () => {
  const starts = [
    "2026-11-24T00:00:00",
    "2026-11-24T00:15:00",
    "2026-11-24T00:30:00",
    "2026-11-24T00:45:00",
  ];

  it("selects the quarters inside [start, end)", () => {
    expect([...windowIndexes(starts, "2026-11-24T00:15:00", "2026-11-24T00:45:00")]).toEqual([1, 2]);
  });

  it("is empty without a window", () => {
    expect(windowIndexes(starts).size).toBe(0);
  });
});
