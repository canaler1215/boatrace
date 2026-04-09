export type Grade = "A1" | "A2" | "B1" | "B2";
export type RaceStatus = "scheduled" | "running" | "finished" | "canceled";
export type TidalType = "満潮" | "干潮";

export interface Stadium {
  id: number;
  name: string;
  location?: string;
  waterType?: string;
  inWinRate?: number;
}

export interface Racer {
  id: number;
  name: string;
  grade?: Grade;
  winRate?: number;
  weight?: number;
}

export interface Race {
  id: string; // {stadium_id}{yyyymmdd}{race_no}
  stadiumId: number;
  raceDate: string; // YYYY-MM-DD
  raceNo: number;
  grade?: string;
  status: RaceStatus;
}

export interface RaceEntry {
  id: number;
  raceId: string;
  boatNo: number;
  racerId?: number;
  motorWinRate?: number;
  boatWinRate?: number;
  exhibitionTime?: number;
  startTiming?: number;
  finishPosition?: number;
}

export interface Prediction {
  id: number;
  raceId: string;
  combination: string; // 例: "1-2-3"
  winProbability: number;
  expectedValue: number;
  alertFlag: boolean;
  predictedAt: Date;
}

export interface Bet {
  id: number;
  raceId: string;
  combination: string;
  amount: number;
  oddsAtBet?: number;
  isWin?: boolean;
  payout: number;
  note?: string;
  bettedAt: Date;
}
