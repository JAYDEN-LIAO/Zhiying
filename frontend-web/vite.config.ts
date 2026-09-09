import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    fs: {
      // 允许加载共享后端对接层 frontend-shared/（在 frontend-web/ 之外，dev 需显式放行）
      allow: [".", "../frontend-shared"],
    },
    proxy: {
      "/api": "http://localhost:8011",
      "/videos": "http://localhost:8011",
    },
  },
});
