import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-router")) return "vendor";
          if (id.includes("node_modules/recharts")) return "charts";
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:18080",
      "/health": "http://localhost:18080",
      "/ready": "http://localhost:18080",
      "/metrics": "http://localhost:18080",
    },
  },
});
