import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

interface KeywordFilterEditorProps {
  includeKeywords: string[];
  excludeKeywords: string[];
  onChange: (patch: Record<string, string[]>) => void;
}

const TagInput: React.FC<{
  tags: string[];
  placeholder: string;
  onAdd: (value: string) => void;
  onRemove: (index: number) => void;
}> = ({ tags, placeholder, onAdd, onRemove }) => {
  const [input, setInput] = useState("");

  const handleAdd = () => {
    const trimmed = input.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onAdd(trimmed);
      setInput("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
  };

  return (
    <div>
      <div className="flex flex-wrap gap-1 mb-1">
        {tags.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-0.5 rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-800"
          >
            {tag}
            <button
              type="button"
              onClick={() => onRemove(i)}
              className="text-blue-500 hover:text-blue-700"
            >
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={handleAdd}
        placeholder={placeholder}
        className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
    </div>
  );
};

export const KeywordFilterEditor: React.FC<KeywordFilterEditorProps> = ({
  includeKeywords,
  excludeKeywords,
  onChange,
}) => {
  const { t } = useTranslation();

  return (
    <div>
      <h4 className="text-sm font-semibold text-gray-800 mb-2">
        {t("rules.filters.keywordFilter")}
      </h4>
      <p className="mb-3 text-xs text-gray-500">
        {t("rules.filters.keywordFilterHelp")}
      </p>
      <div className="flex flex-col gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {t("rules.includeKeywords")}
          </label>
          <p className="mb-1 text-xs text-gray-500">
            {t("rules.filters.includeKeywordsHelp")}
          </p>
          <TagInput
            tags={includeKeywords}
            placeholder={t("rules.includeKeywords") + "..."}
            onAdd={(v) =>
              onChange({ includeKeywords: [...includeKeywords, v] })
            }
            onRemove={(i) =>
              onChange({
                includeKeywords: includeKeywords.filter((_, idx) => idx !== i),
              })
            }
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {t("rules.excludeKeywords")}
          </label>
          <p className="mb-1 text-xs text-gray-500">
            {t("rules.filters.excludeKeywordsHelp")}
          </p>
          <TagInput
            tags={excludeKeywords}
            placeholder={t("rules.excludeKeywords") + "..."}
            onAdd={(v) =>
              onChange({ excludeKeywords: [...excludeKeywords, v] })
            }
            onRemove={(i) =>
              onChange({
                excludeKeywords: excludeKeywords.filter((_, idx) => idx !== i),
              })
            }
          />
        </div>
      </div>
    </div>
  );
};
