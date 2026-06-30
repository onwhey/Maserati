export type StrategyReleaseActionState = {
  ok: boolean;
  reason_code: string;
  message: string;
  release_id: number | null;
};

export const initialStrategyReleaseActionState: StrategyReleaseActionState = {
  ok: false,
  reason_code: "",
  message: "",
  release_id: null
};
