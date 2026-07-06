import { StyleProvider } from "@ant-design/cssinjs";
import { QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import viVN from "antd/locale/vi_VN";
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import "antd/dist/reset.css";
import { queryClient } from "./api/queryClient.js";
import { makeAntdTheme } from "./lib/antdTheme.js";
import { ThemeProvider, useTheme } from "./lib/ThemeContext.jsx";
import { router } from "./routes.jsx";
import "./index.css";

// Reads the current theme mode and feeds the matching antd config to
// ConfigProvider, so antd components flip with the CSS-variable palette.
function ThemedApp() {
  const { mode } = useTheme();
  return (
    <StyleProvider layer>
      <ConfigProvider theme={makeAntdTheme(mode)} locale={viVN}>
        <AntApp>
          <QueryClientProvider client={queryClient}>
            <RouterProvider router={router} />
          </QueryClientProvider>
        </AntApp>
      </ConfigProvider>
    </StyleProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  </React.StrictMode>
);
