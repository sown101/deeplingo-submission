import type { ReactNode, SelectHTMLAttributes } from "react";

export function SelectField({ id, label, inset = false, className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & {
  id: string;
  label: ReactNode;
  inset?: boolean;
}) {
  return <label className="dl-field" htmlFor={id}><span>{label}</span>
    <select {...props} id={id} className={`dl-select${inset ? " dl-select--inset" : ""}${className ? ` ${className}` : ""}`}>{children}</select>
  </label>;
}

export function SegmentedControl<Value extends string>({ label, items, value, onChange, idPrefix, panelId }: {
  label: string;
  items: readonly { value: Value; label: ReactNode; icon?: ReactNode }[];
  value: Value;
  onChange: (value: Value) => void;
  idPrefix: string;
  panelId: (value: Value) => string;
}) {
  return <div className="mode-tabs dl-segmented" role="tablist" aria-label={label}>
    {items.map(item => <button key={item.value} type="button" role="tab" id={`${idPrefix}-${item.value}`}
      aria-selected={value === item.value} aria-controls={panelId(item.value)}
      className={value === item.value ? "mode-tab active" : "mode-tab"} onClick={() => onChange(item.value)}>
      {item.icon}<span>{item.label}</span>
    </button>)}
  </div>;
}
