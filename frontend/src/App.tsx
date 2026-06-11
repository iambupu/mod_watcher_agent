// 中文注释：装配前端应用根组件和路由出口。

import { RouterProvider } from "react-router-dom";
import { useEffect } from "react";
import { router } from "./app/router";
import { useSystemNotifications } from "./hooks/useSystemNotifications";
import { useSettingsSync } from "./hooks/useSettingsSync";
import { migrateTokenToCookie } from "./api/client";

function App() {
  useSystemNotifications();
  useSettingsSync();

  useEffect(() => {
    migrateTokenToCookie();
  }, []);

  return <RouterProvider router={router} />;
}

export default App;
