/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Page layers — darkest to lightest
        base:    '#050e0a',
        surface: '#071510',
        card:    '#091a13',
        elevated:'#102318',
        border:  '#163322',

        // Accents — cyber green primary
        accent:  '#00e676',
        success: '#00e676',
        warning: '#f59e0b',
        danger:  '#ff4d4d',
        violet:  '#c084fc',
        cyan:    '#22d3ee',
        muted:   '#4ade80',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}
