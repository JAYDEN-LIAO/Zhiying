import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { YunzhiProvider } from "./platform/YunzhiProvider";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <YunzhiProvider>
      <App />
    </YunzhiProvider>
  </React.StrictMode>
);
