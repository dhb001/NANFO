import { useId, useState } from "react";

export interface ChartPoint {
  time: number;
  value: number | null;
  unavailable?: string | undefined;
  samples?: number | undefined;
}

export interface ChartSeries {
  id: string;
  label: string;
  unit: string;
  points: ChartPoint[];
  interval?: number | undefined;
}

// This feature-owned chart is also used for modeled simulation histories.
export function TimeSeriesChart({ title, series, modeled = false }: {
  title: string; series: ChartSeries[]; modeled?: boolean;
}) {
  const id = useId();
  const [selected, setSelected] = useState("");
  const [tableState, setTableState] = useState({ id: "", page: 0 });
  const current = series.find((item) => item.id === selected) ?? series[0];
  const points = [...(current?.points ?? [])].filter((point) => Number.isFinite(point.time)).sort((a, b) => a.time - b.time);
  const valid = points.filter((point) => !point.unavailable && point.value !== null && Number.isFinite(point.value));
  const minTime = points[0]?.time ?? 0;
  const maxTime = points.at(-1)?.time ?? minTime;
  const values = valid.map((point) => point.value as number);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const x = (time: number) => 64 + (time - minTime) / (maxTime - minTime || 1) * 550;
  const y = (value: number) => 175 - (value - min) / (max - min || 1) * 140;
  const timeLabel = (time: number) => modeled ? `${time} ms` : new Date(time).toISOString();
  const tablePage = tableState.id === current?.id ? Math.min(tableState.page, Math.max(0, Math.ceil(points.length / 50) - 1)) : 0;
  return <section aria-label={title} style={{ minWidth: 0 }}>
    <h3>{title}</h3>
    {!current ? <p>No series available. Missing observations are not zero.</p> : <>
      <label style={{ display: "grid", gap: "0.4rem" }}>Series
        <select aria-label={`${title} series`} value={current.id} onChange={(event) => setSelected(event.target.value)} style={{ width: "100%", minWidth: 0 }}>
          {series.map((item) => <option key={item.id} value={item.id}>{item.label} [{item.unit}]</option>)}
        </select>
      </label>
      <p style={{ overflowWrap: "anywhere" }}>{current.label} | Unit: {current.unit}</p>
      <svg role="img" aria-labelledby={`${id}-title ${id}-desc`} viewBox="0 0 640 220" style={{ width: "100%", height: "auto", display: "block" }}>
        <title id={`${id}-title`}>{title}: {current.unit}</title>
        <desc id={`${id}-desc`}>{valid.length} available observations. Time increases left to right. Missing or stale values break the series. Exact values are in the keyboard-accessible data table.</desc>
        <path d="M64 25V185H614" fill="none" stroke="var(--ink-3)" />
        {valid.length > 0 && <><text x="4" y="35" fill="var(--ink-2)" fontSize="12">{max.toPrecision(4)}</text><text x="4" y="175" fill="var(--ink-2)" fontSize="12">{min.toPrecision(4)}</text></>}
        {points.map((point, index) => {
          if (point.unavailable || point.value === null || !Number.isFinite(point.value)) return null;
          const previous = points[index - 1];
          // Raw samples have no promised cadence: show points, never infer continuity.
          const connect = current.interval && previous && !previous.unavailable && previous.value !== null && Number.isFinite(previous.value) && point.time > previous.time && point.time - previous.time <= current.interval;
          return <g key={`${point.time}-${index}`}>
            {connect && <line x1={x(previous.time)} y1={y(previous.value as number)} x2={x(point.time)} y2={y(point.value)} stroke="var(--ink-2)" strokeWidth="2" />}
            <circle cx={x(point.time)} cy={y(point.value)} r="3" fill="var(--ink-2)"><title>{timeLabel(point.time)}: {point.value} {current.unit}</title></circle>
          </g>;
        })}
        <text x="64" y="207" fontSize="11" fill="var(--ink-3)">{modeled ? `${minTime} ms` : points.length ? new Date(minTime).toISOString().slice(11, 19) : "Unavailable"}</text>
        <text x="614" y="207" textAnchor="end" fontSize="11" fill="var(--ink-3)">{modeled ? `${maxTime} ms modeled` : points.length ? `${new Date(maxTime).toISOString().slice(11, 19)} UTC` : ""}</text>
      </svg>
      {valid.length === 0 && <p>Values unavailable for this series.</p>}
      <p>{modeled ? "Configured model predictions, not measurements." : "Fetched observations only, not a full-network total."} No zero-fill or interpolation across gaps. Raw samples are unconnected.</p>
      <details>
        <summary>{title} data table</summary>
        <div role="region" aria-label={`${title} table scroll area`} tabIndex={0} style={{ overflow: "auto", maxHeight: 320 }}>
          <table style={{ width: "100%" }}>
            <caption>{current.label} ({current.unit})</caption>
            <thead><tr><th scope="col">{modeled ? "Modeled elapsed time" : "Timestamp (UTC)"}</th><th scope="col">Value ({current.unit})</th><th scope="col">Samples / availability</th></tr></thead>
            <tbody>{points.slice(tablePage * 50, (tablePage + 1) * 50).map((point, index) => <tr key={`${point.time}-${index}`}><th scope="row">{timeLabel(point.time)}</th><td>{!point.unavailable && point.value !== null && Number.isFinite(point.value) ? point.value : "Unavailable"}</td><td>{point.unavailable ?? point.samples ?? "Observed"}</td></tr>)}</tbody>
          </table>
        </div>
        {points.length > 50 && <nav aria-label={`${title} table pagination`} style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
          <button type="button" disabled={tablePage === 0} onClick={() => setTableState({ id: current.id, page: tablePage - 1 })}>Previous table rows</button>
          <span>Table page {tablePage + 1} / {Math.ceil(points.length / 50)} (50 rows maximum)</span>
          <button type="button" disabled={(tablePage + 1) * 50 >= points.length} onClick={() => setTableState({ id: current.id, page: tablePage + 1 })}>Next table rows</button>
        </nav>}
      </details>
    </>}
  </section>;
}
