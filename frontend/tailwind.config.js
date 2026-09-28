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
        xynapse: {
          bg: '#0B0F17',
          surface: '#121824',
          card: '#161F30',
          border: '#223048',
          accent: '#00F0FF',
          accentGlow: 'rgba(0, 240, 255, 0.15)',
          alert: '#FF2A55',
          alertGlow: 'rgba(255, 42, 85, 0.2)',
          success: '#00FFA3',
          warning: '#FFB800'
        }
      },
      fontFamily: {
        display: ['Outfit', 'Plus Jakarta Sans', '-apple-system', 'sans-serif'],
        sans: ['Plus Jakarta Sans', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'Cascadia Code', 'monospace']
      }
    },
  },
  plugins: [],
}
