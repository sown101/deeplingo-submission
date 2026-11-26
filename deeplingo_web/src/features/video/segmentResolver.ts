// Precomputes non-overlapping active intervals for transcript synchronization.
// Interval semantics: start_ms <= position < end_ms.
// Overlap policy: latest start wins; equal starts use highest sequence.
// A complete tie uses the earlier list index (stable). Lookup is O(log N).

export interface TimedSegment {
  sequence: number;
  start_ms: number;
  end_ms: number;
}

export class SegmentResolver<T extends TimedSegment> {
  private readonly times: number[] = [];
  private readonly indices: (T | null)[] = [];

  constructor(segments: readonly T[]) {
    const events = new Map<number, Array<{ index: number; opens: boolean }>>();
    segments.forEach((segment, index) => {
      if (segment.start_ms < 0 || segment.end_ms <= segment.start_ms) return;
      pushEvent(events, segment.start_ms, { index, opens: true });
      pushEvent(events, segment.end_ms, { index, opens: false });
    });
    const times = [...events.keys()].sort((a, b) => a - b);
    // Active set ordered by (start, sequence, reversed index); the winner is
    // the LAST element. A complete tie keeps the stable earlier list index.
    const indexed = segments.map((segment, index) => ({ segment, index }));
    const byPriority = (
      a: { segment: T; index: number },
      b: { segment: T; index: number },
    ): number => {
      if (a.segment.start_ms !== b.segment.start_ms) return a.segment.start_ms - b.segment.start_ms;
      if (a.segment.sequence !== b.segment.sequence) return a.segment.sequence - b.segment.sequence;
      return b.index - a.index;
    };
    const active = new SortedActiveSet(byPriority);
    for (const time of times) {
      for (const event of events.get(time)!) {
        if (event.opens) active.add(indexed[event.index]);
        else active.remove(indexed[event.index]);
      }
      const winner = active.isEmpty ? null : active.last();
      this.times.push(time);
      this.indices.push(winner ? winner.segment : null);
    }
  }

  resolve(positionMs: number): T | null {
    if (this.times.length === 0) return null;
    let low = 0;
    let high = this.times.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (this.times[mid] <= positionMs) low = mid + 1;
      else high = mid;
    }
    return low === 0 ? null : this.indices[low - 1];
  }
}

function pushEvent<T>(map: Map<number, T[]>, time: number, value: T): void {
  const list = map.get(time);
  if (list) list.push(value);
  else map.set(time, [value]);
}

class SortedActiveSet<T> {
  private items: T[] = [];

  constructor(private readonly compare: (a: T, b: T) => number) {}

  get isEmpty(): boolean {
    return this.items.length === 0;
  }

  add(item: T): void {
    let low = 0;
    let high = this.items.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (this.compare(this.items[mid], item) <= 0) low = mid + 1;
      else high = mid;
    }
    this.items.splice(low, 0, item);
  }

  remove(item: T): void {
    const index = this.items.findIndex((candidate) => candidate === item);
    if (index >= 0) this.items.splice(index, 1);
  }

  last(): T {
    return this.items[this.items.length - 1];
  }
}
