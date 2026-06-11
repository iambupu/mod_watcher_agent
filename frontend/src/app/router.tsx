// 中文注释：配置前端应用级 router 基础设施。

import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router-dom";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Discover = lazy(() => import("@/pages/Discover"));
const Favorites = lazy(() => import("@/pages/Favorites"));
const Updates = lazy(() => import("@/pages/Updates"));
const Rules = lazy(() => import("@/pages/Rules"));
const RuleEditorPage = lazy(() =>
  import("@/components/rules/RuleEditorPage").then((module) => ({ default: module.RuleEditorPage })),
);
const Logs = lazy(() => import("@/pages/Logs"));
const Settings = lazy(() => import("@/pages/Settings"));
const AgentChat = lazy(() => import("@/pages/AgentChat"));

function page(element: ReactNode) {
  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      {element}
    </Suspense>
  );
}

export const router = createBrowserRouter([
  { path: "/", element: page(<Dashboard />) },
  { path: "/discover", element: page(<Discover />) },
  { path: "/favorites", element: page(<Favorites />) },
  { path: "/updates", element: page(<Updates />) },
  { path: "/rules", element: page(<Rules />) },
  { path: "/rules/new", element: page(<RuleEditorPage />) },
  { path: "/rules/:id/edit", element: page(<RuleEditorPage />) },
  { path: "/logs", element: page(<Logs />) },
  { path: "/agent", element: page(<AgentChat />) },
  { path: "/settings", element: page(<Settings />) },
]);
