import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      keyframes: {
        "tab-flash": {
          "0%": { backgroundColor: "rgba(167, 139, 250, 0)" },
          "30%": { backgroundColor: "rgba(167, 139, 250, 0.25)" },
          "100%": { backgroundColor: "rgba(167, 139, 250, 0)" },
        },
        "triage-pulse": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(167, 139, 250, 0.3)" },
          "50%": { boxShadow: "0 0 0 4px rgba(167, 139, 250, 0)" },
        },
        "triage-complete": {
          "0%": { boxShadow: "0 0 0 0 rgba(34, 197, 94, 0.4)" },
          "50%": { boxShadow: "0 0 0 6px rgba(34, 197, 94, 0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(34, 197, 94, 0)" },
        },
        "status-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
      },
    },
  },
};

export default config;
