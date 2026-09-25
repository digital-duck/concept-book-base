// App-level branding overrides for derived apps. A fork can edit this file
// alone (instead of touching Header.js) to swap in its own logo/title.
export const appConfig = {
  // When set, Header renders this image instead of the i18n `app.title` text.
  logoImage: null,
  // Use UI strings of languages not yet reviewed — locales/ui.yaml status
  // `machine` (LLM-drafted by scripts/translate_locale.py) or `draft` (started
  // on the Manage → i18n tab). Off: those languages show the UI in English.
  showMachineLocales: false,
}
