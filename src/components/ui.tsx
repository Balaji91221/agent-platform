'use client';

import type { ReactNode } from 'react';

type SwitchProps = {
  pressed: boolean;
  label: string;
  onToggle: () => void;
};

export function Switch({ pressed, label, onToggle }: SwitchProps) {
  return (
    <button className="sw" aria-pressed={pressed} aria-label={label} onClick={onToggle} />
  );
}

type SegmentedProps = {
  options: string[];
  /* indices that read as pressed */
  active: number[];
  onSelect: (index: number) => void;
  id?: string;
};

export function Segmented({ options, active, onSelect, id }: SegmentedProps) {
  return (
    <div className="seg" id={id}>
      {options.map((label, i) => (
        <button key={label} aria-pressed={active.includes(i)} onClick={() => onSelect(i)}>
          {label}
        </button>
      ))}
    </div>
  );
}

type PageHeadProps = {
  title: string;
  blurb?: ReactNode;
  actions?: ReactNode;
};

export function PageHead({ title, blurb, actions }: PageHeadProps) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {blurb ? <p>{blurb}</p> : null}
      </div>
      {actions}
    </div>
  );
}

type CardHeadProps = {
  title: string;
  blurb?: ReactNode;
  aside?: ReactNode;
};

export function CardHead({ title, blurb, aside }: CardHeadProps) {
  return (
    <div className="card-head">
      <div>
        <h2>{title}</h2>
        {blurb ? <p>{blurb}</p> : null}
      </div>
      {aside}
    </div>
  );
}
