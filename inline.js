
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            primary: 'var(--color-primary)',
            accent: 'var(--color-accent)',
            'accent-blue': 'var(--color-accent-blue)',
            warm: 'var(--color-warm)',
            surface: 'var(--color-surface)',
            background: 'var(--color-bg)',
            border: 'var(--color-border)',
            'text-primary': 'var(--color-text-primary)',
            'text-secondary': 'var(--color-text-secondary)',
            'text-tertiary': 'var(--color-text-tertiary)',
          },
          fontFamily: {
            display: ['"DM Serif Display"', 'PingFang SC', 'Microsoft YaHei', 'serif'],
            body: ['"DM Sans"', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
            mono: ['"JetBrains Mono"', 'monospace'],
          },
          boxShadow: {
            'soft': '0 4px 20px -2px rgba(30, 58, 95, 0.08)',
            'glow': '0 0 40px -10px rgba(6, 182, 212, 0.25)',
            'card': '0 1px 3px rgba(0,0,0,0.04), 0 12px 24px -8px rgba(30, 58, 95, 0.08)',
          },
          borderRadius: {
            'card': '16px',
            'button': '10px',
          },
          animation: {
            'fade-in-up': 'fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards',
            'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
            'shimmer': 'shimmer 2s infinite',
            'float': 'float 6s ease-in-out infinite',
          },
          keyframes: {
            fadeInUp: {
              '0%': { opacity: '0', transform: 'translateY(24px)' },
              '100%': { opacity: '1', transform: 'translateY(0)' },
            },
            pulseSoft: {
              '0%, 100%': { opacity: '1' },
              '50%': { opacity: '0.6' },
            },
            shimmer: {
              '0%': { backgroundPosition: '-200% 0' },
              '100%': { backgroundPosition: '200% 0' },
            },
            float: {
              '0%, 100%': { transform: 'translateY(0)' },
              '50%': { transform: 'translateY(-12px)' },
            },
          },
        }
      }
    }
  