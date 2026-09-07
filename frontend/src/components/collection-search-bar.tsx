"use client";

import type { ReactNode } from "react";

type CollectionSearchBarProps = {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  shownCount: number;
  totalCount: number;
  noun: string;
  children?: ReactNode;
  compact?: boolean;
};

export function CollectionSearchBar({
  label,
  placeholder,
  value,
  onChange,
  shownCount,
  totalCount,
  noun,
  children,
  compact = false,
}: CollectionSearchBarProps) {
  return (
    <div
      className={
        compact
          ? "border-b border-slate-200 p-4"
          : "rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"
      }
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-end">
        <label className="min-w-0 flex-1 text-sm font-bold text-slate-700">
          {label}
          <input
            type="search"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            className="mt-1.5 w-full rounded-xl border border-slate-300 px-3 py-2 font-normal text-slate-950 placeholder:text-slate-400"
          />
        </label>
        {children}
      </div>
      <p className="mt-3 text-xs font-medium text-slate-500" aria-live="polite">
        Showing {shownCount} of {totalCount} {noun}
      </p>
    </div>
  );
}
