/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        navy:    '#0A0E1A',
        surface: '#111827',
        card:    '#1A2235',
        card2:   '#1F2B40',
        border:  '#243049',
        primary: {
          DEFAULT: '#3B82F6',
          dark:    '#2563EB',
          light:   '#60A5FA',
        },
        secondary: {
          DEFAULT: '#7C3AED',
          dark:    '#6D28D9',
          light:   '#A78BFA',
        },
        success: '#10B981',
        warning: '#F59E0B',
        danger:  '#EF4444',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', "'Segoe UI'", 'sans-serif'],
      },
      // Opacity steps used in the UI that are not in Tailwind's default scale
      // (without these, e.g. `bg-primary/12` silently generates no CSS).
      opacity: {
        6:  '0.06',
        7:  '0.07',
        8:  '0.08',
        12: '0.12',
        18: '0.18',
      },
      borderRadius: {
        card: '12px',
        btn:  '14px',
      },
      backgroundImage: {
        'gradient-blue':   'linear-gradient(135deg, #1D4ED8, #3B82F6)',
        'gradient-purple': 'linear-gradient(135deg, #6D28D9, #7C3AED)',
        'gradient-green':  'linear-gradient(135deg, #059669, #10B981)',
        'gradient-navy':   'linear-gradient(135deg, #0A0E1A, #111827)',
      },
      animation: {
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 2s cubic-bezier(0.4,0,0.6,1) infinite',
      },
      keyframes: {
        fadeIn:  { from: { opacity: '0' },                  to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
}
