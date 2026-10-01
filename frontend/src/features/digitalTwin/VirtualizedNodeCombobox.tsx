import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  COMBOBOX_ROW_HEIGHT,
  COMBOBOX_VISIBLE_ROWS,
  buildSearchIndex,
  filterIndexed,
  isComboboxKey,
  moveActive,
  scrollToIndex,
  visibleWindow,
  type ComboboxOption,
} from "./comboboxWindow";

/**
 * ARIA 1.2 combobox with a virtualized listbox: only the visible window of options is in
 * the DOM (instead of a 12,800-option `<select>`), options expose aria-setsize/posinset,
 * and the whole flow works from the keyboard (type to filter, arrows/Page/Home/End,
 * Enter to select, Escape to close). This is the keyboard alternative to 3D picking.
 */
export function VirtualizedNodeCombobox({ label, ariaLabel, options, selectedId, onSelect, placeholder = "Type a hostname, type or device id" }: {
  label: string;
  ariaLabel: string;
  options: readonly ComboboxOption[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  placeholder?: string;
}) {
  const baseId = useId();
  const inputId = `${baseId}-input`;
  const listId = `${baseId}-listbox`;
  const statusId = `${baseId}-status`;
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [scrollTop, setScrollTop] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const index = useMemo(() => buildSearchIndex(options), [options]);
  const selected = useMemo(() => options.find((option) => option.id === selectedId) ?? null, [options, selectedId]);
  const matches = useMemo(() => filterIndexed(index, editing ? query : ""), [index, editing, query]);
  const { start, end } = visibleWindow(matches.length, scrollTop);
  const optionId = (position: number) => `${baseId}-option-${position}`;
  const viewportHeight = Math.max(1, Math.min(matches.length, COMBOBOX_VISIBLE_ROWS)) * COMBOBOX_ROW_HEIGHT;

  function setScroll(value: number) {
    setScrollTop(value);
    if (list.current) list.current.scrollTop = value;
  }

  function activate(position: number) {
    setActive(position);
    if (position >= 0) setScroll(scrollToIndex(position, scrollTop));
  }

  function openList() {
    if (open) return;
    setOpen(true);
    const position = selected ? matches.findIndex((option) => option.id === selected.id) : -1;
    setActive(position);
    setScroll(position >= 0 ? scrollToIndex(position, 0) : 0);
  }

  function close() {
    setOpen(false);
    setEditing(false);
    setQuery("");
    setActive(-1);
  }

  function choose(position: number) {
    const option = matches[position];
    if (!option) return;
    onSelect(option.id);
    close();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (isComboboxKey(event.key)) {
      event.preventDefault();
      if (!open) { openList(); return; }
      activate(moveActive(active, event.key, matches.length));
      return;
    }
    if (event.key === "Enter") {
      if (!open) return;
      event.preventDefault();
      choose(active >= 0 ? active : 0);
      return;
    }
    if (event.key === "Escape" && (open || editing)) {
      event.preventDefault();
      close();
    }
  }

  const status = open ? `${matches.length} matching node${matches.length === 1 ? "" : "s"}` : selected ? `Selected ${selected.label}` : "No node selected";
  return (
    <div className="twin-combobox">
      <label className="mono twin-field-label" htmlFor={inputId}>{label}</label>
      <div className="twin-combobox-control">
        <input
          id={inputId}
          className="twin-input"
          role="combobox"
          aria-label={ariaLabel}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && active >= 0 && active < matches.length ? optionId(active) : undefined}
          aria-describedby={statusId}
          data-selected-node-id={selectedId ?? ""}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={editing ? query : selected?.label ?? ""}
          onChange={(event) => {
            setEditing(true);
            setQuery(event.target.value);
            setOpen(true);
            setActive(event.target.value.trim() ? 0 : -1);
            setScroll(0);
          }}
          onClick={openList}
          onFocus={(event) => event.currentTarget.select()}
          onKeyDown={onKeyDown}
          onBlur={close}
        />
        {selectedId ? (
          <button type="button" className="twin-icon-button" aria-label="Clear node selection" onMouseDown={(event) => event.preventDefault()} onClick={() => { onSelect(null); close(); }}>
            <span aria-hidden="true">×</span>
          </button>
        ) : null}
      </div>
      <span id={statusId} role="status" aria-live="polite" className="twin-visually-hidden">{status}</span>
      {open ? (
        <div
          ref={list}
          id={listId}
          role="listbox"
          aria-label="Matching nodes"
          className="twin-listbox"
          style={{ height: viewportHeight }}
          onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        >
          {matches.length === 0 ? <div className="twin-listbox-empty">No matching nodes</div> : null}
          <div className="twin-listbox-spacer" style={{ height: matches.length * COMBOBOX_ROW_HEIGHT }}>
            {matches.slice(start, end).map((option, offset) => {
              const position = start + offset;
              return (
                <div
                  key={option.id}
                  id={optionId(position)}
                  role="option"
                  aria-selected={option.id === selectedId}
                  aria-setsize={matches.length}
                  aria-posinset={position + 1}
                  className={`twin-option${position === active ? " twin-option--active" : ""}`}
                  style={{ top: position * COMBOBOX_ROW_HEIGHT, height: COMBOBOX_ROW_HEIGHT }}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActive(position)}
                  onClick={() => choose(position)}
                >
                  {option.label}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
