// 中文注释：提供规则编辑器里的 RuleTestResultPanel 表单组件。

import React from "react";
import { useTranslation } from "react-i18next";
import { Card, CardHeader, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { RuleTestResponse } from "@/types";

interface RuleTestResultPanelProps {
  result?: RuleTestResponse | null;
}

const PREVIEW_ITEM_LIMIT = 5;

export const RuleTestResultPanel: React.FC<RuleTestResultPanelProps> = ({ result }) => {
  const { t } = useTranslation();

  if (!result || (result.scanned === 0 && result.items.length === 0)) {
    return (
      <Card>
        <CardContent>
          <p className="text-gray-500 text-center py-6">{t("rules.test.noResults")}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* ── Stats ─────────────────────────────── */}
      <Card>
        <CardHeader>
          <h3 className="text-sm font-semibold text-gray-700">{t("rules.test.title")}</h3>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatBox label={t("rules.test.scanned")} value={result.scanned} />
            <StatBox label={t("rules.test.normalized")} value={result.normalized} />
            <StatBox label={t("rules.test.passedDeterministic")} value={result.passedDeterministicFilters} />
            <StatBox label={t("rules.test.passedLlm")} value={result.passedLlmFilters} />
          </div>
        </CardContent>
      </Card>

      {/* ── Rejected Reasons ──────────────────── */}
      {Object.keys(result.rejectedReasons).length > 0 && (
        <Card>
          <CardHeader>
            <h3 className="text-sm font-semibold text-gray-700">{t("rules.test.rejectedReasons")}</h3>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1">
              {Object.entries(result.rejectedReasons).map(([reason, count]) => (
                <li key={reason} className="flex items-start gap-2 text-sm text-gray-600">
                  <span className="text-red-400 mt-0.5">&#x2022;</span>
                  <span>
                    {t(`rules.test.reason.${reason}`, reason)}: {count}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {result.rejectedItems.length > 0 && (
        <Card>
          <CardHeader>
            <h3 className="text-sm font-semibold text-gray-700">
              {t("rules.test.rejectedItems", { count: result.rejectedItems.length })}
            </h3>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {result.rejectedItems.slice(0, PREVIEW_ITEM_LIMIT).map((item, idx) => (
                <div
                  key={`${item.source}-${item.externalId}-${idx}`}
                  className="rounded-md border border-gray-100 px-3 py-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800 truncate">{item.title || item.externalId}</span>
                    {item.externalId && (
                      <span className="text-xs text-gray-400">{item.externalId}</span>
                    )}
                    <Badge variant="warning">{t(`rules.test.stage.${item.stage}`, item.stage)}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-gray-600">
                    {t(`rules.test.reason.${item.reason}`, item.reason)}
                  </div>
                  {item.llmFeedback && (
                    <div className="mt-1 rounded bg-gray-50 px-2 py-1 text-xs text-gray-500">
                      {t("rules.test.llmFeedback")}: {item.llmFeedback}
                    </div>
                  )}
                  <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                    <span>{item.game}</span>
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-500 hover:underline truncate"
                      >
                        {item.url}
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Items List ────────────────────────── */}
      {result.items.length > 0 && (
        <Card>
          <CardHeader>
            <h3 className="text-sm font-semibold text-gray-700">
              {t("rules.matchCount", { count: result.items.length })}
            </h3>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {result.items.slice(0, PREVIEW_ITEM_LIMIT).map((item) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between rounded-md border border-gray-100 px-3 py-2 text-sm"
                >
                  <div className="flex-1 min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-800 truncate">{item.title}</span>
                      {item.external_id && (
                        <span className="text-xs text-gray-400">{item.external_id}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <span>{item.game}</span>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-500 hover:underline truncate"
                        >
                          {item.url}
                        </a>
                      )}
                    </div>
                  </div>
                  <Badge variant="success">Passed</Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-gray-50 px-3 py-2.5 text-center">
      <div className="text-xl font-bold text-gray-800">{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  );
}
