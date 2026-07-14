import { AlertTriangle, FolderOpen, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { RuntimePathsInfo } from "@/api/settings";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

interface StoragePathsCardProps {
  runtimePaths?: RuntimePathsInfo;
  databasePath: string;
  onDatabasePathChange: (value: string) => void;
  onOpenConfigDirectory: () => void;
  openingConfigDirectory: boolean;
  openError?: string | null;
}

export function StoragePathsCard({
  runtimePaths,
  databasePath,
  onDatabasePathChange,
  onOpenConfigDirectory,
  openingConfigDirectory,
  openError,
}: StoragePathsCardProps) {
  const { t } = useTranslation();
  const configDir = runtimePaths?.configDir || t("settings.pathUnavailable");
  const defaultDatabasePath = runtimePaths?.defaultDatabasePath || t("settings.pathUnavailable");

  return (
    <Card className="overflow-hidden">
      <CardHeader className="bg-slate-50/70">
        <h3 className="font-semibold text-slate-900">{t("settings.storagePaths")}</h3>
      </CardHeader>
      <CardContent className="space-y-4">
        <section className="rounded-lg border border-sky-100 bg-sky-50/60 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-slate-900">{t("settings.configDirectory")}</p>
              <p className="mt-1 break-all font-mono text-xs leading-5 text-slate-700">{configDir}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="h-8 shrink-0 gap-1.5 border-sky-200 text-sky-800 hover:bg-sky-100"
              onClick={onOpenConfigDirectory}
              disabled={!runtimePaths || openingConfigDirectory}
            >
              {openingConfigDirectory ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <FolderOpen className="h-4 w-4" aria-hidden="true" />
              )}
              {t("settings.openConfigDirectory")}
            </Button>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">{t("settings.configDirectoryHint")}</p>
          {openError && (
            <p role="alert" className="mt-2 text-xs font-medium text-rose-700">
              {openError}
            </p>
          )}
        </section>

        <section className="space-y-2 border-t border-slate-100 pt-4">
          <label className="text-sm font-semibold text-slate-900" htmlFor="database-path">
            {t("settings.databasePath")}
          </label>
          <Input
            id="database-path"
            value={databasePath}
            onChange={(event) => onDatabasePathChange(event.target.value)}
            placeholder="sqlite:///./mod_watcher.db"
          />
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <p className="text-xs font-semibold text-slate-600">{t("settings.defaultDatabasePath")}</p>
            <p className="mt-1 break-all font-mono text-xs leading-5 text-slate-700">{defaultDatabasePath}</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">{t("settings.defaultDatabasePathHint")}</p>
          </div>
          <div
            role="note"
            className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-amber-950 shadow-sm"
          >
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <AlertTriangle className="h-4 w-4" strokeWidth={2.25} aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold leading-5">{t("settings.databasePathRestartTitle")}</p>
              <p className="mt-0.5 text-xs leading-5 text-amber-800">{t("settings.databasePathHint")}</p>
            </div>
          </div>
          <p className="text-xs leading-5 text-slate-500">{t("settings.databasePathResolveHint")}</p>
        </section>
      </CardContent>
    </Card>
  );
}
