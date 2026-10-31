/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        noc: {
          bg: '#0B0D14',
          panel: '#121624',
          subpanel: '#1A2035',
          border: '#242C47',
          hover: '#2D375B',
          text: '#F1F5F9',
          muted: '#94A3B8',
          accent: '#818CF8',
          accentDim: '#4F46E5',
          cyan: '#38BDF8',
          amethyst: '#C7A7EF',
          green: '#10B981',
          yellow: '#F59E0B',
          red: '#F43F5E',
          purple: '#A855F7',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Menlo', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
