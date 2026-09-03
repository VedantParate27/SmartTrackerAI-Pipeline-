//  @ts-check

import { tanstackConfig } from '@tanstack/eslint-config'

export default [
  ...tanstackConfig,
  {
    rules: {
      'import/no-cycle': 'off',
      'import/order': 'off',
      'sort-imports': 'off',
      '@typescript-eslint/array-type': 'off',
      '@typescript-eslint/require-await': 'off',
      'pnpm/json-enforce-catalog': 'off',
    },
  },
  {
    ignores: [
      'eslint.config.js',
      'prettier.config.js',
      // Build artifacts: dist/ and dist-ssr/ from Vite, .output/ from Nitro,
      // .vercel/output/ from the Vercel preset.
      'dist/**',
      'dist-ssr/**',
      '.output/**',
      '.vercel/**',
      '.nitro/**',
      '.tanstack/**',
    ],
  },
]
