import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CalendarBlank, CaretLeft, CaretRight, CaretDown, X } from '@phosphor-icons/react';
import { useI18n } from '../utils/i18n.jsx';
import { isoDay, ruDate } from '../utils/formats.js';
import { dayDate, monthDays, monthStart, presetRange, shiftDay } from '../utils/dateRange.js';
import './DateRangePicker.css';

const PRESETS = ['yesterday', 'week', 'previousWeek', 'month', 'previousMonth', 7, 30, 90];
const TEXT = {
  ru: { title: 'Выбор периода', quick: 'Быстрый выбор', period: 'Период', start: 'Выберите начало периода', end: 'Выберите конец периода', close: 'Закрыть', previous: 'Предыдущий месяц', next: 'Следующий месяц', monthLabel: 'Месяц', year: 'Год', custom: 'Количество дней', days: 'д', weeks: 'н', months: 'м', weekdays: ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'], presets: ['Вчера', 'Текущая неделя', 'Предыдущая неделя', 'Текущий месяц', 'Предыдущий месяц', 'Последние 7 дней', 'Последние 30 дней', 'Последние 90 дней'] },
  en: { title: 'Choose date range', quick: 'Quick select', period: 'Period', start: 'Choose the start date', end: 'Choose the end date', close: 'Close', previous: 'Previous month', next: 'Next month', monthLabel: 'Month', year: 'Year', custom: 'Number of days', days: 'd', weeks: 'w', months: 'm', weekdays: ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'], presets: ['Yesterday', 'This week', 'Previous week', 'This month', 'Previous month', 'Last 7 days', 'Last 30 days', 'Last 90 days'] },
};

export default function DateRangePicker({ dateFrom, dateTo, onChange }) {
  const { lang } = useI18n();
  const text = TEXT[lang] || TEXT.ru;
  const locale = lang === 'en' ? 'en-GB' : 'ru-RU';
  const today = isoDay();
  const id = useId();
  const trigger = useRef(null), panel = useRef(null);
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(() => monthStart(dateTo));
  const [anchor, setAnchor] = useState(null), [hover, setHover] = useState(null);
  const [custom, setCustom] = useState('');
  const [position, setPosition] = useState({});
  const close = () => { setOpen(false); setAnchor(null); setHover(null); trigger.current?.focus(); };
  const apply = (from, to) => { onChange({ dateFrom: from, dateTo: to }); close(); };
  const choosePreset = (key) => apply(...presetRange(key, today));

  useEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = trigger.current.getBoundingClientRect();
      const width = Math.min(780, window.innerWidth - 24);
      setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)), top: Math.min(rect.bottom + 8, Math.max(12, window.innerHeight - 220)), width, maxHeight: Math.max(180, window.innerHeight - rect.bottom - 20) });
    };
    place();
    panel.current?.focus();
    const outside = (event) => { if (!panel.current?.contains(event.target) && !trigger.current?.contains(event.target)) { setOpen(false); setAnchor(null); setHover(null); } };
    document.addEventListener('pointerdown', outside);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open]);

  // A first click only starts a draft. Fetch analytics once the complete range is chosen.
  const chooseDay = (day) => {
    if (!anchor) { setAnchor(day); setHover(day); }
    else apply(day < anchor ? day : anchor, day < anchor ? anchor : day);
  };
  const from = anchor ? (hover && hover < anchor ? hover : anchor) : dateFrom;
  const to = anchor ? (hover && hover > anchor ? hover : anchor) : dateTo;
  const months = Array.from({ length: 12 }, (_, i) => new Intl.DateTimeFormat(locale, { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2026, i, 1))));
  const years = Array.from({ length: Math.max(12, Number(today.slice(0, 4)) - 2014) }, (_, i) => Number(today.slice(0, 4)) - i);
  const keyDay = (event, day) => {
    const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key];
    if (offset == null) return;
    event.preventDefault();
    const next = shiftDay(day, offset);
    if (next > today) return;
    const element = panel.current.querySelector(`button[data-day="${next}"]:not([data-outside="true"])`);
    if (element) element.focus();
    else { setMonth(monthStart(next)); requestAnimationFrame(() => panel.current?.querySelector(`button[data-day="${next}"]:not([data-outside="true"])`)?.focus()); }
    if (anchor) setHover(next);
  };

  return <>
    <button ref={trigger} type="button" className="date-range-trigger" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => { if (open) close(); else { setMonth(monthStart(dateTo)); setAnchor(null); setHover(null); setOpen(true); } }}>
      <CalendarBlank size={21} aria-hidden="true" />
      <span>{ruDate(dateFrom).replace(/\.20(\d\d)$/, '.$1')} — {ruDate(dateTo).replace(/\.20(\d\d)$/, '.$1')}</span>
      <CaretDown size={14} aria-hidden="true" />
    </button>
    {open && createPortal(<div ref={panel} id={id} role="dialog" aria-label={text.title} tabIndex={-1} className="date-range-panel" style={position}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); close(); }
        if (event.key === 'Tab') {
          const elements = [...panel.current.querySelectorAll('button:not(:disabled), select, input')];
          const first = elements[0], last = elements[elements.length - 1];
          if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      }}>
      <div className="date-range-calendars">
        <div className="date-range-hint"><span aria-live="polite">{anchor ? text.end : text.start}</span><button type="button" aria-label={text.close} onClick={close}><X size={18} /></button></div>
        <div className="date-range-months">
          {[0, 1].map(index => {
            const displayed = monthStart(month, index), date = dayDate(displayed);
            return <section key={index} className="date-range-month" aria-label={`${months[date.getUTCMonth()]} ${date.getUTCFullYear()}`}>
              <div className="date-range-month-heading">
                {index === 0 && <button type="button" className="date-range-arrow" aria-label={text.previous} onClick={() => setMonth(monthStart(month, -1))}><CaretLeft size={18} /></button>}
                <select aria-label={`${text.monthLabel} ${index + 1}`} value={date.getUTCMonth()} onChange={e => setMonth(monthStart(`${date.getUTCFullYear()}-${String(Number(e.target.value) + 1).padStart(2, '0')}-01`, -index))}>
                  {months.map((name, i) => <option key={name} value={i}>{name}</option>)}
                </select>
                <select aria-label={`${text.year} ${index + 1}`} value={date.getUTCFullYear()} onChange={e => setMonth(monthStart(`${e.target.value}-${displayed.slice(5, 7)}-01`, -index))}>
                  {[...new Set([date.getUTCFullYear(), ...years])].sort((a, b) => b - a).map(year => <option key={year}>{year}</option>)}
                </select>
                {index === 1 && <button type="button" className="date-range-arrow" aria-label={text.next} disabled={month >= monthStart(today)} onClick={() => setMonth(monthStart(month, 1))}><CaretRight size={18} /></button>}
              </div>
              <div className="date-range-weekdays">{text.weekdays.map(day => <span key={day}>{day}</span>)}</div>
              <div className="date-range-days" onMouseLeave={() => setHover(null)}>{monthDays(displayed).map(day => {
                const outside = day.slice(0, 7) !== displayed.slice(0, 7), selected = day >= from && day <= to;
                const duplicate = index === 1 ? day < displayed : day >= monthStart(displayed, 1);
                return <button key={day} type="button" data-day={day} data-outside={outside} disabled={day > today || duplicate} aria-hidden={duplicate || undefined} aria-label={ruDate(day)} aria-pressed={selected} aria-current={day === today ? 'date' : undefined}
                  className={`${duplicate ? 'duplicate' : ''} ${outside ? 'outside' : ''} ${selected ? 'selected' : ''} ${day === from || day === to ? 'endpoint' : ''}`}
                  onClick={() => chooseDay(day)} onMouseEnter={() => anchor && setHover(day)} onFocus={() => anchor && setHover(day)} onKeyDown={e => keyDay(e, day)}>{Number(day.slice(8))}</button>;
              })}</div>
            </section>;
          })}
        </div>
      </div>
      <aside className="date-range-presets">
        <h3>{text.quick}</h3>
        {PRESETS.map((key, i) => { const range = presetRange(key, today); return <button type="button" key={key} aria-pressed={!anchor && dateFrom === range[0] && dateTo === range[1]} onClick={() => choosePreset(key)}>{text.presets[i]}</button>; })}
        <h3 className="date-range-period-title">{text.period}</h3>
        <div className="date-range-periods">
          <button type="button" onClick={() => choosePreset(7)}>7{text.days}</button>
          <button type="button" onClick={() => choosePreset(28)}>4{text.weeks}</button>
          <button type="button" onClick={() => choosePreset('quarter')}>3{text.months}</button>
          <form onSubmit={e => { e.preventDefault(); const days = Number(custom); if (Number.isInteger(days) && days > 0 && days <= 36500) choosePreset(days); }}>
            <input aria-label={text.custom} type="number" min="1" max="36500" placeholder={`42${text.days}`} value={custom} onChange={e => setCustom(e.target.value)} />
          </form>
        </div>
      </aside>
    </div>, document.body)}
  </>;
}
