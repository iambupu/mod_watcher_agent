import { createBrowserRouter } from "react-router-dom";
import Dashboard from "@/pages/Dashboard";
import Discover from "@/pages/Discover";
import Favorites from "@/pages/Favorites";
import Updates from "@/pages/Updates";
import Rules from "@/pages/Rules";
import { RuleEditorPage } from "@/components/rules/RuleEditorPage";
import Logs from "@/pages/Logs";
import Settings from "@/pages/Settings";
import AgentChat from "@/pages/AgentChat";

export const router = createBrowserRouter([
  { path: "/", element: <Dashboard /> },
  { path: "/discover", element: <Discover /> },
  { path: "/favorites", element: <Favorites /> },
  { path: "/updates", element: <Updates /> },
  { path: "/rules", element: <Rules /> },
  { path: "/rules/new", element: <RuleEditorPage /> },
  { path: "/rules/:id/edit", element: <RuleEditorPage /> },
  { path: "/logs", element: <Logs /> },
  { path: "/agent", element: <AgentChat /> },
  { path: "/settings", element: <Settings /> },
]);
