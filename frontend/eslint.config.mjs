import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'

export default [
  {
    ignores: ['.next/**', 'out/**', 'build/**', 'next-env.d.ts'],
  },
  ...nextCoreWebVitals,
  {
    rules: {
      // New experimental react-hooks rules (enabled by the Next 16 bump) that
      // over-flag valid idiomatic patterns: setState in effect bodies for
      // localStorage/theme init and async loading flags, and Date.now() in
      // render for time-relative "resolving soon" badges.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/purity': 'off',
    },
  },
]
