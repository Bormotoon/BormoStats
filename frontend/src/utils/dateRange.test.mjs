import test from 'node:test';
import assert from 'node:assert/strict';
import { monthDays, monthStart, presetRange, shiftDay } from './dateRange.js';

test('week presets start on Monday and cross year boundaries', () => {
  assert.deepEqual(presetRange('week', '2026-01-01'), ['2025-12-29', '2026-01-01']);
  assert.deepEqual(presetRange('previousWeek', '2026-01-01'), ['2025-12-22', '2025-12-28']);
  assert.deepEqual(presetRange('week', '2026-10-26'), ['2026-10-26', '2026-10-26']);
});
test('month presets handle leap years and inclusive day counts', () => {
  assert.deepEqual(presetRange('previousMonth', '2024-03-10'), ['2024-02-01', '2024-02-29']);
  assert.deepEqual(presetRange(30, '2026-10-29'), ['2026-09-30', '2026-10-29']);
  assert.deepEqual(presetRange(1, '2026-10-29'), ['2026-10-29', '2026-10-29']);
  assert.deepEqual(presetRange('quarter', '2026-01-31'), ['2025-11-01', '2026-01-31']);
});
test('calendar grids start on Monday and include every day of six-week months', () => {
  const days = monthDays('2026-03-01');
  assert.equal(days.length, 42);
  assert.equal(days[0], '2026-02-23');
  assert.equal(days.at(-1), '2026-04-05');
  assert.equal(monthStart('2026-01-31', -1), '2025-12-01');
  assert.equal(shiftDay('2024-03-01', -1), '2024-02-29');
});
