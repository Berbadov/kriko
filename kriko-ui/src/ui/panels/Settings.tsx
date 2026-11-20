/** The Settings screen now lives in `src/screens/Settings.tsx` and its sections in
 *  `src/ui/settings/`. These names remain for the drawer and for Setup, which
 *  still import them from here. */
export { SettingsScreen as SettingsPanel } from '../../screens/Settings'
export { AboutPage, SharedAccessGroup } from '../settings/parts'
