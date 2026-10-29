// Calendar arithmetic uses UTC dates so DST and the computer's timezone cannot shift a day.
export const dayDate = (iso) => new Date(`${iso}T00:00:00Z`);
export const dayIso = (date) => date.toISOString().slice(0, 10);
export function shiftDay(iso, days) {
  const date = dayDate(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return dayIso(date);
}
export function monthStart(iso, offset = 0) {
  const date = dayDate(iso);
  return dayIso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + offset, 1)));
}
export function monthDays(month) {
  const start = dayDate(month);
  const offset = (start.getUTCDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => shiftDay(month, i - offset));
}
export function presetRange(preset, today) {
  const monday = shiftDay(today, -((dayDate(today).getUTCDay() + 6) % 7));
  switch (preset) {
    case 'yesterday': return [shiftDay(today, -1), shiftDay(today, -1)];
    case 'week': return [monday, today];
    case 'previousWeek': return [shiftDay(monday, -7), shiftDay(monday, -1)];
    case 'month': return [monthStart(today), today];
    case 'previousMonth': return [monthStart(today, -1), shiftDay(monthStart(today), -1)];
    case 'quarter': return [monthStart(today, -2), today];
    default: return [shiftDay(today, 1 - Number(preset)), today];
  }
}
