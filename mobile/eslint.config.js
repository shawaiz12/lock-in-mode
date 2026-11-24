// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    // Generated from the API's OpenAPI schema: never edited by hand, so never linted.
    ignores: ['dist/*', 'src/api/schema.d.ts'],
  },
]);
