export type Area = "SE1" | "SE2" | "SE3" | "SE4";
export const AREAS: Area[] = ["SE1", "SE2", "SE3", "SE4"];

export interface Interval {
  start_utc: string;
  end_utc: string;
  start_local: string;
  price_ore_per_kwh: number;
  upsampled_from_hourly: boolean;
}

export interface PricesResult {
  data: {
    unit: string;
    summary: {
      min_ore_per_kwh: number;
      avg_ore_per_kwh: number;
      max_ore_per_kwh: number;
      n_intervals: number;
      n_negative: number;
    } | null;
    intervals: Interval[];
  };
  notes: string[];
}

export interface Window {
  start_utc: string;
  end_utc: string;
  start_local: string;
  avg_ore_per_kwh: number;
}

export interface WindowResult {
  data: {
    duration_minutes: number;
    cheapest: Window | null;
    dearest: Window | null;
    day_avg_ore_per_kwh: number | null;
    saving_vs_day_avg_ore_per_kwh?: number;
    saving_vs_dearest_ore_per_kwh?: number;
  };
}

export interface Device {
  id: "dishwasher" | "washer" | "car";
  minutes: number;
}

export const DEVICES: Device[] = [
  { id: "dishwasher", minutes: 120 },
  { id: "washer", minutes: 180 },
  { id: "car", minutes: 240 },
];

export interface DayData {
  date: string;
  prices: PricesResult | null;
  windows: Record<number, WindowResult | null>;
}

export interface ToolCallTrace {
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  result: unknown;
}

export interface ChatAnswer {
  answer: string;
  tool_calls: ToolCallTrace[];
  grounding: { numbers_checked: number; ungrounded: string[]; unverified_dates: string[]; ok: boolean };
  model: string;
  error?: string;
}
