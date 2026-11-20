/** Friendly aliases for the schemas generated from FastAPI's OpenAPI document (src/api/schema.d.ts). */
import type { components, operations } from './schema'

type S = components['schemas']

export type Season = S['Season']
export type Team = S['Team']
export type TeamSeason = S['TeamSeason']
export type TeamWindow = S['TeamWindow']
export type LineupSummary = S['LineupSummary']
export type LineupDetail = S['LineupDetail']
export type WindowStats = S['WindowStats']
export type Change = S['Change']
export type Player = S['Player']
export type PlayerTeamSeason = S['PlayerTeamSeason']
export type Prediction = S['Prediction']
export type PredictionRequest = S['PredictionRequest']
export type Uncertainty = S['Uncertainty']
export type Contribution = S['Contribution']
export type ModelCard = S['ModelCard']
export type ModelPerformance = S['ModelPerformance']
export type EvaluationSummary = S['EvaluationSummary']
export type Estimate = S['Estimate']
export type Coefficient = S['Coefficient']
export type Health = S['Health']
export type DataStatus = S['DataStatus']
export type Page<T> = { items: T[]; page: number; page_size: number; total: number; total_pages: number }

export type LineupQuery = NonNullable<operations['list_lineups_api_v1_lineups_get']['parameters']['query']>
export type LineupSort = NonNullable<LineupQuery['sort']>
export type PlayerQuery = NonNullable<operations['list_players_api_v1_players_get']['parameters']['query']>
export type LineupRanking = S['LineupRanking']
export type RankedLineup = S['RankedLineup']
export type PredictionRanking = S['PredictionRanking']
export type RankedPrediction = S['RankedPrediction']
export type RankingQuery = NonNullable<operations['rank_lineups_api_v1_rankings_lineups_get']['parameters']['query']>
export type PredictionRankingQuery = NonNullable<operations['rank_predictions_api_v1_rankings_predictions_get']['parameters']['query']>
