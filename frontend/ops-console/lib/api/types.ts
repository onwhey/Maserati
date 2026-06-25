export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonRecord = Record<string, JsonValue | undefined>;

export type OpsApiResponse<T> =
  | {
      ok: true;
      reason_code: string;
      data: T;
    }
  | {
      ok: false;
      reason_code: string;
      message_zh: string;
      data: null;
    };

export type Pagination = {
  limit: number;
  offset: number;
  total: number;
};

export type Paginated<T> = {
  items: T[];
  pagination: Pagination;
};
