import { expect, it } from "vitest";
import { dailyBars, speakingBars, weeklyBars } from "./progressCharts";

const TODAY = new Date(2026, 10, 14, 10); // Saturday 14 Nov 2026; its week starts Monday the 9th

it("buckets actions by day and by Monday-to-Sunday week", () => {
  const days = [{ date: "2026-11-14", attempts: 2 }, { date: "2026-11-09", attempts: 3 }, { date: "2026-11-08", attempts: 4 }];
  const daily = dailyBars(days, 7, TODAY);
  expect(daily.map(bar => bar.key)[0]).toBe("2026-11-08");
  expect(daily.map(bar => bar.value)).toEqual([4, 3, 0, 0, 0, 0, 2]);
  const weekly = weeklyBars(days, 3, TODAY);
  expect(weekly.map(bar => [bar.key, bar.value])).toEqual([["2026-10-26", 0], ["2026-11-02", 4], ["2026-11-09", 5]]);
});

it("places the server's speaking weeks and fills the empty ones with zero", () => {
  const bars = speakingBars([{ week_start: "2026-11-02", minutes: 6.5 }], 3, TODAY);
  expect(bars.map(bar => bar.value)).toEqual([0, 6.5, 0]);
  expect(bars[2].key).toBe("2026-11-09");
});
