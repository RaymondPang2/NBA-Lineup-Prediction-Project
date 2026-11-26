/**
 * Public demo build (VITE_DEMO_MODE=1): the API serves a SYNTHETIC league (fictional teams, players and statistics),
 * because NBA.com's terms allow its statistics only for private, non-commercial use. The UI says so on every page.
 */
export const isDemo = (flag: string | undefined = import.meta.env.VITE_DEMO_MODE): boolean => flag === '1' || flag === 'true'

export const REPO_URL = 'https://github.com/RaymondPang2/NBA-Lineup-Prediction-Project'
