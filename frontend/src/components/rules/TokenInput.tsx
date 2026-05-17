import React, { useState } from "react";

interface TokenInputProps {
  label: string;
  description?: string;
  placeholder?: string;
  values?: string[];
  onChange: (values: string[]) => void;
}

export const TokenInput: React.FC<TokenInputProps> = ({
  label,
  description,
  placeholder,
  values = [],
  onChange,
}) => {
  const [draft, setDraft] = useState("");

  const addDraft = () => {
    const value = draft.trim();
    if (!value) {
      return;
    }
    if (!values.includes(value)) {
      onChange([...values, value]);
    }
    setDraft("");
  };

  const removeValue = (value: string) => {
    onChange(values.filter((item) => item !== value));
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addDraft();
      return;
    }
    if (event.key === "Backspace" && !draft && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">{label}</label>
      {description && (
        <p className="text-xs leading-5 text-gray-500">{description}</p>
      )}
      <div className="flex min-h-10 flex-wrap items-center gap-2 rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm shadow-sm focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500">
        {values.map((value) => (
          <span
            key={value}
            className="inline-flex max-w-full items-center gap-1 rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700"
          >
            <span className="truncate">{value}</span>
            <button
              type="button"
              className="rounded px-0.5 text-blue-500 hover:bg-blue-100 hover:text-blue-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
              onClick={() => removeValue(value)}
              aria-label={`Remove ${value}`}
            >
              x
            </button>
          </span>
        ))}
        <input
          className="min-w-40 flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-gray-400"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={addDraft}
          placeholder={values.length === 0 ? placeholder : ""}
        />
      </div>
    </div>
  );
};
