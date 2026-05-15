import { RouterProvider } from "react-router-dom";
import { router } from "./app/router";
import { useSystemNotifications } from "./hooks/useSystemNotifications";
import { useSettingsSync } from "./hooks/useSettingsSync";

function App() {
  useSystemNotifications();
  useSettingsSync();
  return <RouterProvider router={router} />;
}

export default App;
